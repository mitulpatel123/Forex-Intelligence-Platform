from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from adapter_sdk import ProviderEnvelope
from forex_contracts import PriceTick, QualityStatus
from forex_contracts.models import canonical_hash
from ic_markets_adapter import IcMarketsAdapter
from ic_markets_adapter.redaction import redact
from pydantic import ValidationError

BASE = datetime(2026, 7, 23, 14, 30, 1, tzinfo=UTC)


def envelope(
    *,
    instrument: str = "EURUSD",
    semantics: str = "snapshot",
    bid: object = "1.08542",
    ask: object = "1.08544",
    sequence: int = 1,
    provider_time: datetime | None = BASE,
    received_at: datetime = BASE + timedelta(milliseconds=4),
    connection: str = "c1",
    session: str = "s1",
) -> ProviderEnvelope:
    payload = {
        "instrument": instrument,
        "provider_event_time": (
            provider_time.isoformat().replace("+00:00", "Z") if provider_time is not None else None
        ),
        "sequence": sequence,
    }
    if bid is not None:
        payload["bid"] = bid
    if ask is not None:
        payload["ask"] = ask
    return ProviderEnvelope(
        connection_id=connection,
        session_id=session,
        received_at=received_at,
        semantics=semantics,  # type: ignore[arg-type]
        payload=payload,
    )


def visible_envelope(
    *,
    instrument: str = "EURUSD",
    sequence: int | None = 1,
    browser_observed_at: datetime = BASE,
    collector_received_at: datetime = BASE + timedelta(milliseconds=4),
    session: str = "document-one",
    bid: str = "1.08542",
    ask: str = "1.08544",
    provider_claim: str | None = None,
) -> ProviderEnvelope:
    return ProviderEnvelope(
        connection_id="browser-one",
        session_id=session,
        document_session_id=session,
        observation_sequence=sequence,
        browser_observed_at=browser_observed_at,
        collector_received_at=collector_received_at,
        received_at=browser_observed_at,
        semantics="snapshot",
        payload={
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "provider_event_time": provider_claim,
            "sequence": 999,
            "observation_source": "visible_dom",
        },
        channel_metadata={"observation_level": "DISPLAY_QUOTE"},
    )


def rule(output: object) -> str:
    return output.quality_events[0].rule_id  # type: ignore[attr-defined,no-any-return]


def test_complete_snapshot_and_decimal_math() -> None:
    output = IcMarketsAdapter().process(envelope())
    assert output.tick is not None
    assert output.tick.mid == Decimal("1.08543")
    assert output.tick.spread == Decimal("0.00002")
    assert output.tick.spread_pips == Decimal("0.2")
    assert output.tick.pip_size == Decimal("0.0001")
    assert output.tick.changed_fields == ["bid", "ask"]


@pytest.mark.parametrize(
    ("instrument", "bid", "ask", "base", "quote", "pip", "spread_pips"),
    [
        ("EURUSD", "1.13743", "1.13744", "EUR", "USD", "0.0001", "0.1"),
        ("GBPUSD", "1.33155", "1.33157", "GBP", "USD", "0.0001", "0.2"),
        ("USDJPY", "163.832", "163.833", "USD", "JPY", "0.01", "0.1"),
        ("AUDUSD", "0.69689", "0.69690", "AUD", "USD", "0.0001", "0.1"),
    ],
)
def test_all_supported_pairs_use_registry_math(
    instrument: str,
    bid: str,
    ask: str,
    base: str,
    quote: str,
    pip: str,
    spread_pips: str,
) -> None:
    output = IcMarketsAdapter().process(envelope(instrument=instrument, bid=bid, ask=ask))
    assert output.tick is not None
    assert output.tick.instrument == instrument
    assert output.tick.base_currency == base
    assert output.tick.quote_currency == quote
    assert output.tick.pip_size == Decimal(pip)
    assert output.tick.spread_pips == Decimal(spread_pips)
    assert output.tick.schema_version == "0.2"


def test_state_and_dedup_are_independent_per_pair() -> None:
    adapter = IcMarketsAdapter()
    eur = adapter.process(envelope(instrument="EURUSD", bid="1.1", ask="1.1001"))
    aud = adapter.process(envelope(instrument="AUDUSD", bid="0.7", ask="0.7001"))
    assert eur.tick is not None
    assert aud.tick is not None
    duplicate = adapter.process(envelope(instrument="EURUSD", bid="1.1", ask="1.1001"))
    assert duplicate.tick is None
    assert rule(duplicate) == "DUP_STRONG_KEY"

    aud_partial = adapter.process(
        envelope(
            instrument="AUDUSD",
            semantics="partial",
            bid="0.70005",
            ask=None,
            sequence=2,
            provider_time=BASE + timedelta(milliseconds=1),
            received_at=BASE + timedelta(milliseconds=5),
        )
    )
    assert aud_partial.tick is not None
    assert aud_partial.tick.ask == Decimal("0.7001")


