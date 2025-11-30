import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import anyio
import httpx
import logging

from .config import settings

logger = logging.getLogger("cogneo-edge-router.semcache")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_in(seconds: int) -> datetime:
    return _utc_now() + timedelta(seconds=seconds)


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return -1.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 <= 0 or n2 <= 0:
        return -1.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))


@dataclass
class SemContext:
    tenant_id: str
    endpoint: str
    backend: str
    llm_source: Optional[str] = None
    model: Optional[str] = None


class _Embedder:
    """
    Simple wrapper around fastembed. If fastembed is not available, this
    embedder is disabled and semantic cache will no-op.
    """

    def __init__(self, model_name: str, dim: int):
        self.enabled = False
        self.dim = dim
        try:
            from fastembed import TextEmbedding  # type: ignore

            # Map the semantic embedder setting to a fastembed model
            # Default to e5-small-v2 (384 dim) for small footprint CPU-only
            if model_name == "fastembed_e5_small":
                fe_model = "intfloat/e5-small-v2"
                self.dim = 384
            else:
                fe_model = model_name
            self._model = TextEmbedding(model_name=fe_model)
            # Dry-run to ensure it works
            _ = list(self._model.embed(["hello"]))[0]
            self.enabled = True
            logger.info("Semantic embedder ready: %s (dim=%s)", fe_model, self.dim)
        except Exception as e:
            logger.warning("Semantic embedder unavailable (fastembed missing or error): %s", e)
            self.enabled = False
            self._model = None

    async def embed(self, text: str) -> Optional[List[float]]:
        if not self.enabled or not text:
            return None
        # fastembed is synchronous; run in a worker thread
        def _run() -> List[float]:
            return list(self._model.embed([text]))[0]  # type: ignore[attr-defined]
        try:
            vec = await anyio.to_thread.run_sync(_run)
            return list(map(float, vec))
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return None


class _OpenSearchProvider:
    def __init__(self, base_url: str, index: str, user: str = "", pwd: str = "", dim: int = 384):
        self.base_url = base_url.rstrip("/")
        self.index = index
        self.dim = dim
        auth = (user, pwd) if user or pwd else None
        self._client = httpx.AsyncClient(base_url=self.base_url, auth=auth, timeout=10.0)

    async def ensure_index(self):
        try:
            resp = await self._client.get(f"/{self.index}")
            if resp.status_code == 200:
                return
            # Create index
            body = {
                "settings": {"index": {"knn": True}},
                "mappings": {
                    "properties": {
                        "tenant_id": {"type": "keyword"},
                        "endpoint": {"type": "keyword"},
                        "backend": {"type": "keyword"},
                        "llm_source": {"type": "keyword"},
                        "model": {"type": "keyword"},
                        "params_hash": {"type": "keyword"},
                        "query_text": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": self.dim,
                            "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "nmslib"},
                        },
                        "response_json": {"type": "text"},
                        "created_at": {"type": "date"},
                        "expires_at": {"type": "date"},
                    }
                },
            }
            cr = await self._client.put(f"/{self.index}", json=body)
            if cr.status_code >= 300:
                logger.warning("OpenSearch semcache: index create failed: %s %s", cr.status_code, cr.text)
        except Exception as e:
            logger.warning("OpenSearch semcache: ensure_index error: %s", e)

    async def search(self, vec: List[float], ctx: SemContext, threshold: float) -> Optional[Dict[str, Any]]:
        try:
            q: Dict[str, Any] = {
                "size": 1,
                "_source": ["response_json", "embedding"],
                "knn": {"field": "embedding", "query_vector": vec, "k": 1, "num_candidates": 50},
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"tenant_id": ctx.tenant_id}},
                            {"term": {"endpoint": ctx.endpoint}},
                            {"term": {"backend": ctx.backend}},
                            {"range": {"expires_at": {"gte": "now"}}},
                        ]
                    }
                },
            }
            if ctx.llm_source:
                q["query"]["bool"]["filter"].append({"term": {"llm_source": ctx.llm_source}})
            if ctx.model:
                q["query"]["bool"]["filter"].append({"term": {"model": ctx.model}})
            resp = await self._client.post(f"/{self.index}/_search", json=q)
            if resp.status_code >= 300:
                return None
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                return None
            doc = hits[0].get("_source", {})
            emb = doc.get("embedding")
            if not isinstance(emb, list):
                return None
            sim = _cosine_similarity(vec, [float(x) for x in emb])
            if sim >= threshold:
                try:
                    return json.loads(doc.get("response_json", "{}"))
                except Exception:
                    return None
            return None
        except Exception as e:
            logger.warning("OpenSearch semcache: search error: %s", e)
            return None

    async def index_doc(self, vec: List[float], ctx: SemContext, query_text: str, response: Dict[str, Any], ttl: int):
        try:
            body = {
                "tenant_id": ctx.tenant_id,
                "endpoint": ctx.endpoint,
                "backend": ctx.backend,
                "llm_source": ctx.llm_source,
                "model": ctx.model,
                "params_hash": "",  # reserved
                "query_text": query_text,
                "embedding": vec,
                "response_json": json.dumps(response),
                "created_at": _utc_now().isoformat(),
                "expires_at": _utc_in(ttl).isoformat(),
            }
            resp = await self._client.post(f"/{self.index}/_doc", json=body)
            if resp.status_code >= 300:
                logger.warning("OpenSearch semcache: index doc failed: %s %s", resp.status_code, resp.text)
        except Exception as e:
            logger.warning("OpenSearch semcache: index error: %s", e)


