<div align="center">

# Tryvanta Social

**One inbox. One AI. Zero missed opportunities.**

An AI Social Operating System — every message from every platform in one place,
ranked by what it is actually worth.

</div>

---

## Quick start

```bash
git clone https://github.com/<you>/tryvanta-social
cd tryvanta-social
cp .env.example .env              # fill in the required values (see below)
make fresh                        # boot → migrate → seed demo data
```

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| API health | http://localhost:8000/healthz |
| Metrics | http://localhost:8000/metrics |

Demo credentials: `demo@tryvanta.social` / session via magic link

---

## What this is

Tryvanta Social is not a social media scheduler. It is an AI operating layer:

- **Universal Inbox** — Gmail, Outlook, LinkedIn, Instagram, WhatsApp, Telegram,
  Slack, Discord, Google Business, X, Threads, YouTube, Facebook, Messenger.
  Normalised into one thread model, sorted by opportunity score.
- **Signal Rail** — every thread has a vertical bar. The bar is the score.
  Scanning the inbox is scanning a bar chart you never have to read.
- **AI Reply** — eight tones, trained on the messages you actually sent.
- **Content Studio** — eleven formats, three variants per brief.
- **Personal CRM** — relationship strength decays when you go quiet.
- **Automations** — rules engine with dry-run testing and audit trail.
- **Ad Campaigns** — Meta boost and Google Search, with mandatory confirm step
  and daily spend cap enforced before any provider call.

---

## Project structure

```
tryvanta-social/
├── backend/
│   ├── app/
│   │   ├── ads/          AdAdapter contract, Meta and Google adapters
│   │   ├── connectors/   14 source adapters (Gmail, Slack, LinkedIn, …)
│   │   ├── core/         config, db, deps, crypto, ratelimit, errors
│   │   ├── models.py     ORM (InboundObject, Signal, SourceAccount, …)
│   │   ├── routers/      14 API routers
│   │   ├── services/     AI router, intelligence, ingestion, search, …
│   │   └── workers/      arq background jobs
│   ├── alembic/          migrations (0001 initial, 0002 Phase 3b)
│   ├── tests/            11 test files
│   ├── schema.sql        canonical DDL (reference; migrations are authoritative)
│   ├── requirements.txt
│   └── Dockerfile
├── web/
│   ├── app/
│   │   ├── (app)/        10 authenticated pages
│   │   ├── (auth)/       login
│   │   └── page.tsx      landing page
│   ├── components/       Shell, Inbox, Studio, CRM, Rules, Analytics
│   ├── lib/              typed API client, realtime hook, formatters
│   └── Dockerfile
├── infra/
│   ├── docker-compose.prod.yml
│   ├── k6/load_test.js
│   ├── prometheus.yml
│   └── alerts.yml
├── docs/                 Architecture, API reference, Deployment, Channels
├── .github/workflows/    ci.yml (lint → type-check → test → build → push)
├── docker-compose.yml    local development
├── .env.example
└── README.md
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in the values marked REQUIRED.

### Core (REQUIRED)

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `APP_SECRET` | JWT signing secret — `openssl rand -base64 32` |
| `DATA_ENCRYPTION_KEY` | Field-level encryption key — `openssl rand -base64 32` |

### AI providers (at least one REQUIRED)

| Variable | Notes |
|---|---|
| `ANTHROPIC_API_KEY` | Claude (recommended for drafting) |
| `OPENAI_API_KEY` | GPT-4.1 fallback |
| `GOOGLE_API_KEY` | Gemini Flash (cheapest classifier) |
| `GROQ_API_KEY` | Fastest classifier |
| `OLLAMA_BASE_URL` | Local models — `http://localhost:11434` |

The AI router degrades gracefully: add any subset and it routes accordingly.
With only `OLLAMA_BASE_URL`, the product runs fully offline (classification only).

### Source OAuth (all optional — connect sources via Settings)

| Variable | Source |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Gmail, YouTube, Google Business |
| `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` | Outlook |
| `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` | LinkedIn |
| `META_APP_ID` / `META_APP_SECRET` | Instagram, Messenger, WhatsApp, Facebook |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` | Slack |
| `X_CLIENT_ID` / `X_CLIENT_SECRET` | X (Twitter) |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram (bot token pasted in Settings) |

### Ad platforms (optional — Phase 7)

| Variable | Notes |
|---|---|
| `META_ADS_DEVELOPER_TOKEN` | Requires Business Verification + ads_management approval |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Requires Basic Access approval from Google |

---

## Database

```bash
# Apply migrations (also run by `make migrate`)
docker compose exec api alembic upgrade head

# Seed demo data (8 threads across 6 channels, 3 automation rules)
docker compose exec api python -m app.seed

# Undo Phase 3b migration (returns to Phase 3 schema)
docker compose exec api alembic downgrade 0001
```

Migration order: `0001_initial` → `0002_source_signal`

The schema uses:
- `pgcrypto` for UUID generation
- `pgvector` for semantic search embeddings
- `pg_trgm` for fuzzy contact name matching
- Row-level security on all tenant tables

---

## Development

```bash
# Start everything
make up              # docker compose up --build -d

# Run with live reload
docker compose exec api uvicorn app.main:app --reload
docker compose exec web npm run dev

# Tests
make test            # inside container
cd backend && pytest -q  # locally (needs DATABASE_URL and REDIS_URL)

# Linting / types
docker compose exec api ruff check app
docker compose exec api mypy app
cd web && npm run typecheck && npm run lint

# Load test (requires k6)
k6 run --env BASE=http://localhost:8000 --env TOKEN=<jwt> infra/k6/load_test.js
```

---

## Production deployment

See `docs/DEPLOYMENT.md` for the full guide.

Short version:

```bash
# 1. Set production secrets in secret manager (never in .env files)
# 2. Build and push images (CI does this automatically on main)
#    docker build -t ghcr.io/<org>/api:v1.0.0 ./backend
#    docker build -t ghcr.io/<org>/web:v1.0.0 ./web
# 3. Deploy
cp infra/docker-compose.prod.yml /srv/tryvanta/docker-compose.yml
VERSION=v1.0.0 DOMAIN=app.tryvanta.social docker compose up -d
# 4. Migrate (runs as a pre-deploy job, never at app start)
docker compose run --rm migrate
```

Production stack: Traefik (TLS) → Web (Next.js) + API (FastAPI × 2) + Workers (arq × 3)
→ PostgreSQL (HA) + Redis (AOF) + Prometheus + Grafana

---

## SLOs and monitoring

| Metric | Target | Alert |
|---|---|---|
| Inbox p95 latency | < 300ms | `InboxLatencyHigh` |
| Classification lag | < 60s | `ClassificationLag` |
| API error rate | < 2% | `APIErrorRateHigh` |
| AI spend/day | < $25 | `AISpendHigh` |
| Worker queue depth | < 500 | `WorkerQueueDeep` |

---

## Architecture notes

The data model is `Source → Connector → InboundObject → Signal → Action`.

- `InboundObject` is anything that entered the system (message, event, work item, doc, metric, alert)
- `Signal` is what the intelligence layer creates when it decides an object warrants attention
- Not every `InboundObject` becomes a `Signal`
- `source_kind` is a plain `TEXT` column — new sources add a string constant, never an `ALTER TYPE` migration
- All tenant tables have row-level security: a query that forgets `WHERE workspace_id` returns zero rows

See `docs/ARCHITECTURE.md` for the full design rationale.

---

## Licence

Proprietary — Tryvanta. All rights reserved.