def test_disconnect_invalidates_every_pair_only_in_that_session() -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope(instrument="EURUSD"))
    adapter.process(envelope(instrument="AUDUSD", bid="0.7", ask="0.7001"))
    adapter.process(
        envelope(
            instrument="GBPUSD",
            bid="1.3",
            ask="1.3001",
            connection="other",
            session="other",
        )
    )
    adapter.on_disconnect("c1", "s1")
    invalidated = adapter.process(
        envelope(
            instrument="AUDUSD",
            semantics="partial",
            ask=None,
            bid="0.70005",
            sequence=2,
            provider_time=BASE + timedelta(milliseconds=1),
            received_at=BASE + timedelta(milliseconds=5),
        )
    )
    retained = adapter.process(
        envelope(
            instrument="GBPUSD",
            semantics="partial",
            ask=None,
            bid="1.30005",
            sequence=2,
            provider_time=BASE + timedelta(milliseconds=1),
            received_at=BASE + timedelta(milliseconds=5),
            connection="other",
            session="other",
        )
    )
    assert rule(invalidated) == "PARTIAL_NO_SAFE_STATE"
    assert retained.tick is not None


@pytest.mark.parametrize(
    ("instrument", "bid", "ask"),
    [
        ("EURUSD", "1.1", "1.101"),
        ("GBPUSD", "1.3", "1.301"),
        ("USDJPY", "160", "160.1"),
        ("AUDUSD", "0.7", "0.701"),
    ],
)
def test_pair_specific_extreme_spread_warning(instrument: str, bid: str, ask: str) -> None:
    output = IcMarketsAdapter().process(envelope(instrument=instrument, bid=bid, ask=ask))
    assert output.tick is not None
    assert "EXTREME_SPREAD" in output.tick.quality_flags


@pytest.mark.parametrize(
    ("bid", "ask", "expected"),
    [(None, "1.0", "SNAPSHOT_MISSING_BID"), ("1.0", None, "SNAPSHOT_MISSING_ASK")],
)
def test_snapshot_missing_side(bid: object, ask: object, expected: str) -> None:
    assert rule(IcMarketsAdapter().process(envelope(bid=bid, ask=ask))) == expected


@pytest.mark.parametrize(
    ("bid", "ask", "changed"),
    [("1.08543", None, ["bid"]), (None, "1.08545", ["ask"])],
)
def test_partial_updates(bid: object, ask: object, changed: list[str]) -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope())
    output = adapter.process(
        envelope(
            semantics="partial",
            bid=bid,
            ask=ask,
            sequence=2,
            provider_time=BASE + timedelta(milliseconds=10),
            received_at=BASE + timedelta(milliseconds=14),
        )
    )
    assert output.tick is not None
    assert output.tick.is_snapshot is False
    assert output.tick.changed_fields == changed


def test_partial_without_state() -> None:
    output = IcMarketsAdapter().process(envelope(semantics="partial", ask=None))
    assert rule(output) == "PARTIAL_NO_SAFE_STATE"


def test_stale_partial_state() -> None:
    adapter = IcMarketsAdapter(partial_state_max_age=timedelta(seconds=1))
    adapter.process(envelope())
    output = adapter.process(
        envelope(
            semantics="partial",
            ask=None,
            sequence=2,
            provider_time=BASE + timedelta(seconds=2),
            received_at=BASE + timedelta(seconds=2),
        )
    )
    assert rule(output) == "PARTIAL_STALE_STATE"


def test_disconnect_invalidates_state() -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope())
    adapter.on_disconnect("c1", "s1")
    output = adapter.process(
        envelope(
            semantics="partial",
            ask=None,
            sequence=2,
            provider_time=BASE + timedelta(milliseconds=10),
            received_at=BASE + timedelta(milliseconds=14),
        )
    )
    assert rule(output) == "PARTIAL_NO_SAFE_STATE"


@pytest.mark.parametrize("bid", ["0", "-1", "NaN", "Infinity"])
def test_invalid_prices(bid: str) -> None:
    output = IcMarketsAdapter().process(envelope(bid=bid))
    assert output.tick is None


