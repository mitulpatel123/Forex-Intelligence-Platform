from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIP_", env_file=".env", extra="ignore")

    env: str = "development"
    bind_host: str = "127.0.0.1"
    health_port: int = 8001
    ingest_port: int = 8765
    redis_url: str = "redis://127.0.0.1:6380/0"
    database_url: str = "postgresql://forex:forex_local_only@127.0.0.1:55432/forex"
    bridge_token_file: str = ".local/bridge-token"  # noqa: S105
    queue_size: int = 10_000
    stale_after_seconds: float = 5.0
    bridge_stale_after_seconds: float = 6.0
    bridge_session_expiry_seconds: float = 60.0
    dedup_cache_max_entries: int = 100_000
    dedup_cache_ttl_seconds: float = 3_600.0
    max_browser_to_collector_delay_ms: float = 30_000.0
    reject_negative_browser_to_collector_delay: bool = False
    reject_excessive_browser_to_collector_delay: bool = False
    reject_local_wall_clock_adjustment: bool = False
    missing_observation_sequence_severity: Literal["WARNING", "ERROR"] = "ERROR"
    non_increasing_observation_sequence_severity: Literal["WARNING", "ERROR"] = "ERROR"
