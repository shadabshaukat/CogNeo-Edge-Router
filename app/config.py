from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    router_name: str = "CogNeo Edge Router"
    router_version: str = "0.1.0"
    request_timeout: float = 30.0
    upstream_timeout: float = 30.0
    tenants_config: str = "tenants.yaml"

    # Tenancy: when False, a "default" tenant in tenants.yaml is used and X-Tenant-Id header is optional
    tenancy_enable: bool = False

    # CORS
    cors_enable: bool = True
    cors_allow_origins: str = "*"

    # Metrics
    metrics_enable: bool = True

    # Cache (Valkey/Redis)
    cache_enable: bool = True
    cache_ttl: int = 60
    cache_url: str = "redis://localhost:6379/0"
    # When using TLS (rediss://), control certificate verification
    cache_tls_verify: bool = True

    class Config:
        env_prefix = ""
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
