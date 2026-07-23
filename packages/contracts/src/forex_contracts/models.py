from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from forex_contracts.instruments_generated import (
    SupportedInstrument,
    instrument_spec,
    is_supported_instrument,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_event_id() -> str:
    return str(uuid.uuid4())


def canonical_hash(value: str | bytes | dict[str, Any]) -> str:
    if isinstance(value, dict):
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    elif isinstance(value, str):
        payload = value.encode()
    else:
        payload = value
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class QualityStatus(StrEnum):
    GOOD = "GOOD"
    WARNING = "WARNING"
    BAD = "BAD"
    DUPLICATE = "DUPLICATE"
    LATE = "LATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    STALE = "STALE"
    UNPARSEABLE = "UNPARSEABLE"


class AssetClass(StrEnum):
    FX = "FX"


class AdapterState(StrEnum):
    INITIALIZING = "INITIALIZING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    BLOCKED_BY_PROVIDER_DISCOVERY = "BLOCKED_BY_PROVIDER_DISCOVERY"


class EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=new_event_id)
    schema_version: str
    event_type: str
    source: str = "WEB_TERMINAL"
    observation_level: Literal["DISPLAY_QUOTE", "PROVIDER_TICK"] = "PROVIDER_TICK"
    is_provider_tick: bool = True
    provider: Literal["IC_MARKETS"] = "IC_MARKETS"
    adapter_instance_id: str
    instrument: str
    asset_class: AssetClass = AssetClass.FX
    provider_event_time: datetime | None
    received_at: datetime
    normalized_at: datetime
    sequence: int | None = None
    raw_event_id: str
    raw_payload_hash: str
    quality_status: QualityStatus
    quality_flags: list[str] = Field(default_factory=list)
    trace_id: str

    @field_validator("provider_event_time", "received_at", "normalized_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware UTC")
        return value.astimezone(UTC) if value is not None else None


class PriceTickV01(EventBase):
    """Frozen Milestone 1 EURUSD contract."""

    schema_version: Literal["0.1"] = "0.1"
    event_type: Literal["PRICE_TICK"] = "PRICE_TICK"
    instrument: Literal["EURUSD"] = "EURUSD"
    bid: Decimal
    ask: Decimal
    mid: Decimal
    spread: Decimal
    spread_pips: Decimal
    pip_size: Decimal = Decimal("0.0001")
    quote_currency: Literal["USD"] = "USD"
    is_snapshot: bool
    changed_fields: list[Literal["bid", "ask"]]

    @model_validator(mode="after")
    def validate_quote_math(self) -> PriceTickV01:
        if not self.bid.is_finite() or not self.ask.is_finite():
            raise ValueError("prices must be finite")
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("prices must be positive")
        if self.pip_size != Decimal("0.0001"):
            raise ValueError("EURUSD pip_size must equal 0.0001")
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        expected_spread = self.ask - self.bid
        expected_mid = (self.bid + self.ask) / Decimal("2")
        if self.spread != expected_spread:
            raise ValueError("spread does not equal ask - bid")
        if self.mid != expected_mid:
            raise ValueError("mid does not equal (bid + ask) / 2")
        if self.spread_pips != expected_spread / self.pip_size:
            raise ValueError("spread_pips does not equal spread / pip_size")
        return self

    @classmethod
    def from_quote(cls, *, bid: Decimal, ask: Decimal, **kwargs: Any) -> PriceTickV01:
        spread = ask - bid
        pip_size = Decimal("0.0001")
        return cls(
            bid=bid,
            ask=ask,
            mid=(bid + ask) / Decimal("2"),
            spread=spread,
            spread_pips=spread / pip_size,
            pip_size=pip_size,
            **kwargs,
        )


