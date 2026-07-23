from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from adapter_sdk import Adapter, AdapterOutput, ProviderEnvelope
from forex_contracts import (
    DataQualityEvent,
    PriceTick,
    QualityStatus,
    RawProviderEvent,
    instrument_spec,
    is_supported_instrument,
)
from forex_contracts.models import canonical_hash, utc_now

from ic_markets_adapter.redaction import redact

MAX_PAYLOAD_BYTES = 256 * 1024


@dataclass
class QuoteState:
    bid: Decimal
    ask: Decimal
    updated_at: datetime
    order_time: datetime
    sequence: int | None


class IcMarketsAdapter(Adapter):
    """Normalizer for the discovery bridge's provider-neutral capture envelope.

    The nested quote field mapping is intentionally the bridge contract, not a claim
    about an undiscovered IC Markets wire schema.
    """

    def __init__(
        self,
        instance_id: str = "icm-local-01",
        partial_state_max_age: timedelta = timedelta(seconds=2),
        max_future_skew: timedelta = timedelta(seconds=2),
        extreme_spread_pips: Decimal | None = None,
        extreme_jump_pips: Decimal | None = None,
        dedup_cache_max_entries: int = 100_000,
        dedup_cache_ttl: timedelta = timedelta(hours=1),
        max_browser_to_collector_delay: timedelta = timedelta(seconds=30),
        reject_negative_browser_to_collector_delay: bool = False,
        reject_excessive_browser_to_collector_delay: bool = False,
        reject_local_wall_clock_adjustment: bool = False,
        missing_observation_sequence_severity: str = "ERROR",
        non_increasing_observation_sequence_severity: str = "ERROR",
    ) -> None:
        self.instance_id = instance_id
        self.partial_state_max_age = partial_state_max_age
        self.max_future_skew = max_future_skew
        self.extreme_spread_pips = extreme_spread_pips
        self.extreme_jump_pips = extreme_jump_pips
        self.dedup_cache_max_entries = max(1, dedup_cache_max_entries)
        self.dedup_cache_ttl = dedup_cache_ttl
        self.max_browser_to_collector_delay = max_browser_to_collector_delay
        self.reject_negative_browser_to_collector_delay = reject_negative_browser_to_collector_delay
        self.reject_excessive_browser_to_collector_delay = (
            reject_excessive_browser_to_collector_delay
        )
        self.reject_local_wall_clock_adjustment = reject_local_wall_clock_adjustment
        self.missing_observation_sequence_severity = missing_observation_sequence_severity
        self.non_increasing_observation_sequence_severity = (
            non_increasing_observation_sequence_severity
        )
        self._state: dict[tuple[str, str, str], QuoteState] = {}
        self._seen: OrderedDict[str, tuple[datetime, tuple[str, str, str]]] = OrderedDict()

    @property
    def dedup_cache_size(self) -> int:
        return len(self._seen)

    def _purge_seen(self, now: datetime) -> None:
        cutoff = now - self.dedup_cache_ttl
        while self._seen:
            _, (seen_at, _) = next(iter(self._seen.items()))
            if seen_at >= cutoff:
                break
            self._seen.popitem(last=False)
        while len(self._seen) >= self.dedup_cache_max_entries:
            self._seen.popitem(last=False)

    def on_disconnect(self, connection_id: str, session_id: str) -> None:
        for key in list(self._state):
            if key[0] == connection_id and key[1] == session_id:
                del self._state[key]
        for dedup, (_, key) in list(self._seen.items()):
            if key[0] == connection_id and key[1] == session_id:
                del self._seen[dedup]

    def _quality(
        self,
        raw: RawProviderEvent,
        rule_id: str,
        classification: QualityStatus,
        expected: str,
        action: str = "tick_not_published",
        observed: str | None = None,
        severity: str = "ERROR",
    ) -> DataQualityEvent:
        return DataQualityEvent(
            related_event_id=raw.event_id,
            instrument=raw.instrument or "UNKNOWN",
            severity=severity,  # type: ignore[arg-type]
            rule_id=rule_id,
            classification=classification,
            observed_value=observed,
            expected_condition=expected,
            action_taken=action,
            trace_id=raw.trace_id,
        )

    @staticmethod
    def _parse_decimal(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    def process(self, envelope: ProviderEnvelope) -> AdapterOutput:
        collector_received_at = envelope.collector_received_at or envelope.received_at
        browser_observed_at = envelope.browser_observed_at or envelope.received_at
        self._purge_seen(collector_received_at)
        sanitized, redactions = redact(envelope.payload)
        is_visible_dom = isinstance(sanitized, dict) and (
            sanitized.get("observation_source") == "visible_dom"
            or envelope.channel_metadata.get("observation_level") == "DISPLAY_QUOTE"
        )
        raw_values: dict[str, Any] = {
            **({"event_id": envelope.event_id} if envelope.event_id is not None else {}),
            "adapter_instance_id": self.instance_id,
            "connection_id": envelope.connection_id,
            "session_id": envelope.session_id,
            "instrument": (
                str(sanitized.get("instrument")) if isinstance(sanitized, dict) else None
            ),
            "received_at": envelope.received_at,
            "browser_observed_at": browser_observed_at if is_visible_dom else None,
            "collector_received_at": collector_received_at if is_visible_dom else None,
            "document_session_id": envelope.document_session_id if is_visible_dom else None,
            "observation_sequence": (envelope.observation_sequence if is_visible_dom else None),
            "browser_to_collector_delay_ms": (
                (collector_received_at - browser_observed_at).total_seconds() * 1000
                if is_visible_dom
                else None
            ),
            "payload_content_type": envelope.payload_content_type,
            "payload": sanitized,
            "content_hash": canonical_hash(sanitized),
            "channel_metadata": envelope.channel_metadata,
            "redaction_status": "SANITIZED" if redactions else "NOT_REQUIRED",
            "redactions": redactions,
        }
        raw = RawProviderEvent(
            **raw_values,
        )
        if len(str(sanitized).encode()) > MAX_PAYLOAD_BYTES:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(raw, "STRUCT_PAYLOAD_SIZE", QualityStatus.BAD, "<= 262144 bytes")
                ],
            )
        if not isinstance(sanitized, dict):
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "STRUCT_PAYLOAD_OBJECT",
                        QualityStatus.UNPARSEABLE,
                        "JSON object bridge envelope",
                    )
                ],
            )

        instrument = sanitized.get("instrument")
        if not is_supported_instrument(instrument):
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "STRUCT_INSTRUMENT",
                        QualityStatus.BAD,
                        "instrument exists in the canonical registry",
                        observed=str(instrument),
                    )
                ],
            )

        provider_time_value = sanitized.get("provider_event_time")
        provider_time = None if is_visible_dom else self._parse_time(provider_time_value)
        if not is_visible_dom and provider_time_value is not None and provider_time is None:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "TIME_PARSE_UTC",
                        QualityStatus.UNPARSEABLE,
                        "timezone-aware provider_event_time",
                        observed=str(provider_time_value),
                    )
                ],
            )
        raw.provider_event_time = provider_time
        if (
            provider_time is not None
            and provider_time > envelope.received_at + self.max_future_skew
        ):
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "TIME_FUTURE_SKEW",
                        QualityStatus.BAD,
                        f"provider time <= receive time + {self.max_future_skew.total_seconds()}s",
                    )
                ],
            )

        sequence_value = sanitized.get("sequence")
        sequence = (
            envelope.observation_sequence
            if is_visible_dom
            else sequence_value
            if isinstance(sequence_value, int)
            else None
        )
        bid = self._parse_decimal(sanitized.get("bid"))
        ask = self._parse_decimal(sanitized.get("ask"))
        spec = instrument_spec(instrument)
        pip_size = spec["pip_size"]
        minimum = spec["broad_min_price"]
        maximum = spec["broad_max_price"]
        spread_limit = self.extreme_spread_pips or spec["extreme_spread_pips"]
        jump_limit = self.extreme_jump_pips or spec["extreme_jump_pips"]
        assert isinstance(pip_size, Decimal)
        assert isinstance(minimum, Decimal)
        assert isinstance(maximum, Decimal)
        assert isinstance(spread_limit, Decimal)
        assert isinstance(jump_limit, Decimal)
        key = (envelope.connection_id, envelope.session_id, instrument)
        previous = self._state.get(key)
        changed_fields: list[str] = []

        if is_visible_dom and sequence is None:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "SEQ_OBSERVATION_MISSING",
                        QualityStatus.BAD,
                        "positive observation_sequence for each document session and instrument",
                        severity=self.missing_observation_sequence_severity,
                    )
                ],
            )
        persisted_last_sequence = envelope.channel_metadata.get(
            "persisted_last_observation_sequence"
        )
        if (
            is_visible_dom
            and sequence is not None
            and isinstance(persisted_last_sequence, int)
            and sequence <= persisted_last_sequence
            and (previous is None or previous.sequence is None)
        ):
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        (
                            "SEQ_REPEATED"
                            if sequence == persisted_last_sequence
                            else "SEQ_OUT_OF_ORDER"
                        ),
                        (
                            QualityStatus.DUPLICATE
                            if sequence == persisted_last_sequence
                            else QualityStatus.OUT_OF_ORDER
                        ),
                        (
                            "strictly increasing observation_sequence within "
                            "document_session_id + instrument, including collector restarts"
                        ),
                        action="tick_suppressed",
                        severity=self.non_increasing_observation_sequence_severity,
                    )
                ],
            )

        if envelope.semantics == "snapshot":
            if bid is None or ask is None:
                missing = "bid" if bid is None else "ask"
                return AdapterOutput(
                    raw_event=raw,
                    quality_events=[
                        self._quality(
                            raw,
                            f"SNAPSHOT_MISSING_{missing.upper()}",
                            QualityStatus.BAD,
                            "snapshot contains numeric bid and ask",
                        )
                    ],
                )
            changed_fields = ["bid", "ask"]
            is_snapshot = True
        elif envelope.semantics == "partial":
            if (bid is None) == (ask is None):
                return AdapterOutput(
                    raw_event=raw,
                    quality_events=[
                        self._quality(
                            raw,
                            "PARTIAL_CHANGED_SIDE",
                            QualityStatus.BAD,
                            "partial contains exactly one of bid or ask",
                        )
                    ],
                )
            if previous is None:
                return AdapterOutput(
                    raw_event=raw,
                    quality_events=[
                        self._quality(
                            raw,
                            "PARTIAL_NO_SAFE_STATE",
                            QualityStatus.BAD,
                            "fresh same-session quote state exists",
                        )
                    ],
                )
            if envelope.received_at - previous.updated_at > self.partial_state_max_age:
                return AdapterOutput(
                    raw_event=raw,
                    quality_events=[
                        self._quality(
                            raw,
                            "PARTIAL_STALE_STATE",
                            QualityStatus.STALE,
                            f"state age <= {self.partial_state_max_age.total_seconds()}s",
                        )
                    ],
                )
            if bid is not None:
                ask = previous.ask
                changed_fields = ["bid"]
            else:
                bid = previous.bid
                changed_fields = ["ask"]
            is_snapshot = False
        else:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "SEMANTICS_UNKNOWN",
                        QualityStatus.UNPARSEABLE,
                        "discovery bridge marks snapshot or partial",
                    )
                ],
            )

        assert bid is not None and ask is not None
        if bid <= 0 or ask <= 0:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw, "NUM_PRICE_POSITIVE", QualityStatus.BAD, "bid > 0 and ask > 0"
                    )
                ],
            )
        if bid < minimum or ask > maximum:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "NUM_PRICE_BROAD_RANGE",
                        QualityStatus.BAD,
                        f"{minimum} <= bid <= ask <= {maximum}",
                        observed=f"{bid}/{ask}",
                    )
                ],
            )
        if ask < bid:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(raw, "NUM_CROSSED_QUOTE", QualityStatus.BAD, "ask >= bid")
                ],
            )

        event_order_time = provider_time or browser_observed_at
        dedup = canonical_hash(
            {
                "provider": "IC_MARKETS",
                "connection_id": envelope.connection_id,
                "session_id": envelope.session_id,
                "instrument": instrument,
                "event_order_time": event_order_time.isoformat(),
                "timestamp_basis": "provider"
                if provider_time is not None
                else "browser_observation",
                "bid": str(bid),
                "ask": str(ask),
                "sequence": sequence,
            }
        )
        if dedup in self._seen:
            self._seen.move_to_end(dedup)
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "DUP_STRONG_KEY",
                        QualityStatus.DUPLICATE,
                        "unseen deterministic provider identity",
                        action="duplicate_tick_suppressed",
                        severity="INFO",
                    )
                ],
            )

        flags: list[str] = []
        status = QualityStatus.GOOD
        qualities: list[DataQualityEvent] = []
        if provider_time is None:
            flags.append("PROVIDER_TIMESTAMP_UNAVAILABLE")
            status = QualityStatus.WARNING
            qualities.append(
                self._quality(
                    raw,
                    "TIME_PROVIDER_UNAVAILABLE",
                    QualityStatus.WARNING,
                    "provider timestamp present; browser observation time used for ordering",
                    action="tick_published_with_warning",
                    severity="WARNING",
                )
            )
        if previous is not None:
            if (
                sequence is not None
                and previous.sequence is not None
                and sequence <= previous.sequence
            ):
                classification = (
                    QualityStatus.DUPLICATE
                    if sequence == previous.sequence
                    else QualityStatus.OUT_OF_ORDER
                )
                rule = "SEQ_REPEATED" if sequence == previous.sequence else "SEQ_OUT_OF_ORDER"
                return AdapterOutput(
                    raw_event=raw,
                    quality_events=[
                        self._quality(
                            raw,
                            rule,
                            classification,
                            (
                                "strictly increasing observation_sequence within "
                                "document_session_id + instrument"
                                if is_visible_dom
                                else "strictly increasing provider sequence"
                            ),
                            action="tick_suppressed",
                            severity=self.non_increasing_observation_sequence_severity,
                        )
                    ],
                )
            if event_order_time < previous.order_time:
                if is_visible_dom and sequence is not None:
                    flags.append("LOCAL_WALL_CLOCK_ADJUSTMENT")
                    status = QualityStatus.WARNING
                    qualities.append(
                        self._quality(
                            raw,
                            "TIME_LOCAL_WALL_CLOCK_ADJUSTMENT",
                            QualityStatus.WARNING,
                            "browser observation time is non-decreasing",
                            action=(
                                "tick_suppressed"
                                if self.reject_local_wall_clock_adjustment
                                else "tick_published_with_warning"
                            ),
                            observed=event_order_time.isoformat(),
                            severity="WARNING",
                        )
                    )
                    if self.reject_local_wall_clock_adjustment:
                        return AdapterOutput(raw_event=raw, quality_events=qualities)
                else:
                    return AdapterOutput(
                        raw_event=raw,
                        quality_events=[
                            self._quality(
                                raw,
                                "TIME_OUT_OF_ORDER",
                                QualityStatus.OUT_OF_ORDER,
                                "non-decreasing provider timestamp",
                                action="tick_suppressed",
                            )
                        ],
                    )
            jump_pips = abs(((bid + ask) / 2) - ((previous.bid + previous.ask) / 2)) / pip_size
            if jump_pips > jump_limit:
                flags.append("EXTREME_SINGLE_TICK_JUMP")
                status = QualityStatus.WARNING
                qualities.append(
                    self._quality(
                        raw,
                        "PLAUS_EXTREME_JUMP",
                        QualityStatus.WARNING,
                        f"jump <= {jump_limit} pips",
                        action="tick_published_with_warning",
                        observed=str(jump_pips),
                        severity="WARNING",
                    )
                )
        spread_pips = (ask - bid) / pip_size
        if spread_pips > spread_limit:
            flags.append("EXTREME_SPREAD")
            status = QualityStatus.WARNING
            qualities.append(
                self._quality(
                    raw,
                    "PLAUS_EXTREME_SPREAD",
                    QualityStatus.WARNING,
                    f"spread <= {spread_limit} pips",
                    action="tick_published_with_warning",
                    observed=str(spread_pips),
                    severity="WARNING",
                )
            )

        browser_delay_ms = (collector_received_at - browser_observed_at).total_seconds() * 1000
        if is_visible_dom and browser_delay_ms < 0:
            flags.append("NEGATIVE_BROWSER_TO_COLLECTOR_DELAY")
            status = QualityStatus.WARNING
            qualities.append(
                self._quality(
                    raw,
                    "TIME_NEGATIVE_BROWSER_TO_COLLECTOR_DELAY",
                    QualityStatus.WARNING,
                    "browser_to_collector_delay_ms >= 0",
                    action=(
                        "tick_suppressed"
                        if self.reject_negative_browser_to_collector_delay
                        else "tick_published_with_warning"
                    ),
                    observed=str(browser_delay_ms),
                    severity="WARNING",
                )
            )
            if self.reject_negative_browser_to_collector_delay:
                return AdapterOutput(raw_event=raw, quality_events=qualities)
        if is_visible_dom and browser_delay_ms > (
            self.max_browser_to_collector_delay.total_seconds() * 1000
        ):
            flags.append("EXCESSIVE_BROWSER_TO_COLLECTOR_DELAY")
            status = QualityStatus.WARNING
            qualities.append(
                self._quality(
                    raw,
                    "TIME_EXCESSIVE_BROWSER_TO_COLLECTOR_DELAY",
                    QualityStatus.WARNING,
                    (
                        "browser_to_collector_delay_ms <= "
                        f"{self.max_browser_to_collector_delay.total_seconds() * 1000}"
                    ),
                    action=(
                        "tick_suppressed"
                        if self.reject_excessive_browser_to_collector_delay
                        else "tick_published_with_warning"
                    ),
                    observed=str(browser_delay_ms),
                    severity="WARNING",
                )
            )
            if self.reject_excessive_browser_to_collector_delay:
                return AdapterOutput(raw_event=raw, quality_events=qualities)

        normalized_at = utc_now()
        collector_processing_delay_ms = (
            normalized_at - collector_received_at
        ).total_seconds() * 1000
        total_local_pipeline_delay_ms = (normalized_at - browser_observed_at).total_seconds() * 1000
        tick = PriceTick.from_quote(
            adapter_instance_id=self.instance_id,
            instrument=instrument,
            source="VISIBLE_DOM" if is_visible_dom else "WEB_TERMINAL",
            observation_level="DISPLAY_QUOTE" if is_visible_dom else "PROVIDER_TICK",
            is_provider_tick=not is_visible_dom,
            bid=bid,
            ask=ask,
            is_snapshot=is_snapshot,
            changed_fields=changed_fields,
            provider_event_time=None if is_visible_dom else provider_time,
            received_at=browser_observed_at if is_visible_dom else envelope.received_at,
            normalized_at=normalized_at,
            sequence=None if is_visible_dom else sequence,
            browser_observed_at=browser_observed_at if is_visible_dom else None,
            collector_received_at=collector_received_at if is_visible_dom else None,
            document_session_id=envelope.document_session_id if is_visible_dom else None,
            observation_sequence=sequence if is_visible_dom else None,
            browser_to_collector_delay_ms=browser_delay_ms if is_visible_dom else None,
            collector_processing_delay_ms=(
                collector_processing_delay_ms if is_visible_dom else None
            ),
            total_local_pipeline_delay_ms=(
                total_local_pipeline_delay_ms if is_visible_dom else None
            ),
            raw_event_id=raw.event_id,
            raw_payload_hash=raw.content_hash,
            quality_status=status,
            quality_flags=flags,
            trace_id=raw.trace_id,
        )
        self._seen[dedup] = (collector_received_at, key)
        self._seen.move_to_end(dedup)
        self._purge_seen(collector_received_at)
        self._state[key] = QuoteState(
            bid,
            ask,
            envelope.received_at,
            event_order_time,
            sequence,
        )
        return AdapterOutput(raw_event=raw, tick=tick, quality_events=qualities)
