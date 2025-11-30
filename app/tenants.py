import yaml
from typing import Dict, Any, Optional
from functools import lru_cache
from .config import settings

class TenantConfig:
    def __init__(self, data: Dict[str, Any]):
        self.default_backend = (data.get("default_backend") or "opensearch").lower()
        self.default_llm = (data.get("default_llm") or "ollama").lower()
        ups = data.get("upstreams") or {}
        self.upstreams = {
            "postgres": ups.get("postgres_api"),
            "oracle": ups.get("oracle_api"),
            "opensearch": ups.get("opensearch_api"),
        }
        self.auth = data.get("auth") or {}

    def upstream_for(self, backend: str) -> str:
        backend = backend.lower()
        if backend not in self.upstreams or not self.upstreams[backend]:
            raise ValueError(f"Upstream not configured for backend {backend}")
        return self.upstreams[backend]

class TenantRegistry:
    def __init__(self, cfg_path: Optional[str] = None):
        self.cfg_path = cfg_path or settings.tenants_config
        self._tenants: Dict[str, TenantConfig] = {}
        self.reload()

    def reload(self):
        with open(self.cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        tenants = data.get("tenants") or {}
        self._tenants = { k: TenantConfig(v or {}) for k, v in tenants.items() }

    def get(self, tenant_id: str) -> TenantConfig:
        t = self._tenants.get(tenant_id)
        if not t:
            raise KeyError(f"Unknown tenant_id: {tenant_id}")
        return t

@lru_cache(maxsize=1)
def get_registry() -> TenantRegistry:
    return TenantRegistry(settings.tenants_config)