class _PgVectorProvider:
    def __init__(self, dsn: str, table: str, dim: int = 384):
        self.dsn = dsn
        self.table = table
        self.dim = dim
        self._ready = False

    def _connect(self):
        import psycopg2  # type: ignore

        return psycopg2.connect(self.dsn)

    def _ensure(self):
        if self._ready:
            return
        conn = self._connect()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table} (
                        id bigserial PRIMARY KEY,
                        tenant_id text,
                        endpoint text,
                        backend text,
                        llm_source text,
                        model text,
                        params_hash text,
                        query_text text,
                        embedding vector({self.dim}),
                        response_json text,
                        created_at timestamptz DEFAULT now(),
                        expires_at timestamptz
                    );
                    """
                )
                # Create ANN index if not exists
                cur.execute(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_class c
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.relname = '{self.table}_ann_idx'
                        ) THEN
                            EXECUTE 'CREATE INDEX {self.table}_ann_idx ON {self.table} USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);';
                        END IF;
                    END$$;
                    """
                )
            self._ready = True
        finally:
            conn.close()

    def _to_vector_literal(self, vec: List[float]) -> str:
        # pgvector accepts array-like casts: '[0.1,0.2,...]'
        return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

    def _search(self, vec: List[float], ctx: SemContext, threshold: float) -> Optional[Dict[str, Any]]:
        import psycopg2  # type: ignore

        self._ensure()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                vstr = self._to_vector_literal(vec)
                sql = f"""
                    SELECT response_json, 1 - (embedding <=> %s::vector) AS score
                    FROM {self.table}
                    WHERE tenant_id = %s
                      AND endpoint = %s
                      AND backend = %s
                      AND (llm_source IS NULL OR llm_source = %s)
                      AND (model IS NULL OR model = %s)
                      AND (expires_at IS NULL OR expires_at > now())
                    ORDER BY embedding <=> %s::vector
                    LIMIT 1;
                """
                params = (vstr, ctx.tenant_id, ctx.endpoint, ctx.backend, ctx.llm_source, ctx.model, vstr)
                cur.execute(sql, params)
                row = cur.fetchone()
                if not row:
                    return None
                response_json, score = row
                if score is not None and float(score) >= float(threshold):
                    try:
                        return json.loads(response_json or "{}")
                    except Exception:
                        return None
                return None
        finally:
            conn.close()

    def _index(self, vec: List[float], ctx: SemContext, query_text: str, response: Dict[str, Any], ttl: int):
        import psycopg2  # type: ignore

        self._ensure()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                vstr = self._to_vector_literal(vec)
                expires = _utc_in(ttl)
                sql = f"""
                    INSERT INTO {self.table}
                      (tenant_id, endpoint, backend, llm_source, model, params_hash, query_text, embedding, response_json, created_at, expires_at)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s);
                """
                cur.execute(
                    sql,
                    (
                        ctx.tenant_id,
                        ctx.endpoint,
                        ctx.backend,
                        ctx.llm_source,
                        ctx.model,
                        "",
                        query_text,
                        vstr,
                        json.dumps(response),
                        _utc_now(),
                        expires,
                    ),
                )
                conn.commit()
        finally:
            conn.close()

    async def ensure_ready(self):
        await anyio.to_thread.run_sync(self._ensure)

    async def search(self, vec: List[float], ctx: SemContext, threshold: float) -> Optional[Dict[str, Any]]:
        return await anyio.to_thread.run_sync(self._search, vec, ctx, threshold)

    async def index_doc(self, vec: List[float], ctx: SemContext, query_text: str, response: Dict[str, Any], ttl: int):
        await anyio.to_thread.run_sync(self._index, vec, ctx, query_text, response, ttl)


