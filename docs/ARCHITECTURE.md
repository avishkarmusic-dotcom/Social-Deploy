# Architecture

## Principle

Ingestion is dumb, intelligence is separate, and the read model is fast.

Fourteen channel APIs disagree about almost everything: pagination, identity,
edit semantics, rate limits, what a "conversation" even is. If those differences
reach the UI, the UI becomes fourteen UIs. So the boundary is drawn early —
adapters normalise into `(thread, message, contact)` and nothing downstream
knows which provider a row came from.

```
 provider webhooks ─┐
 polling workers  ──┤→ adapters → normalise → messages/threads (Postgres)
                    │                              │
                    │                              ├→ arq: classify → thread_intelligence
                    │                              ├→ arq: embed    → pgvector
                    │                              └→ automations engine
                    │
 Redis Streams ─────┴→ WebSocket fanout → the open browser tab
```

## Why AI output lives in its own table

`thread_intelligence` is append-only, keyed by `(thread_id, prompt_version)`.
A prompt or model change re-runs into new rows; the old scores stay auditable.
Nothing the model produces ever overwrites something a human or a provider sent.
That is what makes "why is this scored 88?" answerable a year later.

## Why a model router instead of one SDK

The workloads are not alike:

| Job | Volume/day | Needs | Route |
|---|---|---|---|
| Classify inbound | ~4,000 | speed, cost | Groq → Gemini Flash → Haiku → Ollama |
| Summarise thread | ~800 | brevity | Haiku → Flash |
| Draft a reply | ~120 | voice, judgement | Sonnet → GPT |
| Assistant queries | ~60 | tool use | Sonnet → GPT |

Each task has an ordered fallback chain; a provider outage degrades quality
rather than the product. Ollama sits at the end of the cheap chains so a
self-hosted or air-gapped deployment still classifies.

## Ingestion

- **Push where it exists**: Gmail via Pub/Sub, Meta and Slack via webhooks.
  Signatures verified, payload enqueued, HTTP 200 in under 50 ms.
- **Poll where it doesn't**: LinkedIn, X, Google Business. Adaptive interval per
  account, backed off on 429, cursor persisted in `channel_accounts.sync_cursor`.
- **Exactly once, effectively**: `UNIQUE (thread_id, external_id)` plus an
  idempotency key on the job. Providers replay; the database refuses duplicates.

## Contact resolution

Identity across channels is the hard part of a personal CRM. Resolution runs in
order: exact email → verified handle in `contact_identities` → normalised name
plus company with a confidence threshold. Below the threshold the system creates
a separate contact rather than guessing — a wrong merge is much more expensive
to undo than a duplicate.

## Scoring

`opportunity_score` is a model output, then adjusted by signals the model can't
see: is this contact already a paying client, has this sender ever converted,
does the workspace historically reply to this category within an hour. The
adjustment is a small, explainable delta stored alongside the raw score, so the
UI can say "88, raised from 74 because you've closed two deals from this domain."

## Realtime

Workers publish to a Redis Stream per workspace. The WebSocket gateway holds one
consumer group per connected tab and pushes deltas (`thread.created`,
`thread.scored`, `post.published`). The client applies them to a normalised
cache; there is no polling in the UI.

## Multi-tenancy

Every tenant table has `workspace_id` with row-level security. The request
middleware opens a transaction and sets `app.workspace_id` from the verified
session before any query runs. A forgotten filter returns zero rows instead of
someone else's inbox.

## Scale notes

- `messages` is partitioned monthly once a workspace passes ~5M rows; the inbox
  only ever reads recent partitions.
- HNSW index on embeddings for semantic search; full-text `tsvector` for exact.
  Global search queries both and merges by reciprocal rank fusion.
- Classification cost is bounded by a per-workspace daily token budget held in
  Redis. Over budget, threads queue for the nightly batch instead of realtime.
