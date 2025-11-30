from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Tuple
import httpx
import hashlib, json as _json
from redis.asyncio import Redis
from redis.asyncio.cluster import RedisCluster
from urllib.parse import urlparse
import ssl
import logging
import re, string
from .semcache import get_semantic_cache, SemContext

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
_redis: Optional[Redis] = None
logger = logging.getLogger("cogneo-edge-router")
# Ensure INFO-level output for cache HIT/MISS/SET visibility
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

def get_client(base_url: str) -> httpx.AsyncClient:
    c = _clients.get(base_url)
    if not c:
        c = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(settings.upstream_timeout))
        _clients[base_url] = c
    return c

async def get_cache() -> Optional[Redis]:
    global _redis
    if not settings.cache_enable:
        return None
    if _redis is None:
        # Respect TLS verification and support Cluster mode (handles MOVED redirections)
        try:
            parsed = urlparse(settings.cache_url)
            kwargs = dict(
                decode_responses=True,
                socket_connect_timeout=settings.cache_connect_timeout,
                socket_timeout=settings.cache_socket_timeout,
            )
            tls_kwargs = {}
            if parsed.scheme == "rediss" and not settings.cache_tls_verify:
                tls_kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
            if settings.cache_cluster_enable:
                _redis = RedisCluster.from_url(settings.cache_url, **kwargs, **tls_kwargs)
            else:
                _redis = Redis.from_url(settings.cache_url, **kwargs, **tls_kwargs)
        except Exception:
            # Fallback: minimal client with timeouts
            if settings.cache_cluster_enable:
                _redis = RedisCluster.from_url(
                    settings.cache_url,
                    decode_responses=True,
                    socket_connect_timeout=settings.cache_connect_timeout,
                    socket_timeout=settings.cache_socket_timeout,
                )
            else:
                _redis = Redis.from_url(
                    settings.cache_url,
                    decode_responses=True,
                    socket_connect_timeout=settings.cache_connect_timeout,
                    socket_timeout=settings.cache_socket_timeout,
                )
    return _redis

async def cache_get(key: str) -> Optional[str]:
    """
    Safe cache GET that never raises. Returns None on any cache error or miss.
    """
    try:
        rc = await get_cache()
        if rc:
            return await rc.get(key)
    except Exception as e:
        logger.warning("Cache GET failed for key %s: %s", key, e)
    return None

async def cache_setex(key: str, ttl: int, value: str) -> None:
    """
    Safe cache SETEX that never raises. Swallows cache connectivity errors.
    """
    try:
        rc = await get_cache()
        if rc:
            await rc.setex(key, ttl, value)
    except Exception as e:
        logger.warning("Cache SETEX failed for key %s: %s", key, e)

async def resolve_tenant(x_tenant_id: Optional[str] = Header(default=None)) -> Tuple[str, TenantConfig]:
    reg: TenantRegistry = get_registry()
    # Tenancy optional: when disabled, use "default" block
    if not settings.tenancy_enable:
        cfg = None
        try:
            cfg = reg.get("default")
        except Exception:
            cfg = reg.get_default()
        return ("default", cfg)
    # Tenancy enabled -> require header
    if not x_tenant_id:
        raise HTTPException(401, "Missing X-Tenant-Id")
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

def _cache_key(endpoint: str, backend: str, payload: dict) -> str:
    body = _json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{endpoint}:{backend}:{h}"

def _extract_auth(payload: dict, default_auth: Tuple[str, str] | None) -> tuple[Tuple[str, str] | None, dict]:
    """
    Allow overriding upstream basic auth by passing _upstream_user/_upstream_pass in payload.
    These keys are removed from the forwarded payload if present.
    """
    user = payload.pop("_upstream_user", None)
    pwd = payload.pop("_upstream_pass", None)
    if user is not None and pwd is not None:
        return (user, pwd), payload
    return default_auth, payload

