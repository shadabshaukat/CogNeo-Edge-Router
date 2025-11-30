# CogNeo-Edge-Router

Edge Router (FastAPI) that fronts multiple CogNeo stacks and routes requests to a selected vector backend (Postgres/pgvector, Oracle 26ai, OpenSearch) and LLM provider (Ollama, OCI GenAI, AWS Bedrock) per-tenant or per-request. Designed as an API Gateway-like component to build multi-backend, multi-inference, internet-scale RAG applications.

## Features

- Route-by-parameter:
  - Vector backend: postgres | oracle | opensearch
  - Inference provider: ollama | oci_genai | bedrock
- Optional tenancy:
  - When disabled (default), no tenant header is required. A `default` routing config is used.
  - When enabled, routing is resolved by `X-Tenant-Id`.
- Async upstream proxy with httpx keep-alive
- Response caching via Valkey/Redis with TTL and optional TLS verification
- Observability with Prometheus metrics
- Dockerized; production-ready patterns

---

## Directory Layout

```
.
├─ app/
│  ├─ main.py            # FastAPI endpoints + routing + caching
│  ├─ config.py          # Pydantic settings (.env)
│  ├─ tenants.py         # Tenants/default routing config loader (YAML)
│  └─ types.py           # Pydantic models for request payloads
├─ tenants.example.yaml  # Example tenants/default routing config
├─ .env                  # Environment configuration (with descriptions)
├─ requirements.txt
├─ Dockerfile
└─ README.md
```

---

## Quick Start (Local)

1) Create and activate a venv (optional):
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2) Install dependencies:
```bash
pip install -r requirements.txt
```

3) Prepare configs and edit:
```bash
cp tenants.example.yaml tenants.yaml
# Edit tenants.yaml: point upstreams to your CogNeo stacks and set basic auth if needed
# Edit .env: set timeouts, caching, tenancy, etc.
```

4) Run the router:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

5) Health:
```bash
curl -s http://localhost:8080/health
```

---

## Docker

Build:
```bash
docker build -t cogneo-edge-router:latest .
```

Run:
```bash
docker run --rm -p 8080:8080 \
  --env-file .env \
  -v "$(pwd)/tenants.yaml:/app/tenants.yaml:ro" \
  cogneo-edge-router:latest
```

---

## Configuration (.env)

This repository ships with `.env` out of the box. Edit values as needed.

- REQUEST_TIMEOUT
  - Description: Default request timeout (seconds) for the Router’s API.
  - Values: integer seconds (e.g., 30, 60, 120).
  - Default: `30`
- UPSTREAM_TIMEOUT
  - Description: HTTP timeout (seconds) used for calls to upstream CogNeo stacks.
  - Values: integer seconds.
  - Default: `30`
- TENANTS_CONFIG
  - Description: Path to the routing config file (YAML).
  - Values: relative/absolute path, e.g., `tenants.yaml`.
  - Default: `tenants.yaml`
- TENANCY_ENABLE
  - Description: Enable multi-tenant routing by X-Tenant-Id header.
  - Values: `0` = disabled (use `default` block; X-Tenant-Id not required), `1` = enabled (X-Tenant-Id required; use `tenants.<id>`).
  - Default: `0`
- CORS_ENABLE
  - Description: Enable CORS middleware.
  - Values: `0`/`1`.
  - Default: `1`
- CORS_ALLOW_ORIGINS
  - Description: Comma-separated allowed origins. Use `*` to allow all.
  - Default: `*`
- METRICS_ENABLE
  - Description: Expose Prometheus metrics endpoint `/metrics`.
  - Values: `0`/`1`.
  - Default: `1`
- CACHE_ENABLE
  - Description: Enable response caching via Valkey/Redis.
  - Values: `0`/`1`.
  - Default: `1`
- CACHE_TTL
  - Description: TTL (seconds) for cached responses.
  - Values: integer seconds.
  - Default: `60`
- CACHE_URL
  - Description: Valkey/Redis URL: `redis://host:port/db` or `rediss://host:port/db` (TLS).
  - Default: `redis://localhost:6379/0`
- CACHE_TLS_VERIFY
  - Description: TLS certificate verification for rediss://.
  - Values: `1` = verify (recommended), `0` = skip for testing.
  - Default: `1`

Example `.env`:
```ini
# Router
REQUEST_TIMEOUT=30
UPSTREAM_TIMEOUT=30
TENANTS_CONFIG=tenants.yaml

# Tenancy (0 = disabled, 1 = enabled)
TENANCY_ENABLE=0

# CORS
CORS_ENABLE=1
CORS_ALLOW_ORIGINS=*

# Metrics
METRICS_ENABLE=1

# Cache (Valkey/Redis)
CACHE_ENABLE=1
CACHE_TTL=60
# redis:// for plaintext, rediss:// for TLS
CACHE_URL=redis://localhost:6379/0
CACHE_TLS_VERIFY=1
```

---

## Tenants Routing Config (tenants.yaml)

