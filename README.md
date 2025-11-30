# CogNeo-Edge-Router

Edge Router (FastAPI) that fronts multiple CogNeo stacks and routes requests to a selected vector backend (Postgres/pgvector, Oracle 26ai, OpenSearch) and LLM provider (Ollama, OCI GenAI, AWS Bedrock) per-tenant or per-request.

Features
- Per-tenant routing policy: default backend + default LLM provider
- Request-level overrides: backend, llm_source, model, region
- Async HTTP proxy to upstream CogNeo stacks (keep-alive via httpx)
- Uniform REST API: /v1/search/* and /v1/chat/*
- Observability: healthcheck, Prometheus metrics
- Extensible to quotas/rate-limits and circuit breakers

Directory layout
.
├─ app/
│  ├─ main.py              # FastAPI app, endpoints and routing
│  ├─ config.py            # Pydantic Settings (env + defaults)
│  ├─ tenants.py           # Tenant config loader (YAML)
│  └─ types.py             # Pydantic models (request/response)
├─ tenants.example.yaml    # Example per-tenant routing config
├─ .env.example            # Example environment configuration
├─ requirements.txt
├─ Dockerfile
└─ README.md

Quick start (local)
1) Create and activate a venv (optional):
   python3 -m venv .venv
   source .venv/bin/activate

2) Install dependencies:
   pip install -r requirements.txt

3) Copy config templates:
   cp .env.example .env
   cp tenants.example.yaml tenants.yaml
   # Edit tenants.yaml to point to your upstream CogNeo stacks (base URLs and auth)

4) Run:
   uvicorn app.main:app --host 0.0.0.0 --port 8080

5) Test:
   curl -s http://localhost:8080/health
   curl -s -H "X-Tenant-Id: tenantA" -X POST http://localhost:8080/v1/search/hybrid -H "Content-Type: application/json" -d '{"query":"privacy act exemptions","top_k":5,"alpha":0.5}'

Environment (.env)
- ROUTER_REQUEST_TIMEOUT=30                 # request timeout (s)
- ROUTER_UPSTREAM_TIMEOUT=30               # upstream timeout (s)
- TENANTS_CONFIG=tenants.yaml              # path to tenants YAML file
- CORS_ENABLE=1                            # enable CORS
- CORS_ALLOW_ORIGINS=*                     # comma-separated origins
- METRICS_ENABLE=1                         # expose /metrics

Tenants config (tenants.yaml)
Example:
```yaml
tenants:
  tenantA:
    default_backend: opensearch            # postgres | oracle | opensearch
    default_llm: bedrock                   # ollama | oci_genai | bedrock
    upstreams:
      postgres_api: "http://pg-stack:8000"
      oracle_api: "http://ora-stack:8000"
      opensearch_api: "http://os-stack:8000"
    auth:
      user: "legal_api"
      pass: "letmein"
```

API (Router)
- Health:
  - GET /health -> { "ok": true }

- Metrics:
  - GET /metrics (if enabled)

- Search:
  - POST /v1/search/vector
  - POST /v1/search/hybrid
  - POST /v1/search/fts
    Request body (for hybrid):
    {
      "query": "text",
      "top_k": 8,
      "alpha": 0.5,
      "backend": "postgres|oracle|opensearch"   # optional override
    }

- RAG:
  - POST /v1/search/rag
    Pass-through payload to upstream /search/rag. You may add llm_source/model/region overrides.

- Chat:
  - POST /v1/chat/conversation
  - POST /v1/chat/agentic
    {
      "message": "What is ...",
      "backend": "opensearch",
      "llm_source": "bedrock",
      "model": "anthropic.claude-3-haiku-20240307-v1:0",
      "top_k": 10
    }

Headers
- X-Tenant-Id: tenant key to select routing policy.

Deployment
- Container:
  docker build -t cogneo-edge-router:latest .
  docker run --rm -p 8080:8080 --env-file .env -v $(pwd)/tenants.yaml:/app/tenants.yaml:ro cogneo-edge-router:latest

- K8s:
  - Run multiple replicas behind a LoadBalancer/Ingress.
  - Mount tenants.yaml via ConfigMap or secret; environment vars via ConfigMap/secret.
  - Enable readiness/liveness probes on /health.

Notes and roadmap
- Add per-tenant quotas/rate limits (Redis-based token bucket).
- Add circuit breakers with upstream retry/backoff policies.
- Optionally implement in-process retrieval/LLM calls for a single-hop architecture after stabilizing the Router.