def _norm_text(s: Optional[str]) -> Optional[str]:
    """
    Lightweight normalization to improve cache key hit-rate for trivial variations.
    Applies only to cache keys (never mutates upstream request body).
    """
    if not isinstance(s, str):
        return s
    if not settings.cache_normalize_query:
        return s
    t = s.lower()
    t = re.sub(r"\s+", " ", t).strip()  # collapse whitespace
    t = t.translate(str.maketrans("", "", string.punctuation))  # strip punctuation
    return t

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
    payload = {"query": req.query, "top_k": req.top_k}
    auth_eff, payload2 = _extract_auth(dict(payload), auth)
    # Cache key (apply normalization to query only for keying)
    payload_cache = dict(payload2)
    if "query" in payload_cache:
        payload_cache["query"] = _norm_text(payload_cache["query"])
    ck = _cache_key("/v1/search/vector", backend, payload_cache)
    hit = await cache_get(ck)
    if hit:
        logger.info("CACHE HIT /v1/search/vector backend=%s key=%s", backend, ck)
        return _json.loads(hit)
    # Semantic cache (best-effort)
    semc = await get_semantic_cache()
    sh = await semc.try_get(req.query, SemContext(tenant_id=tenant_id, endpoint="/v1/search/vector", backend=backend))
    if sh is not None:
        return sh
    logger.info("CACHE MISS /v1/search/vector backend=%s key=%s -> proxy & store", backend, ck)
    # Proxy
    r = await client.post("/search/vector", json=payload2, auth=auth_eff)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    out = r.json()
    logger.info("CACHE SET /v1/search/vector backend=%s key=%s ttl=%s", backend, ck, settings.cache_ttl)
    semc = await get_semantic_cache()
    await semc.put(req.query, SemContext(tenant_id=tenant_id, endpoint="/v1/search/vector", backend=backend), out)
    await cache_setex(ck, settings.cache_ttl, _json.dumps(out))
    return out

