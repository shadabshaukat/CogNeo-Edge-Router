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
    # Normalize query text before hashing cache keys for search endpoints
    cache_normalize_query: bool = Field(
        False,
        validation_alias=AliasChoices("CACHE_NORMALIZE_QUERY"),
    )
    # Valkey/Redis Cluster mode (use when endpoint returns MOVED redirections)
    cache_cluster_enable: bool = Field(
        False,
        validation_alias=AliasChoices("CACHE_CLUSTER_ENABLE"),
    )

    # Semantic cache (router-side, backed by OpenSearch or pgvector)
    semcache_enable: bool = Field(
        False,
        validation_alias=AliasChoices("SEMCACHE_ENABLE"),
    )
    semcache_provider: str = Field(
        "opensearch",  # opensearch | pgvector
        validation_alias=AliasChoices("SEMCACHE_PROVIDER"),
    )
    semcache_threshold: float = Field(
        0.90,  # cosine similarity threshold
        validation_alias=AliasChoices("SEMCACHE_THRESHOLD"),
    )
    semcache_ttl: int = Field(
        3600,  # seconds
        validation_alias=AliasChoices("SEMCACHE_TTL"),
    )
    # Embedding model (router local)
    semcache_embedder: str = Field(
        "fastembed_e5_small",  # reserved for future options
        validation_alias=AliasChoices("SEMCACHE_EMBEDDER"),
    )
    semcache_dim: int = Field(
        384,  # default dimension for e5-small
        validation_alias=AliasChoices("SEMCACHE_DIM"),
    )

    # OpenSearch semantic cache config
    semcache_os_url: str = Field(
        "http://localhost:9200",
        validation_alias=AliasChoices("SEMCACHE_OS_URL"),
    )
    semcache_os_index: str = Field(
        "semcache",
        validation_alias=AliasChoices("SEMCACHE_OS_INDEX"),
    )
    semcache_os_user: str = Field(
        "",
        validation_alias=AliasChoices("SEMCACHE_OS_USER"),
    )
    semcache_os_pass: str = Field(
        "",
        validation_alias=AliasChoices("SEMCACHE_OS_PASS"),
    )

    # pgvector semantic cache config
    semcache_pg_dsn: str = Field(
        "postgresql://postgres:postgres@localhost:5432/postgres",
        validation_alias=AliasChoices("SEMCACHE_PG_DSN"),
    )
    semcache_pg_table: str = Field(
        "semcache",
        validation_alias=AliasChoices("SEMCACHE_PG_TABLE"),
    )

settings = Settings()
