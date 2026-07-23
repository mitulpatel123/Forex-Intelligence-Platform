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
