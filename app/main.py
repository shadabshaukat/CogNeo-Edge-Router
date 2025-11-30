from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Tuple
import httpx
from .config import settings
from .tenants import get_registry, TenantRegistry, TenantConfig
from .types import HybridReq, VectorReq, FtsReq, RagReq, ChatReq

app = FastAPI(title=settings.router_name, version=settings.router_version)

# CORS
if settings.cors_enable:
    origins = [o.strip() for o in (settings.cors_allow_origins or "*").split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Metrics
if settings.metrics_enable:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app, include_in_schema=False)
    except Exception:
        pass

# Shared httpx clients cache (per upstream base URL)
_clients: dict[str, httpx.AsyncClient] = {}

def get_client(base_url: str) -> httpx.AsyncClient:
    c = _clients.get(base_url)
    if not c:
        c = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(settings.upstream_timeout))
        _clients[base_url] = c
    return c

async def resolve_tenant(x_tenant_id: Optional[str] = Header(default=None)) -> Tuple[str, TenantConfig]:
    if not x_tenant_id:
        raise HTTPException(401, "Missing X-Tenant-Id")
    reg: TenantRegistry = get_registry()
    try:
        cfg = reg.get(x_tenant_id)
        return x_tenant_id, cfg
    except KeyError:
        raise HTTPException(401, f"Unknown tenant: {x_tenant_id}")

def pick_backend(cfg: TenantConfig, override: Optional[str]) -> str:
    b = (override or cfg.default_backend).lower()
    if b not in ("postgres", "oracle", "opensearch"):
        raise HTTPException(400, "Invalid backend")
    return b

def pick_llm(cfg: TenantConfig, override: Optional[str]) -> str:
    s = (override or cfg.default_llm).lower()
    if s not in ("ollama", "oci_genai", "bedrock"):
        raise HTTPException(400, "Invalid llm_source")
    return s

def upstream_and_auth(cfg: TenantConfig, backend: str) -> Tuple[str, Tuple[str, str] | None]:
    base = cfg.upstream_for(backend)
    auth_dict = cfg.auth or {}
    auth = None
    if auth_dict.get("user") and auth_dict.get("pass"):
        auth = (auth_dict["user"], auth_dict["pass"])
    return base, auth

@app.get("/health")
async def health():
    return {"ok": True}

# Search endpoints
@app.post("/v1/search/vector")
async def vector_search(req: VectorReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    r = await client.post("/search/vector", json={"query": req.query, "top_k": req.top_k}, auth=auth)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    return r.json()

@app.post("/v1/search/hybrid")
async def hybrid_search(req: HybridReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    r = await client.post("/search/hybrid", json={"query": req.query, "top_k": req.top_k, "alpha": req.alpha}, auth=auth)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    return r.json()

@app.post("/v1/search/fts")
async def fts_search(req: FtsReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    r = await client.post("/search/fts", json={"query": req.query, "top_k": req.top_k, "mode": req.mode}, auth=auth)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    return r.json()

# RAG (pass-through to upstream /search/rag)
@app.post("/v1/search/rag")
async def rag(req: RagReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    payload = req.model_dump(exclude_none=True)
    r = await client.post("/search/rag", json=payload, auth=auth)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    return r.json()

# Chat endpoints
@app.post("/v1/chat/conversation")
async def chat_conversation(req: ChatReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    payload = {
        "llm_source": pick_llm(cfg, req.llm_source),
        "model": req.model,
        "message": req.message,
        "chat_history": req.chat_history,
        "system_prompt": req.system_prompt,
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
        "repeat_penalty": req.repeat_penalty,
        "top_k": req.top_k,
    }
    r = await client.post("/chat/conversation", json={k: v for k, v in payload.items() if v is not None}, auth=auth)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    return r.json()

@app.post("/v1/chat/agentic")
async def chat_agentic(req: ChatReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    payload = {
        "llm_source": pick_llm(cfg, req.llm_source),
        "model": req.model,
        "message": req.message,
        "chat_history": req.chat_history,
        "system_prompt": req.system_prompt,
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
        "repeat_penalty": req.repeat_penalty,
        "top_k": req.top_k,
    }
    r = await client.post("/chat/agentic", json={k: v for k, v in payload.items() if v is not None}, auth=auth)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    return r.json()
