from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from forex_contracts import (
    INSTRUMENT_SPECS,
    SUPPORTED_INSTRUMENTS,
    PriceTickV01,
    PriceTickV02,
    instrument_spec,
    parse_price_tick,
)
from pydantic import ValidationError

from scripts.generate_contracts import render_python, render_typescript

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "packages/contracts/instrument_specs.json"
PYTHON_GENERATED = ROOT / "packages/contracts/src/forex_contracts/instruments_generated.py"
TYPESCRIPT_GENERATED = ROOT / "apps/browser_bridge/src/instruments.generated.ts"
V02_SCHEMA = ROOT / "docs/contracts/PRICE_TICK_v0.2.schema.json"

EXPECTED = {
    "EURUSD": ("EUR", "USD", Decimal("0.0001"), 4, 6, Decimal("0.5"), Decimal("2.5")),
    "GBPUSD": ("GBP", "USD", Decimal("0.0001"), 4, 6, Decimal("0.5"), Decimal("3.5")),
    "USDJPY": ("USD", "JPY", Decimal("0.01"), 2, 4, Decimal("50"), Decimal("250")),
    "AUDUSD": ("AUD", "USD", Decimal("0.0001"), 4, 6, Decimal("0.2"), Decimal("2.0")),
}


def common() -> dict[str, object]:
    now = datetime(2026, 7, 23, 18, 0, tzinfo=UTC)
    return {
        "adapter_instance_id": "test",
        "source": "VISIBLE_DOM",
        "observation_level": "DISPLAY_QUOTE",
        "is_provider_tick": False,
        "is_snapshot": True,
        "changed_fields": ["bid", "ask"],
        "provider_event_time": None,
        "received_at": now,
        "normalized_at": now,
        "raw_event_id": "raw",
        "raw_payload_hash": "sha256:test",
        "quality_status": "WARNING",
        "quality_flags": ["PROVIDER_TIMESTAMP_UNAVAILABLE"],
        "trace_id": "trace",
    }


def test_canonical_registry_has_exact_supported_pair_specs() -> None:
    canonical = json.loads(REGISTRY_PATH.read_text())
    assert tuple(canonical) == SUPPORTED_INSTRUMENTS
    assert set(canonical) == set(EXPECTED)
    for symbol, expected in EXPECTED.items():
        spec = instrument_spec(symbol)
        actual = (
            spec["base_currency"],
            spec["quote_currency"],
            spec["pip_size"],
            spec["display_decimal_min"],
            spec["display_decimal_max"],
            spec["broad_min_price"],
            spec["broad_max_price"],
        )
        assert actual == expected
        assert INSTRUMENT_SPECS[symbol] == spec


def test_generation_is_deterministic_and_checked_in_artifacts_are_current() -> None:
    canonical = json.loads(REGISTRY_PATH.read_text())
    assert render_python(canonical) == render_python(canonical)
    assert render_typescript(canonical) == render_typescript(canonical)
    assert PYTHON_GENERATED.read_text() == render_python(canonical)
    assert TYPESCRIPT_GENERATED.read_text() == render_typescript(canonical)
    for symbol, values in canonical.items():
        assert f'"{symbol}"' in TYPESCRIPT_GENERATED.read_text()
        assert str(values["pip_size"]) in TYPESCRIPT_GENERATED.read_text()
        assert str(values["base_currency"]) in TYPESCRIPT_GENERATED.read_text()
        assert str(values["quote_currency"]) in TYPESCRIPT_GENERATED.read_text()


@pytest.mark.parametrize(
    ("instrument", "bid", "ask", "mid", "spread_pips"),
    [
        ("EURUSD", "1.13743", "1.13744", "1.137435", "0.1"),
        ("GBPUSD", "1.33155", "1.33157", "1.33156", "0.2"),
        ("USDJPY", "163.832", "163.833", "163.8325", "0.1"),
        ("AUDUSD", "0.69689", "0.69690", "0.696895", "0.1"),
    ],
)
def test_v02_pair_math_and_serialization(
    instrument: str,
    bid: str,
    ask: str,
    mid: str,
    spread_pips: str,
) -> None:
    spec = instrument_spec(instrument)
    tick = PriceTickV02.from_quote(
        instrument=instrument,  # type: ignore[arg-type]
        bid=Decimal(bid),
        ask=Decimal(ask),
        **common(),
    )
    assert tick.base_currency == spec["base_currency"]
    assert tick.quote_currency == spec["quote_currency"]
    assert tick.pip_size == spec["pip_size"]
    assert tick.mid == Decimal(mid)
    assert tick.spread == Decimal(ask) - Decimal(bid)
    assert tick.spread_pips == Decimal(spread_pips)
    payload = json.loads(tick.model_dump_json())
    assert payload["schema_version"] == "0.2"
    assert isinstance(parse_price_tick(payload), PriceTickV02)


def test_usdjpy_never_uses_non_jpy_pip_size() -> None:
    tick = PriceTickV02.from_quote(
        instrument="USDJPY",
        bid=Decimal("163.83"),
        ask=Decimal("163.84"),
        **common(),
    )
    assert tick.pip_size == Decimal("0.01")
    assert tick.pip_size != Decimal("0.0001")
    with pytest.raises(ValidationError):
        PriceTickV02.model_validate({**tick.model_dump(), "pip_size": Decimal("0.0001")})


def test_zero_spread_is_valid_for_each_pair() -> None:
    values = {
        "EURUSD": Decimal("1.1"),
        "GBPUSD": Decimal("1.3"),
        "USDJPY": Decimal("160"),
        "AUDUSD": Decimal("0.7"),
    }
    for instrument, price in values.items():
        tick = PriceTickV02.from_quote(
            instrument=instrument,  # type: ignore[arg-type]
            bid=price,
            ask=price,
            **common(),
        )
        assert tick.spread == 0
        assert tick.spread_pips == 0


@pytest.mark.parametrize(("bid", "ask"), [("-1", "1"), ("1", "-1"), ("2", "1")])
def test_v02_rejects_negative_or_crossed_values(bid: str, ask: str) -> None:
    with pytest.raises(ValidationError):
        PriceTickV02.from_quote(
            instrument="EURUSD",
            bid=Decimal(bid),
            ask=Decimal(ask),
            **common(),
        )


def test_v01_eurusd_contract_remains_parseable_and_frozen() -> None:
    tick = PriceTickV01.from_quote(
        bid=Decimal("1.13743"),
        ask=Decimal("1.13744"),
        **common(),
    )
    payload = json.loads(tick.model_dump_json())
    assert payload["schema_version"] == "0.1"
    assert "base_currency" not in payload
    parsed = parse_price_tick(payload)
    assert isinstance(parsed, PriceTickV01)
    assert parsed.instrument == "EURUSD"
    assert parsed.pip_size == Decimal("0.0001")


def test_checked_in_v02_json_schema_is_current() -> None:
    assert json.loads(V02_SCHEMA.read_text()) == PriceTickV02.model_json_schema()
