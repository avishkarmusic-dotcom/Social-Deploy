# Phase 3 — the floor

The phase where nothing new appears on screen and the repo starts working.

## What landed

| File | What it carries |
|---|---|
| `app/models.py` | 18 tables as ORM models, with the behaviour that belongs to a row |
| `core/db.py` | Session factory + `tenant_session` (sets `app.workspace_id` for RLS) |
| `core/deps.py` | Auth, tenancy, per-workspace rate limits, audit helper |
| `core/errors.py` | Error taxonomy where every error carries a `fix` |
| `core/config.py` | Settings that **refuse to boot production** on a placeholder secret |
| `services/automations.py` | Rules-as-data engine — no expression evaluator anywhere |
| `services/realtime.py` | Redis Streams fan-out with replay |
| `routers/health.py`, `ws.py` | Liveness/readiness, capability report, WebSocket gateway |
| `alembic/` | Migrations, with a hand-written revision 0001 |
| `app/seed.py` | 8 threads across 6 channels, spanning the full score range |
| `tests/` | conftest with transaction rollback + 25 new tests |

## Run it

```bash
cp .env.example .env
make fresh          # up → migrate → seed
```

## Three decisions worth your review

**1. Encrypted bodies and full-text search are in tension, and I picked a side.**

The original schema had `search_tsv` as a generated column over `body_text`.
That cannot work once bodies are ciphertext — Postgres has nothing to tokenise.
The options were: give up field-level encryption, give up Postgres FTS, or
compute the tsvector in the app from plaintext before sealing.

I took the third. The honest cost, now written into the schema comment: **the
search index leaks vocabulary.** Someone with database access can see which
words appear in a workspace's messages, even though they can't read a single
message. For an inbox product that tradeoff is right — search is the feature —
but it's a real one, and if you ever sell to a customer who asks "can your DBAs
read my mail", the answer is "no, but they can see your word list."

**2. Automation rules are data, never code.**

A trigger is an event name plus `(field, op, value)` comparisons against a
whitelisted fact dictionary. There is no `eval`, no expression parser, no
sandbox — because a sandbox is a thing you get wrong eventually, and a
whitelist is a thing you get wrong once at review time. Unknown field or
unknown action fails at **save** time with a message naming what's available.
Missing facts fail **closed**: a rule never fires on data it couldn't see.

**3. Config refuses to start rather than warn.**

`ENVIRONMENT=production` with `APP_SECRET=change-me` raises at import. A
warning in a log nobody reads is how a placeholder encryption key ends up in
production for four months.

## What Phase 3 deliberately did not do

Seven routers (`ai`, `analytics`, `automations`, `channels`, `content`, `crm`,
`search`) are registered and return `{"status": "phase_4"}`. They exist now so
the route table and OpenAPI schema are stable — the generated TypeScript client
in Phase 5 can be built against a shape that won't move.

## Verified

- Every internal import resolves to a module that exists
- Every imported *name* exists in the module it's imported from
- All 36 Python files parse
- `schema.sql` reconciled against the ORM (added `wrapped_key`,
  `ai_spend_today_usd`, `last_error`, `reply_ref`, `citext`; renamed token and
  body columns to their `_enc` forms)

Not yet verified: the container has no network here, so `pip install` and a live
`pytest` run happen on your machine. Expect the first `make fresh` to surface a
version pin or two.
