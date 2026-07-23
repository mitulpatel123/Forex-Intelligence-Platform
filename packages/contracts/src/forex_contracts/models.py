from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    schema_version: Literal["0.1"] = "0.1"
    event_type: str
    source: str = "WEB_TERMINAL"
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
        return value


class PriceTick(EventBase):
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
    def validate_quote_math(self) -> PriceTick:
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
    def from_quote(cls, *, bid: Decimal, ask: Decimal, **kwargs: Any) -> PriceTick:
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
    payload_content_type: str
    payload: str | dict[str, Any]
    content_hash: str
    channel_metadata: dict[str, Any] = Field(default_factory=dict)
    redaction_status: Literal["SANITIZED", "NOT_REQUIRED"]
    redactions: list[str] = Field(default_factory=list)
    trace_id: str = Field(default_factory=new_event_id)


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
    instrument: Literal["EURUSD"] = "EURUSD"
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
    status: Literal["HEALTHY", "DEGRADED", "STALE", "BLOCKED"]
    timestamp: datetime = Field(default_factory=utc_now)
