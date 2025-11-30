from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    router_name: str = "CogNeo Edge Router"
    router_version: str = "0.1.0"
    request_timeout: float = 30.0
    upstream_timeout: float = 30.0
    tenants_config: str = "tenants.yaml"
    cors_enable: bool = True
    cors_allow_origins: str = "*"
    metrics_enable: bool = True

    class Config:
        env_prefix = ""
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
