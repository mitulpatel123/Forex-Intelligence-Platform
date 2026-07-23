from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal

from forex_contracts import DataQualityEvent, PriceTick, RawProviderEvent
from pydantic import BaseModel, ConfigDict, Field


class ProviderEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str | None = None
    connection_id: str
    session_id: str
    document_session_id: str | None = None
    observation_sequence: int | None = None
    browser_observed_at: datetime | None = None
    collector_received_at: datetime | None = None
    received_at: datetime
    payload: dict[str, Any] | str
    payload_content_type: str = "application/json"
    channel_metadata: dict[str, Any] = Field(default_factory=dict)
    semantics: Literal["snapshot", "partial", "unknown"] = "unknown"


class AdapterOutput(BaseModel):
    raw_event: RawProviderEvent
    tick: PriceTick | None = None
    quality_events: list[DataQualityEvent] = Field(default_factory=list)


class Adapter(ABC):
    @abstractmethod
    def process(self, envelope: ProviderEnvelope) -> AdapterOutput:
        """Persistable deterministic transformation of one provider envelope."""

    @abstractmethod
    def on_disconnect(self, connection_id: str, session_id: str) -> None:
        """Invalidate state that cannot safely cross a reconnect."""