When `TENANCY_ENABLE=0`, the Router uses the `default` block. When `TENANCY_ENABLE=1`, it expects requests to include `X-Tenant-Id` and looks up that key under `tenants:`.

Example:
```yaml
tenants:
  tenantA:
    default_backend: opensearch        # postgres | oracle | opensearch
    default_llm: bedrock               # ollama | oci_genai | bedrock
    upstreams:
      postgres_api: "http://pg-stack:8000"
      oracle_api:   "http://ora-stack:8000"
      opensearch_api: "http://os-stack:8000"
    auth:
      user: "legal_api"
      pass: "letmein"

# Used when TENANCY_ENABLE=0
default:
  default_backend: opensearch
  default_llm: bedrock
  upstreams:
    postgres_api: "http://localhost:8001"
    oracle_api:   "http://localhost:8002"
    opensearch_api: "http://localhost:8003"
  auth:
    user: "legal_api"
    pass: "letmein"
```

---

## API Gateway Capability

- The Router accepts backend and LLM source overrides in the request body and forwards the request to the appropriate upstream.
- It acts as an API Gateway to your vector backend and inference providers based on client parameters.
- Upstream auth can be per-tenant in `tenants.yaml`, or overridden per-request via special fields.

### Per-request upstream auth override

Include in the JSON payload:
- `_upstream_user`: upstream basic auth username
- `_upstream_pass`: upstream basic auth password

These fields are removed from the forwarded payload and only used to set upstream auth for that specific call.

---

## Endpoints and Examples (curl)

Notes:
- Tenancy disabled (default): omit `-H "X-Tenant-Id: ..."`
- Tenancy enabled: add `-H "X-Tenant-Id: tenantA"`
- To override upstream auth per request, include `_upstream_user` and `_upstream_pass` in the JSON body.

### Health

```bash
curl -s http://localhost:8080/health
```

---

### /v1/search/vector (Vector Search)

- Postgres
```bash
curl -s -X POST http://localhost:8080/v1/search/vector \
  -H "Content-Type: application/json" \
  -d '{
    "query": "contract termination clause",
    "top_k": 5,
    "backend": "postgres"
  }'
```

- Oracle
```bash
curl -s -X POST http://localhost:8080/v1/search/vector \
  -H "Content-Type: application/json" \
  -d '{
    "query": "privacy act exemptions",
    "top_k": 5,
    "backend": "oracle"
  }'
```

- OpenSearch (with upstream auth override)
```bash
curl -s -X POST http://localhost:8080/v1/search/vector \
  -H "Content-Type: application/json" \
  -d '{
    "query": "equitable estoppel",
    "top_k": 5,
    "backend": "opensearch",
    "_upstream_user": "legal_api",
    "_upstream_pass": "letmein"
  }'
```

---

### /v1/search/hybrid (Hybrid Vector + Lexical)

- Postgres
```bash
curl -s -X POST http://localhost:8080/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "misleading and deceptive conduct",
    "top_k": 8,
    "alpha": 0.5,
    "backend": "postgres"
  }'
```

- Oracle
```bash
curl -s -X POST http://localhost:8080/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "spam act penalties",
    "top_k": 8,
    "alpha": 0.5,
    "backend": "oracle"
  }'
```

- OpenSearch (with upstream auth override)
```bash
curl -s -X POST http://localhost:8080/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "email consent requirements",
    "top_k": 10,
    "alpha": 0.6,
    "backend": "opensearch",
    "_upstream_user": "legal_api",
    "_upstream_pass": "letmein"
  }'
```

---

### /v1/search/fts (Full Text Search)

- Postgres
```bash
curl -s -X POST http://localhost:8080/v1/search/fts \
  -H "Content-Type: application/json" \
  -d '{
    "query": "law enforcement agency",
    "top_k": 10,
    "mode": "both",
    "backend": "postgres"
  }'
```

- Oracle
```bash
curl -s -X POST http://localhost:8080/v1/search/fts \
  -H "Content-Type: application/json" \
  -d '{
    "query": "affirmative consent",
    "top_k": 10,
    "mode": "both",
    "backend": "oracle"
  }'
```

- OpenSearch
```bash
curl -s -X POST http://localhost:8080/v1/search/fts \
  -H "Content-Type: application/json" \
  -d '{
    "query": "telecommunications regulation",
    "top_k": 10,
    "mode": "both",
    "backend": "opensearch"
  }'
```

---

### /v1/search/rag (RAG – Retrieval-Augmented Generation)

Below are examples covering all combinations of vector backend × LLM provider.

- Backend: Postgres, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "ollama",
    "model": "llama3",
    "question": "Summarize penalties under the Spam Act",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: Postgres, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "question": "Provide recent judgments on misleading conduct",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: Postgres, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "question": "List key factors in consent under APP",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: Oracle, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "ollama",
    "model": "llama3",
    "question": "Explain cross-border disclosure requirements",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: Oracle, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "question": "List mandatory reportable data breaches",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: Oracle, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "question": "Provide summary of APP 7 direct marketing",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: OpenSearch, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "ollama",
    "model": "llama3",
    "question": "What is an eligible data breach?",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: OpenSearch, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "question": "Summarize obligations under APP 10 and 11",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

