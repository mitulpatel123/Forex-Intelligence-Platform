from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from adapter_sdk import Adapter, AdapterOutput, ProviderEnvelope
from forex_contracts import DataQualityEvent, PriceTick, QualityStatus, RawProviderEvent
from forex_contracts.models import canonical_hash, utc_now

from ic_markets_adapter.redaction import redact

MAX_PAYLOAD_BYTES = 256 * 1024


@dataclass
class QuoteState:
    bid: Decimal
    ask: Decimal
    updated_at: datetime
    provider_event_time: datetime
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
        extreme_spread_pips: Decimal = Decimal("5"),
        extreme_jump_pips: Decimal = Decimal("20"),
    ) -> None:
        self.instance_id = instance_id
        self.partial_state_max_age = partial_state_max_age
        self.max_future_skew = max_future_skew
        self.extreme_spread_pips = extreme_spread_pips
        self.extreme_jump_pips = extreme_jump_pips
        self._state: dict[tuple[str, str, str], QuoteState] = {}
        self._seen: set[str] = set()

    def on_disconnect(self, connection_id: str, session_id: str) -> None:
        for key in list(self._state):
            if key[0] == connection_id and key[1] == session_id:
                del self._state[key]

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
        sanitized, redactions = redact(envelope.payload)
        raw = RawProviderEvent(
            adapter_instance_id=self.instance_id,
            connection_id=envelope.connection_id,
            session_id=envelope.session_id,
            instrument=(str(sanitized.get("instrument")) if isinstance(sanitized, dict) else None),
            received_at=envelope.received_at,
            payload_content_type=envelope.payload_content_type,
            payload=sanitized,
            content_hash=canonical_hash(sanitized),
            channel_metadata=envelope.channel_metadata,
            redaction_status="SANITIZED" if redactions else "NOT_REQUIRED",
            redactions=redactions,
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
        if instrument != "EURUSD":
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "STRUCT_INSTRUMENT",
                        QualityStatus.BAD,
                        "instrument == EURUSD",
                        observed=str(instrument),
                    )
                ],
            )

        provider_time = self._parse_time(sanitized.get("provider_event_time"))
        if provider_time is None:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(
                        raw,
                        "TIME_PARSE_UTC",
                        QualityStatus.UNPARSEABLE,
                        "timezone-aware provider_event_time",
                        observed=str(sanitized.get("provider_event_time")),
                    )
                ],
            )
        raw.provider_event_time = provider_time
        if provider_time > envelope.received_at + self.max_future_skew:
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
        sequence = sequence_value if isinstance(sequence_value, int) else None
        bid = self._parse_decimal(sanitized.get("bid"))
        ask = self._parse_decimal(sanitized.get("ask"))
        key = (envelope.connection_id, envelope.session_id, "EURUSD")
        previous = self._state.get(key)
        changed_fields: list[str] = []

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
        if ask < bid:
            return AdapterOutput(
                raw_event=raw,
                quality_events=[
                    self._quality(raw, "NUM_CROSSED_QUOTE", QualityStatus.BAD, "ask >= bid")
                ],
            )

        dedup = canonical_hash(
            {
                "provider": "IC_MARKETS",
                "connection_id": envelope.connection_id,
                "session_id": envelope.session_id,
                "instrument": "EURUSD",
                "provider_event_time": provider_time.isoformat(),
                "bid": str(bid),
                "ask": str(ask),
                "sequence": sequence,
            }
        )
        if dedup in self._seen:
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
                            "strictly increasing provider sequence",
                            action="tick_suppressed",
                        )
                    ],
                )
            if provider_time < previous.provider_event_time:
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
            jump_pips = abs(((bid + ask) / 2) - ((previous.bid + previous.ask) / 2)) / Decimal(
                "0.0001"
            )
            if jump_pips > self.extreme_jump_pips:
                flags.append("EXTREME_SINGLE_TICK_JUMP")
                status = QualityStatus.WARNING
                qualities.append(
                    self._quality(
                        raw,
                        "PLAUS_EXTREME_JUMP",
                        QualityStatus.WARNING,
                        f"jump <= {self.extreme_jump_pips} pips",
                        action="tick_published_with_warning",
                        observed=str(jump_pips),
                        severity="WARNING",
                    )
                )
        spread_pips = (ask - bid) / Decimal("0.0001")
        if spread_pips > self.extreme_spread_pips:
            flags.append("EXTREME_SPREAD")
            status = QualityStatus.WARNING
            qualities.append(
                self._quality(
                    raw,
                    "PLAUS_EXTREME_SPREAD",
                    QualityStatus.WARNING,
                    f"spread <= {self.extreme_spread_pips} pips",
                    action="tick_published_with_warning",
                    observed=str(spread_pips),
                    severity="WARNING",
                )
            )

        normalized_at = utc_now()
        tick = PriceTick.from_quote(
            adapter_instance_id=self.instance_id,
            bid=bid,
            ask=ask,
            is_snapshot=is_snapshot,
            changed_fields=changed_fields,
            provider_event_time=provider_time,
            received_at=envelope.received_at,
            normalized_at=normalized_at,
            sequence=sequence,
            raw_event_id=raw.event_id,
            raw_payload_hash=raw.content_hash,
            quality_status=status,
            quality_flags=flags,
            trace_id=raw.trace_id,
        )
        self._seen.add(dedup)
        self._state[key] = QuoteState(bid, ask, envelope.received_at, provider_time, sequence)
        return AdapterOutput(raw_event=raw, tick=tick, quality_events=qualities)
