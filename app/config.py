from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices

class Settings(BaseSettings):
    # Load from .env and ignore unknown env keys (prevents ValidationError on extra env vars)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    router_name: str = "CogNeo Edge Router"
    router_version: str = "0.1.0"

    # Support both REQUEST_TIMEOUT and legacy ROUTER_REQUEST_TIMEOUT
    request_timeout: float = Field(
        30.0,
        validation_alias=AliasChoices("REQUEST_TIMEOUT", "ROUTER_REQUEST_TIMEOUT"),
    )
    # Support both UPSTREAM_TIMEOUT and legacy ROUTER_UPSTREAM_TIMEOUT
    upstream_timeout: float = Field(
        30.0,
        validation_alias=AliasChoices("UPSTREAM_TIMEOUT", "ROUTER_UPSTREAM_TIMEOUT"),
    )

    tenants_config: str = Field(
        "tenants.yaml",
        validation_alias=AliasChoices("TENANTS_CONFIG"),
    )

    # Tenancy: when False, a "default" tenant in tenants.yaml is used and X-Tenant-Id header is optional
    tenancy_enable: bool = Field(
        False,
        validation_alias=AliasChoices("TENANCY_ENABLE"),
    )

    # CORS
    cors_enable: bool = Field(
        True,
        validation_alias=AliasChoices("CORS_ENABLE"),
    )
    cors_allow_origins: str = Field(
        "*",
        validation_alias=AliasChoices("CORS_ALLOW_ORIGINS"),
    )

    # Metrics
    metrics_enable: bool = Field(
        True,
        validation_alias=AliasChoices("METRICS_ENABLE"),
    )

    # Cache (Valkey/Redis)
    cache_enable: bool = Field(
        True,
        validation_alias=AliasChoices("CACHE_ENABLE"),
    )
    cache_ttl: int = Field(
        60,
        validation_alias=AliasChoices("CACHE_TTL"),
    )
    cache_url: str = Field(
        "redis://localhost:6379/0",
        validation_alias=AliasChoices("CACHE_URL"),
    )
    # When using TLS (rediss://), control certificate verification
    cache_tls_verify: bool = Field(
        True,
        validation_alias=AliasChoices("CACHE_TLS_VERIFY"),
    )
    # Redis/Valkey client timeouts (seconds)
    cache_connect_timeout: float = Field(
        1.0,
        validation_alias=AliasChoices("CACHE_CONNECT_TIMEOUT"),
    )
    cache_socket_timeout: float = Field(
        2.0,
        validation_alias=AliasChoices("CACHE_SOCKET_TIMEOUT"),
    )

settings = Settings()