class SemanticCache:
    def __init__(self):
        self.enabled = bool(settings.semcache_enable)
        self.threshold = float(settings.semcache_threshold)
        self.ttl = int(settings.semcache_ttl)
        self.embedder = _Embedder(settings.semcache_embedder, settings.semcache_dim)
        self.provider: Optional[Any] = None

        if not self.enabled:
            logger.info("Semantic cache disabled (SEMCACHE_ENABLE=0)")
            return
        if not self.embedder.enabled:
            logger.warning("Semantic cache disabled: embedder unavailable")
            self.enabled = False
            return

        prov = settings.semcache_provider.lower().strip()
        try:
            if prov == "opensearch":
                self.provider = _OpenSearchProvider(
                    base_url=settings.semcache_os_url,
                    index=settings.semcache_os_index,
                    user=settings.semcache_os_user,
                    pwd=settings.semcache_os_pass,
                    dim=self.embedder.dim,
                )
            elif prov == "pgvector":
                self.provider = _PgVectorProvider(
                    dsn=settings.semcache_pg_dsn,
                    table=settings.semcache_pg_table,
                    dim=self.embedder.dim,
                )
            else:
                logger.warning("Unknown SEMCACHE_PROVIDER=%s; disabling semantic cache", prov)
                self.enabled = False
                return
        except Exception as e:
            logger.warning("Semantic cache provider init failed: %s", e)
            self.enabled = False
            self.provider = None

    async def ensure_ready(self):
        if not self.enabled or not self.provider:
            return
        try:
            if isinstance(self.provider, _OpenSearchProvider):
                await self.provider.ensure_index()
            elif isinstance(self.provider, _PgVectorProvider):
                await self.provider.ensure_ready()
        except Exception as e:
            logger.warning("Semantic cache ensure_ready failed: %s", e)

    async def try_get(self, text: Optional[str], ctx: SemContext) -> Optional[Dict[str, Any]]:
        if not (self.enabled and self.provider and text):
            return None
        vec = await self.embedder.embed(text)
        if not vec:
            return None
        try:
            hit = await self.provider.search(vec, ctx, self.threshold)
            if hit is not None:
                logger.info("SEMCACHE HIT %s backend=%s tenant=%s", ctx.endpoint, ctx.backend, ctx.tenant_id)
            return hit
        except Exception as e:
            logger.warning("Semantic cache get failed: %s", e)
            return None

    async def put(self, text: Optional[str], ctx: SemContext, response: Dict[str, Any]):
        if not (self.enabled and self.provider and text and response is not None):
            return
        vec = await self.embedder.embed(text)
        if not vec:
            return
        try:
            await self.provider.index_doc(vec, ctx, text, response, self.ttl)
            logger.info("SEMCACHE SET %s backend=%s tenant=%s ttl=%s", ctx.endpoint, ctx.backend, ctx.tenant_id, self.ttl)
        except Exception as e:
            logger.warning("Semantic cache put failed: %s", e)


_semcache_singleton: Optional[SemanticCache] = None


async def get_semantic_cache() -> SemanticCache:
    global _semcache_singleton
    if _semcache_singleton is None:
        _semcache_singleton = SemanticCache()
        await _semcache_singleton.ensure_ready()
    return _semcache_singleton
