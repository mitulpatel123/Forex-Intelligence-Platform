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
    observed = envelope().model_copy(
        update={
            "payload": {
                "instrument": "EURUSD",
                "bid": "1.08542",
                "ask": "1.08544",
                "provider_event_time": None,
                "observation_source": "visible_dom",
                # Provenance is derived from the trusted source classification,
                # not from these client-supplied qualifier claims.
                "observation_level": "PROVIDER_TICK",
                "is_provider_tick": True,
            }
        }
    )
    output = IcMarketsAdapter().process(observed)
    assert output.tick is not None
    assert output.tick.provider_event_time is None
    assert output.tick.source == "VISIBLE_DOM"
    assert output.tick.observation_level == "DISPLAY_QUOTE"
    assert output.tick.is_provider_tick is False
    assert output.tick.quality_status == QualityStatus.WARNING
    assert "PROVIDER_TIMESTAMP_UNAVAILABLE" in output.tick.quality_flags
    assert rule(output) == "TIME_PROVIDER_UNAVAILABLE"


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