class PriceTickV02(EventBase):
    """Milestone 2 registry-backed four-pair display quote."""

    schema_version: Literal["0.2"] = "0.2"
    event_type: Literal["PRICE_TICK"] = "PRICE_TICK"
    instrument: SupportedInstrument
    base_currency: str
    quote_currency: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    spread: Decimal
    spread_pips: Decimal
    pip_size: Decimal
    is_snapshot: bool
    changed_fields: list[Literal["bid", "ask"]]
    browser_observed_at: datetime | None = None
    collector_received_at: datetime | None = None
    document_session_id: str | None = None
    observation_sequence: int | None = Field(default=None, ge=1)
    browser_to_collector_delay_ms: float | None = None
    collector_processing_delay_ms: float | None = None
    total_local_pipeline_delay_ms: float | None = None

    @field_validator("browser_observed_at", "collector_received_at")
    @classmethod
    def local_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware UTC")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_quote_math(self) -> PriceTickV02:
        if not is_supported_instrument(self.instrument):
            raise ValueError("instrument must exist in the canonical registry")
        spec = instrument_spec(self.instrument)
        expected_pip = spec["pip_size"]
        if self.base_currency != spec["base_currency"]:
            raise ValueError("base_currency does not match instrument registry")
        if self.quote_currency != spec["quote_currency"]:
            raise ValueError("quote_currency does not match instrument registry")
        if self.pip_size != expected_pip:
            raise ValueError("pip_size does not match instrument registry")
        if not self.bid.is_finite() or not self.ask.is_finite():
            raise ValueError("prices must be finite")
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("prices must be positive")
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        expected_spread = self.ask - self.bid
        expected_mid = (self.bid + self.ask) / Decimal("2")
        if self.spread != expected_spread:
            raise ValueError("spread does not equal ask - bid")
        if self.mid != expected_mid:
            raise ValueError("mid does not equal (bid + ask) / 2")
        if self.spread_pips != expected_spread / self.pip_size:
            raise ValueError("spread_pips does not equal spread / pip_size")
        return self

    @classmethod
    def from_quote(
        cls,
        *,
        instrument: SupportedInstrument,
        bid: Decimal,
        ask: Decimal,
        **kwargs: Any,
    ) -> PriceTickV02:
        spec = instrument_spec(instrument)
        pip_size = spec["pip_size"]
        assert isinstance(pip_size, Decimal)
        spread = ask - bid
        return cls(
            instrument=instrument,
            base_currency=str(spec["base_currency"]),
            quote_currency=str(spec["quote_currency"]),
            bid=bid,
            ask=ask,
            mid=(bid + ask) / Decimal("2"),
            spread=spread,
            spread_pips=spread / pip_size,
            pip_size=pip_size,
            **kwargs,
        )


PriceTick = PriceTickV02
PriceTickCompatible = Annotated[
    PriceTickV01 | PriceTickV02,
    Field(discriminator="schema_version"),
]
_PRICE_TICK_ADAPTER = TypeAdapter(PriceTickCompatible)


def parse_price_tick(value: dict[str, Any]) -> PriceTickV01 | PriceTickV02:
    return _PRICE_TICK_ADAPTER.validate_python(value)


class RawProviderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=new_event_id)
    schema_version: Literal["0.1"] = "0.1"
    event_type: Literal["RAW_PROVIDER_EVENT"] = "RAW_PROVIDER_EVENT"
    provider: Literal["IC_MARKETS"] = "IC_MARKETS"
    adapter_instance_id: str
    connection_id: str
    session_id: str
    instrument: str | None = None
    provider_event_time: datetime | None = None
    received_at: datetime
    browser_observed_at: datetime | None = None
    collector_received_at: datetime | None = None
    document_session_id: str | None = None
    observation_sequence: int | None = Field(default=None, ge=1)
    browser_to_collector_delay_ms: float | None = None
    payload_content_type: str
    payload: str | dict[str, Any]
    content_hash: str
    channel_metadata: dict[str, Any] = Field(default_factory=dict)
    redaction_status: Literal["SANITIZED", "NOT_REQUIRED"]
    redactions: list[str] = Field(default_factory=list)
    trace_id: str = Field(default_factory=new_event_id)

    @field_validator(
        "provider_event_time",
        "received_at",
        "browser_observed_at",
        "collector_received_at",
    )
    @classmethod
    def raw_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware UTC")
        return value.astimezone(UTC) if value is not None else None


class DataQualityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=new_event_id)
    schema_version: Literal["0.1"] = "0.1"
    event_type: Literal["DATA_QUALITY_EVENT"] = "DATA_QUALITY_EVENT"
    related_event_id: str
    provider: Literal["IC_MARKETS"] = "IC_MARKETS"
    instrument: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    rule_id: str
    classification: QualityStatus
    observed_value: str | None = None
    expected_condition: str
    action_taken: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)
    trace_id: str


class AdapterStatus(BaseModel):
    event_id: str = Field(default_factory=new_event_id)
    schema_version: Literal["0.1"] = "0.1"
    event_type: Literal["ADAPTER_STATUS"] = "ADAPTER_STATUS"
    adapter_name: Literal["ic_markets"] = "ic_markets"
    instance_id: str
    state: AdapterState
    connection_count: int = 0
    reconnect_count: int = 0
    last_message_time: datetime | None = None
    last_valid_tick_time: datetime | None = None
    error_code: str | None = None
    summary: str
    timestamp: datetime = Field(default_factory=utc_now)


class FeedHealth(BaseModel):
    event_id: str = Field(default_factory=new_event_id)
    schema_version: Literal["0.1"] = "0.1"
    event_type: Literal["FEED_HEALTH"] = "FEED_HEALTH"
    provider: Literal["IC_MARKETS"] = "IC_MARKETS"
    instrument: SupportedInstrument
    event_rate: float
    last_event_age: float
    invalid_ratio: float
    duplicate_ratio: float
    out_of_order_ratio: float
    p50_ingest_latency: float
    p95_ingest_latency: float
    p99_ingest_latency: float
    queue_lag: int
    storage_lag: int
    status: Literal["INITIALIZING", "HEALTHY", "STALE", "AMBIGUOUS", "MISSING", "DEGRADED"]
    timestamp: datetime = Field(default_factory=utc_now)