def test_crossed_quote() -> None:
    assert rule(IcMarketsAdapter().process(envelope(bid="1.1", ask="1.0"))) == ("NUM_CROSSED_QUOTE")


def test_malformed_timestamp() -> None:
    bad = envelope().model_copy(
        update={"payload": {**envelope().payload, "provider_event_time": "not-time"}}
    )
    assert rule(IcMarketsAdapter().process(bad)) == "TIME_PARSE_UTC"


def test_future_clock_skew() -> None:
    output = IcMarketsAdapter().process(
        envelope(provider_time=BASE + timedelta(seconds=3), received_at=BASE)
    )
    assert rule(output) == "TIME_FUTURE_SKEW"


def test_visible_dom_quote_without_provider_timestamp_is_published_with_warning() -> None:
    observed = visible_envelope()
    output = IcMarketsAdapter().process(observed)
    assert output.tick is not None
    assert output.tick.provider_event_time is None
    assert output.tick.source == "VISIBLE_DOM"
    assert output.tick.observation_level == "DISPLAY_QUOTE"
    assert output.tick.is_provider_tick is False
    assert output.tick.quality_status == QualityStatus.WARNING
    assert "PROVIDER_TIMESTAMP_UNAVAILABLE" in output.tick.quality_flags
    assert rule(output) == "TIME_PROVIDER_UNAVAILABLE"
    assert output.tick.received_at == output.tick.browser_observed_at == BASE
    assert output.tick.collector_received_at == BASE + timedelta(milliseconds=4)
    assert output.tick.observation_sequence == 1
    assert output.tick.sequence is None
    assert output.tick.browser_to_collector_delay_ms == 4


def test_visible_dom_equal_timestamps_are_valid() -> None:
    output = IcMarketsAdapter().process(visible_envelope(collector_received_at=BASE))
    assert output.tick is not None
    assert output.tick.browser_to_collector_delay_ms == 0


def test_negative_browser_delay_is_flagged_without_inventing_provider_time() -> None:
    output = IcMarketsAdapter().process(
        visible_envelope(collector_received_at=BASE - timedelta(milliseconds=5))
    )
    assert output.tick is not None
    assert output.tick.provider_event_time is None
    assert "NEGATIVE_BROWSER_TO_COLLECTOR_DELAY" in output.tick.quality_flags


def test_delayed_outbox_delivery_is_measured_and_flagged() -> None:
    output = IcMarketsAdapter(max_browser_to_collector_delay=timedelta(seconds=1)).process(
        visible_envelope(collector_received_at=BASE + timedelta(seconds=10))
    )
    assert output.tick is not None
    assert output.tick.browser_to_collector_delay_ms == 10_000
    assert "EXCESSIVE_BROWSER_TO_COLLECTOR_DELAY" in output.tick.quality_flags


def test_local_clock_adjustment_uses_sequence_and_publishes_warning() -> None:
    adapter = IcMarketsAdapter()
    assert adapter.process(visible_envelope()).tick is not None
    output = adapter.process(
        visible_envelope(
            sequence=2,
            browser_observed_at=BASE - timedelta(milliseconds=1),
            collector_received_at=BASE + timedelta(milliseconds=5),
            bid="1.08543",
            ask="1.08545",
        )
    )
    assert output.tick is not None
    assert "LOCAL_WALL_CLOCK_ADJUSTMENT" in output.tick.quality_flags


def test_visible_dom_sequence_is_required_and_strict_per_document_and_pair() -> None:
    adapter = IcMarketsAdapter()
    assert rule(adapter.process(visible_envelope(sequence=None))) == "SEQ_OBSERVATION_MISSING"
    for instrument in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD"):
        bid, ask = {
            "EURUSD": ("1.1", "1.1001"),
            "GBPUSD": ("1.3", "1.3001"),
            "USDJPY": ("160", "160.01"),
            "AUDUSD": ("0.7", "0.7001"),
        }[instrument]
        assert (
            adapter.process(visible_envelope(instrument=instrument, bid=bid, ask=ask)).tick
            is not None
        )
    repeated = adapter.process(visible_envelope())
    assert rule(repeated) in {"DUP_STRONG_KEY", "SEQ_REPEATED"}
    reloaded = adapter.process(visible_envelope(session="document-two"))
    assert reloaded.tick is not None


