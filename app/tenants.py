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
        # Also allow top-level "default" key for non-tenancy runs
        default_block = data.get("default")
        self._tenants = { k: TenantConfig(v or {}) for k, v in tenants.items() }
        if default_block:
            self._tenants["default"] = TenantConfig(default_block)

    def get(self, tenant_id: str) -> TenantConfig:
        t = self._tenants.get(tenant_id)
        if not t:
            raise KeyError(f"Unknown tenant_id: {tenant_id}")
        return t

    def get_default(self) -> TenantConfig:
        t = self._tenants.get("default")
        if not t:
            # If no explicit default provided, fall back to any single tenant for dev
            if self._tenants:
                return list(self._tenants.values())[0]
            raise KeyError("No tenants configured and no default tenant present")
        return t

@lru_cache(maxsize=1)
def get_registry() -> TenantRegistry:
    return TenantRegistry(settings.tenants_config)