@app.post("/v1/search/hybrid")
async def hybrid_search(req: HybridReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    payload = {"query": req.query, "top_k": req.top_k, "alpha": req.alpha}
    auth_eff, payload2 = _extract_auth(dict(payload), auth)
    payload_cache = dict(payload2)
    if "query" in payload_cache:
        payload_cache["query"] = _norm_text(payload_cache["query"])
    ck = _cache_key("/v1/search/hybrid", backend, payload_cache)
    hit = await cache_get(ck)
    if hit:
        logger.info("CACHE HIT /v1/search/hybrid backend=%s key=%s", backend, ck)
        return _json.loads(hit)
    # Semantic cache (best-effort)
    semc = await get_semantic_cache()
    sh = await semc.try_get(req.query, SemContext(tenant_id=tenant_id, endpoint="/v1/search/hybrid", backend=backend))
    if sh is not None:
        return sh
    logger.info("CACHE MISS /v1/search/hybrid backend=%s key=%s -> proxy & store", backend, ck)
    r = await client.post("/search/hybrid", json=payload2, auth=auth_eff)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    out = r.json()
    logger.info("CACHE SET /v1/search/hybrid backend=%s key=%s ttl=%s", backend, ck, settings.cache_ttl)
    semc = await get_semantic_cache()
    await semc.put(req.query, SemContext(tenant_id=tenant_id, endpoint="/v1/search/hybrid", backend=backend), out)
    await cache_setex(ck, settings.cache_ttl, _json.dumps(out))
    return out

@app.post("/v1/search/fts")
async def fts_search(req: FtsReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    payload = {"query": req.query, "top_k": req.top_k, "mode": req.mode}
    auth_eff, payload2 = _extract_auth(dict(payload), auth)
    payload_cache = dict(payload2)
    if "query" in payload_cache:
        payload_cache["query"] = _norm_text(payload_cache["query"])
    ck = _cache_key("/v1/search/fts", backend, payload_cache)
    hit = await cache_get(ck)
    if hit:
        logger.info("CACHE HIT /v1/search/fts backend=%s key=%s", backend, ck)
        return _json.loads(hit)
    # Semantic cache (best-effort)
    semc = await get_semantic_cache()
    sh = await semc.try_get(req.query, SemContext(tenant_id=tenant_id, endpoint="/v1/search/fts", backend=backend))
    if sh is not None:
        return sh
    logger.info("CACHE MISS /v1/search/fts backend=%s key=%s -> proxy & store", backend, ck)
    r = await client.post("/search/fts", json=payload2, auth=auth_eff)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    out = r.json()
    logger.info("CACHE SET /v1/search/fts backend=%s key=%s ttl=%s", backend, ck, settings.cache_ttl)
    semc = await get_semantic_cache()
    await semc.put(req.query, SemContext(tenant_id=tenant_id, endpoint="/v1/search/fts", backend=backend), out)
    await cache_setex(ck, settings.cache_ttl, _json.dumps(out))
    return out

# RAG (pass-through to upstream /search/rag)
@app.post("/v1/search/rag")
async def rag(req: RagReq, t=Depends(resolve_tenant)):
    tenant_id, cfg = t
    backend = pick_backend(cfg, req.backend)
    base, auth = upstream_and_auth(cfg, backend)
    client = get_client(base)
    payload = req.model_dump(exclude_none=True)
    auth_eff, payload2 = _extract_auth(dict(payload), auth)
    # Cache for RAG if context provided and deterministic-ish parameters (best-effort)
    payload_cache = dict(payload2)
    if "question" in payload_cache:
        payload_cache["question"] = _norm_text(payload_cache["question"])
    ck = _cache_key("/v1/search/rag", backend, payload_cache)
    hit = await cache_get(ck)
    if hit:
        logger.info("CACHE HIT /v1/search/rag backend=%s key=%s", backend, ck)
        return _json.loads(hit)
    # Semantic cache (best-effort)
    semc = await get_semantic_cache()
    sh = await semc.try_get(
        req.question,
        SemContext(
            tenant_id=tenant_id,
            endpoint="/v1/search/rag",
            backend=backend,
            llm_source=pick_llm(cfg, req.llm_source),
            model=req.model,
        ),
    )
    if sh is not None:
        return sh
    logger.info("CACHE MISS /v1/search/rag backend=%s key=%s -> proxy & store", backend, ck)
    r = await client.post("/search/rag", json=payload2, auth=auth_eff)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    out = r.json()
    logger.info("CACHE SET /v1/search/rag backend=%s key=%s ttl=%s", backend, ck, settings.cache_ttl)
    semc = await get_semantic_cache()
    await semc.put(
        req.question,
        SemContext(
            tenant_id=tenant_id,
            endpoint="/v1/search/rag",
            backend=backend,
            llm_source=pick_llm(cfg, req.llm_source),
            model=req.model,
        ),
        out,
    )
    await cache_setex(ck, settings.cache_ttl, _json.dumps(out))
    return out

# Chat endpoints (cache based on message + top_k + model + llm_source as heuristic)
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
    auth_eff, payload2 = _extract_auth(dict(payload), auth)
    key_subset = {k: v for k, v in payload2.items() if k in ("llm_source","model","message","top_k")}
    if "message" in key_subset:
        key_subset["message"] = _norm_text(key_subset["message"])
    ck = _cache_key("/v1/chat/conversation", backend, key_subset)
    hit = await cache_get(ck)
    if hit:
        logger.info("CACHE HIT /v1/chat/conversation backend=%s key=%s", backend, ck)
        return _json.loads(hit)
    # Semantic cache (best-effort)
    semc = await get_semantic_cache()
    sh = await semc.try_get(
        req.message,
        SemContext(
            tenant_id=tenant_id,
            endpoint="/v1/chat/conversation",
            backend=backend,
            llm_source=pick_llm(cfg, req.llm_source),
            model=req.model,
        ),
    )
    if sh is not None:
        return sh
    logger.info("CACHE MISS /v1/chat/conversation backend=%s key=%s -> proxy & store", backend, ck)
    r = await client.post("/chat/conversation", json={k: v for k, v in payload2.items() if v is not None}, auth=auth_eff)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    out = r.json()
    logger.info("CACHE SET /v1/chat/conversation backend=%s key=%s ttl=%s", backend, ck, settings.cache_ttl)
    semc = await get_semantic_cache()
    await semc.put(
        req.message,
        SemContext(
            tenant_id=tenant_id,
            endpoint="/v1/chat/conversation",
            backend=backend,
            llm_source=pick_llm(cfg, req.llm_source),
            model=req.model,
        ),
        out,
    )
    await cache_setex(ck, settings.cache_ttl, _json.dumps(out))
    return out

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
    auth_eff, payload2 = _extract_auth(dict(payload), auth)
    key_subset = {k: v for k, v in payload2.items() if k in ("llm_source","model","message","top_k")}
    if "message" in key_subset:
        key_subset["message"] = _norm_text(key_subset["message"])
    ck = _cache_key("/v1/chat/agentic", backend, key_subset)
    hit = await cache_get(ck)
    if hit:
        logger.info("CACHE HIT /v1/chat/agentic backend=%s key=%s", backend, ck)
        return _json.loads(hit)
    # Semantic cache (best-effort)
    semc = await get_semantic_cache()
    sh = await semc.try_get(
        req.message,
        SemContext(
            tenant_id=tenant_id,
            endpoint="/v1/chat/agentic",
            backend=backend,
            llm_source=pick_llm(cfg, req.llm_source),
            model=req.model,
        ),
    )
    if sh is not None:
        return sh
    logger.info("CACHE MISS /v1/chat/agentic backend=%s key=%s -> proxy & store", backend, ck)
    r = await client.post("/chat/agentic", json={k: v for k, v in payload2.items() if v is not None}, auth=auth_eff)
    if r.status_code >= 500:
        raise HTTPException(502, f"Upstream error ({backend})")
    out = r.json()
    logger.info("CACHE SET /v1/chat/agentic backend=%s key=%s ttl=%s", backend, ck, settings.cache_ttl)
    semc = await get_semantic_cache()
    await semc.put(
        req.message,
        SemContext(
            tenant_id=tenant_id,
            endpoint="/v1/chat/agentic",
            backend=backend,
            llm_source=pick_llm(cfg, req.llm_source),
            model=req.model,
        ),
        out,
    )
    await cache_setex(ck, settings.cache_ttl, _json.dumps(out))
    return out