def test_collector_restart_does_not_make_browser_sequence_provider_sequence() -> None:
    output = IcMarketsAdapter().process(visible_envelope(sequence=42))
    assert output.tick is not None
    assert output.tick.observation_sequence == 42
    assert output.tick.sequence is None
    after_restart = visible_envelope(sequence=42).model_copy(
        update={
            "channel_metadata": {
                "observation_level": "DISPLAY_QUOTE",
                "persisted_last_observation_sequence": 42,
            }
        }
    )
    suppressed = IcMarketsAdapter().process(after_restart)
    assert suppressed.tick is None
    assert rule(suppressed) == "SEQ_REPEATED"


def test_malicious_provider_timestamp_claim_is_discarded_for_visible_dom() -> None:
    output = IcMarketsAdapter().process(visible_envelope(provider_claim="2099-01-01T00:00:00Z"))
    assert output.tick is not None
    assert output.tick.provider_event_time is None
    assert output.raw_event.provider_event_time is None


def test_dedup_cache_is_bounded_and_disconnect_clears_session_entries() -> None:
    adapter = IcMarketsAdapter(dedup_cache_max_entries=2)
    for index in range(1, 4):
        adapter.process(
            visible_envelope(
                sequence=index,
                browser_observed_at=BASE + timedelta(milliseconds=index),
                collector_received_at=BASE + timedelta(milliseconds=index + 1),
                bid=f"1.0854{index}",
                ask=f"1.0855{index}",
            )
        )
    assert adapter.dedup_cache_size <= 2
    adapter.on_disconnect("browser-one", "document-one")
    assert adapter.dedup_cache_size == 0


def test_duplicate_policy_and_hash_determinism() -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope())
    output = adapter.process(envelope())
    assert output.quality_events[0].classification == QualityStatus.DUPLICATE
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_out_of_order_timestamp() -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope())
    output = adapter.process(
        envelope(
            sequence=2,
            provider_time=BASE - timedelta(milliseconds=1),
            received_at=BASE + timedelta(milliseconds=5),
        )
    )
    assert rule(output) == "TIME_OUT_OF_ORDER"


@pytest.mark.parametrize(("sequence", "expected"), [(1, "SEQ_REPEATED"), (0, "SEQ_OUT_OF_ORDER")])
def test_non_increasing_sequence(sequence: int, expected: str) -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope())
    output = adapter.process(
        envelope(
            sequence=sequence,
            provider_time=BASE + timedelta(milliseconds=1),
            received_at=BASE + timedelta(milliseconds=5),
        )
    )
    assert rule(output) == expected


def test_extreme_jump_and_spread_warning() -> None:
    adapter = IcMarketsAdapter()
    adapter.process(envelope())
    jump = adapter.process(
        envelope(
            bid="1.10",
            ask="1.10002",
            sequence=2,
            provider_time=BASE + timedelta(milliseconds=1),
            received_at=BASE + timedelta(milliseconds=5),
        )
    )
    assert jump.tick is not None
    assert "EXTREME_SINGLE_TICK_JUMP" in jump.tick.quality_flags
    spread = IcMarketsAdapter().process(envelope(bid="1.08", ask="1.081"))
    assert spread.tick is not None
    assert "EXTREME_SPREAD" in spread.tick.quality_flags


def test_redaction_is_recursive() -> None:
    value, paths = redact(
        {"authorization": "Bearer abc", "nested": {"url": "wss://x?token=secret&ok=1"}}
    )
    assert value["authorization"] == "[REDACTED]"
    assert "secret" not in value["nested"]["url"]
    assert paths


def test_redaction_sanitizes_json_encoded_discovery_payloads() -> None:
    value, paths = redact(
        {
            "payload": (
                '{"account":123456,"login":"user","sessionId":"session-secret",'
                '"accessToken":"token-secret","bid":"1.13743"}'
            )
        }
    )
    assert "123456" not in value["payload"]
    assert "session-secret" not in value["payload"]
    assert "token-secret" not in value["payload"]
    assert "1.13743" in value["payload"]
    assert paths


def test_source_event_id_becomes_idempotent_raw_event_id() -> None:
    output = IcMarketsAdapter().process(
        envelope().model_copy(update={"event_id": "browser-observation-event"})
    )
    assert output.raw_event.event_id == "browser-observation-event"


def test_contract_rejects_incorrect_derived_values_and_naive_time() -> None:
    output = IcMarketsAdapter().process(envelope())
    assert output.tick is not None
    with pytest.raises(ValidationError):
        PriceTick.model_validate(
            {
                **output.tick.model_dump(),
                "spread": Decimal("0.01"),
            }
        )
    with pytest.raises(ValidationError):
        PriceTick.model_validate(
            {
                **output.tick.model_dump(),
                "received_at": datetime(2026, 1, 1),
            }
        )
