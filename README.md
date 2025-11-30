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
  - Description: Path to tenants YAML file (relative or absolute).
  - Values: file path (e.g., `tenants.yaml`, `/etc/router/tenants.yaml`).
  - Default: `tenants.yaml`
- TENANCY_ENABLE
  - Description: Enable multi-tenant routing by X-Tenant-Id.
  - Values: `0` = disabled (use `default` block; X-Tenant-Id not required), `1` = enabled (X-Tenant-Id header required).
  - Default: `0`
- CORS_ENABLE
  - Description: Enable CORS middleware.
  - Values: `0` = disabled, `1` = enabled.
  - Default: `1`
- CORS_ALLOW_ORIGINS
  - Description: Comma-separated allowed origins for CORS.
  - Values: `*` for all or list (e.g., `https://example.com,https://app.example.com`).
  - Default: `*`
- METRICS_ENABLE
  - Description: Expose Prometheus metrics endpoint `/metrics`.
  - Values: `0` = disabled, `1` = enabled.
  - Default: `1`
- CACHE_ENABLE
  - Description: Enable response caching via Valkey/Redis.
  - Values: `0` = disabled, `1` = enabled.
  - Default: `1`
- CACHE_TTL
  - Description: TTL (seconds) for cached responses.
  - Values: integer seconds (e.g., 60, 300, 600).
  - Default: `60`
- CACHE_URL
  - Description: Connection URL for Valkey/Redis.
  - Values: `redis://host:port/db` for plaintext or `rediss://host:port/db` for TLS (e.g., `redis://localhost:6379/0`, `rediss://cache.example.com:6380/0`).
  - Default: `redis://localhost:6379/0`
- CACHE_TLS_VERIFY
  - Description: TLS certificate verification for `rediss://`.
  - Values: `1` = verify certificates (recommended in production), `0` = skip verification (testing only).
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

### Search: Vector
Route to Postgres backend; override upstream auth.

```bash
curl -s -X POST http://localhost:8080/v1/search/vector \
  -H "Content-Type: application/json" \
  -d {