- Backend: OpenSearch, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "question": "Provide a summary of consent requirements under APP",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 1024
  }'
```

---

### /v1/chat/conversation (Conversational – RAG per turn)

The following examples cover all combinations of vector backend × LLM provider.

- Backend: Postgres, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "ollama",
    "model": "llama3",
    "message": "What is a Notifiable Data Breach?",
    "top_k": 10
  }'
```

- Backend: Postgres, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "message": "Explain consent vs implied consent under APP.",
    "top_k": 10
  }'
```

- Backend: Postgres, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "message": "Provide case examples on misleading conduct.",
    "top_k": 10
  }'
```

- Backend: Oracle, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "ollama",
    "model": "llama3",
    "message": "Give a brief on APP 8 cross-border disclosure.",
    "top_k": 10
  }'
```

- Backend: Oracle, LLM: OCI GenAI (with upstream auth override)
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "message": "Which APPs cover direct marketing?",
    "top_k": 10,
    "_upstream_user": "cogneo_api",
    "_upstream_pass": "letmein"
  }'
```

- Backend: Oracle, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "message": "Summarize OAIC guidance on consent.",
    "top_k": 10
  }'
```

- Backend: OpenSearch, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "ollama",
    "model": "llama3",
    "message": "Outline exemptions in Australian Privacy Principles.",
    "top_k": 10
  }'
```

- Backend: OpenSearch, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "message": "Explain obligations under APP 10 and 11.",
    "top_k": 10
  }'
```

- Backend: OpenSearch, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/chat/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "message": "Provide case references on cross-border disclosure.",
    "top_k": 10
  }'
```

---

### /v1/chat/agentic (Agentic / Chain-of-Thought)

Below are examples covering all combinations of vector backend × LLM provider.

- Backend: Postgres, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "ollama",
    "model": "llama3",
    "message": "Explain implied consent with legal citations.",
    "top_k": 10
  }'
```

- Backend: Postgres, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "message": "Explain mandatory breach notification thresholds.",
    "top_k": 10
  }'
```

- Backend: Postgres, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "postgres",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "message": "Summarize APP 11 security requirements with citations.",
    "top_k": 10
  }'
```

- Backend: Oracle, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "ollama",
    "model": "llama3",
    "message": "Provide legal basis for cross-border disclosure exceptions.",
    "top_k": 10
  }'
```

- Backend: Oracle, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "message": "Outline APP 7 with sources.",
    "top_k": 10
  }'
```

- Backend: Oracle, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "oracle",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "message": "Cite examples of implied consent in practice.",
    "top_k": 10
  }'
```

- Backend: OpenSearch, LLM: Ollama
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "ollama",
    "model": "llama3",
    "message": "Explain data minimization principles with references.",
    "top_k": 10
  }'
```

- Backend: OpenSearch, LLM: OCI GenAI
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "oci_genai",
    "model": "ocid1.generativeaimodel.oc1..xxxxx",
    "message": "Discuss overseas recipient obligations with citations.",
    "top_k": 10
  }'
```

- Backend: OpenSearch, LLM: Bedrock
```bash
curl -s -X POST http://localhost:8080/v1/chat/agentic \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "opensearch",
    "llm_source": "bedrock",
    "model": "anthropic.claude-3-haiku-20240307-v1:0",
    "message": "Detail cross-border disclosure rules with citations.",
    "top_k": 10
  }'
```

---

## Response Caching (Valkey/Redis)

- Enable caching via `.env`:
  - `CACHE_ENABLE=1`
  - `CACHE_URL=redis://localhost:6379/0` or `rediss://hostname:port/0` (TLS)
  - `CACHE_TLS_VERIFY=1` for production; set `0` only for testing.
  - `CACHE_TTL=60` (seconds)
- Cached endpoints:
  - `/v1/search/vector`, `/v1/search/hybrid`, `/v1/search/fts`
  - `/v1/search/rag` (best-effort; key includes full body)
  - `/v1/chat/conversation`, `/v1/chat/agentic` (heuristic key using message/model/llm_source/top_k)
- Cache keys are namespaced by endpoint and backend with SHA256 of the normalized JSON body.

---

## Production Notes

- Run multiple Router replicas behind a Load Balancer or Ingress.
- Use `TENANCY_ENABLE=1` for multi-tenant scenarios; keep per-tenant routing and secrets in `tenants.yaml` (or wire to a secure config service).
- Set `CACHE_TLS_VERIFY=1` when using `rediss://` in production.
- Add rate limiting/quotas (Redis token-bucket) and circuit breakers with retry/backoff policies per upstream as needed.

---

## Notes

- Replace model identifiers with ones available in your environment (e.g., Ollama model tags, OCI model OCIDs, Bedrock model IDs).
- When overriding upstream auth per request, the `_upstream_user` and `_upstream_pass` fields are stripped from the forwarded payload and used only for upstream authentication.
