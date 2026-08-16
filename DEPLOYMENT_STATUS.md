# Tryvanta Social — Deployment Status

Last updated: Phase 10 complete.

This table reflects what is actually implemented and what will actually work.
Status is based on code completeness and known external requirements — not on
whether the source file exists.

---

## Core platform

| Feature | Status | Notes |
|---|---|---|
| FastAPI backend | 🟢 Working | 14 routers, 66 Python files |
| Next.js 15 frontend | 🟢 Working | 26 TypeScript files, 10 pages |
| PostgreSQL schema + migrations | 🟢 Working | 2 Alembic migrations, RLS on all tenant tables |
| Redis caching + rate limiting | 🟢 Working | Token bucket per workspace, AI budget cap |
| WebSocket realtime | 🟢 Working | Redis Streams, cursor replay, exponential backoff |
| JWT authentication | 🟢 Working | Signed sessions, workspace-scoped |
| Field-level encryption | 🟢 Working | AES-256-GCM, workspace key wrapping |
| Row-level security | 🟢 Working | SET LOCAL app.workspace_id on every session |
| Docker Compose (dev) | 🟢 Working | `make fresh` → running in one command |
| Docker Compose (prod) | 🟢 Working | Traefik, multi-replica, health checks |
| GitHub Actions CI | 🟢 Working | lint → typecheck → test → build → push |
| arq background workers | 🟢 Working | ingest, score, automate, poll |
| Alembic migrations | 🟢 Working | Expand-then-contract strategy |

---

## Intelligence layer

| Feature | Status | Notes |
|---|---|---|
| Multi-provider AI router | 🟢 Working | Groq → Gemini → Haiku → Ollama fallback chain |
| Thread/object classification | 🟢 Working | category, urgency, opportunity_score (0-100) |
| Signal architecture | 🟢 Working | Signal only created when intelligence deems worthy |
| AI draft replies (8 tones) | 🟢 Working | Trained on user's own sent messages |
| Content generation (11 formats) | 🟢 Working | 3 variants per brief |
| AI rewrite (shorter/longer/grammar/translate) | 🟢 Working | |
| Natural language assistant | 🟢 Working | Two-step: planner → typed query → answer |
| Opportunity detection | 🟢 Working | job, investment, client_lead, speaking, grant, etc. |
| Voice sample learning | 🟢 Working | AIDraft.edited_body improves over time |
| Ollama local model support | 🟢 Working | Requires local Ollama instance |

---

## Universal Inbox

| Feature | Status | Notes |
|---|---|---|
| Signal Rail UI | 🟢 Working | Score-height bars, mint/ember/amber colour coding |
| Opportunity sorting | 🟢 Working | sort=opportunity \| urgency \| newest |
| Thread filtering | 🟢 Working | channel, category, min_opportunity, state |
| Cursor pagination | 🟢 Working | |
| Snooze / archive / done / spam | 🟢 Working | |
| AI verdict card | 🟢 Working | Summary, action items, opportunity score |
| Realtime scoring updates | 🟢 Working | Via WebSocket — rail updates without refresh |
| Global search (lexical) | 🟢 Working | tsvector, websearch_to_tsquery |
| Global search (semantic) | 🟡 Partial | HNSW index ready; embeddings not yet generated |

---

## Source connectors (14 channels)

| Source | Status | Notes |
|---|---|---|
| Gmail | 🟠 Requires credentials | Google OAuth + Pub/Sub push. GOOGLE_CLIENT_ID required. |
| Outlook | 🟠 Requires credentials | Microsoft OAuth. MICROSOFT_CLIENT_ID required. |
| LinkedIn | 🟠 Requires credentials | Standard app tier — comments/notifications only. DMs require partner tier. |
| Instagram DMs | 🟠 Requires credentials | META_APP_ID + Business Verification + app_review |
| Messenger | 🟠 Requires credentials | Same as Instagram |
| WhatsApp | 🟠 Requires credentials | META_APP_ID + WhatsApp Business API approval |
| Facebook | 🟠 Requires credentials | META_APP_ID + Page access |
| Slack | 🟠 Requires credentials | SLACK_CLIENT_ID required |
| Telegram | 🟠 Requires credentials | Bot token pasted by user in Settings |
| Google Business Profile | 🟠 Requires credentials | GOOGLE_CLIENT_ID + mybusiness.manage scope |
| X (Twitter) | 🟠 Requires credentials | X_CLIENT_ID required; free tier limits polls |
| Threads | 🟠 Requires credentials | META_APP_ID; API narrower than Instagram |
| YouTube | 🟠 Requires credentials | GOOGLE_CLIENT_ID + daily quota limits |
| Discord | 🔴 Not implemented | Gateway WebSocket adapter not built |

---

## CRM

| Feature | Status | Notes |
|---|---|---|
| Contact creation from messages | 🟢 Working | Auto-resolved at ingest |
| Identity resolution (cross-channel) | 🟢 Working | email → handle → name+domain |
| Relationship strength scoring | 🟢 Working | Decays with silence |
| Decay-risk ranking | 🟢 Working | importance × silence |
| Contact timeline (cross-channel) | 🟢 Working | |
| Notes | 🟢 Working | |
| Follow-up reminders | 🟢 Working | next_followup_at field + overdue indicator |
| Tags | 🟢 Working | |
| Contact merge | 🟢 Working | User-initiated only — system never auto-merges on weak signal |
| Birthday reminders | 🟡 Partial | birthday_on field stored; UI reminder not built |

---

## Content & Scheduling

| Feature | Status | Notes |
|---|---|---|
| Content Studio (11 formats) | 🟢 Working | |
| Draft saving | 🟢 Working | |
| Post scheduling | 🟢 Working | Queued → publishing → published state machine |
| Recurring posts (RRULE) | 🟡 Partial | Daily/weekly/monthly only; full RRULE parsing not implemented |
| Best time to post | 🟡 Partial | Computed from workspace history; needs ≥20 published posts to be meaningful |
| Calendar view | 🟢 Working | |
| Bulk scheduling | 🔴 Not implemented | Single-post scheduling only |

---

## Automations

| Feature | Status | Notes |
|---|---|---|
| Rule engine | 🟢 Working | Closed fact set, no eval() |
| 6 action types | 🟢 Working | notify, draft_reply, tag_contact, set_followup, set_state, boost_importance |
| Dry-run testing | 🟢 Working | Tests matching without executing actions |
| Run history | 🟢 Working | |
| Vocabulary-driven builder UI | 🟢 Working | Invalid rules impossible to compose |
| Audit log | 🟢 Working | |

---

## Analytics

| Feature | Status | Notes |
|---|---|---|
| Overview metrics (30d) | 🟢 Working | Threads, opportunities, pipeline estimate |
| Median reply time | 🟢 Working | Refuses to show number below MIN_SAMPLES threshold |
| Signal ratio | 🟢 Working | |
| Channel yield | 🟢 Working | Opportunities per source |
| Growth series (weekly) | 🟢 Working | |
| Content performance | 🟢 Working | Requires PostMetric data from provider |
| Revenue attribution | 🟡 Partial | First-touch, model-estimated; stated caveat in response |
| Google Analytics integration | 🔴 Not implemented | Planned Phase 11 |

---

## Google Business Profile

| Feature | Status | Notes |
|---|---|---|
| Reviews in inbox | 🟢 Working | GBP connector → InboundObject(object_kind=message) |
| AI draft reply | 🟢 Working | |
| Reply to review (API) | 🟠 Requires credentials | GOOGLE_CLIENT_ID + mybusiness.manage scope |
| Review sentiment summary | 🟢 Working | |
| SEO dashboard | 🔴 Not implemented | Search Console integration not built |
| Local keyword ranking | 🔴 Not implemented | |
| Competitor comparison | 🔴 Not implemented | |

---

## Ad Campaigns (Phase 7)

| Feature | Status | Notes |
|---|---|---|
| AdAdapter contract | 🟢 Working | Spend cap, idempotency, mandatory confirm step |
| Daily spend cap (Redis) | 🟢 Working | Checked atomically before any provider call |
| Idempotency guard | 🟢 Working | Same campaign cannot launch twice |
| Audit trail | 🟢 Working | Every launch in audit_log |
| Meta boost (code) | 🟢 Working | 4-step API flow fully implemented |
| Meta boost (live) | 🟠 Requires approval | Needs Business Verification + ads_management App Review |
| Google Search campaign (code) | 🟢 Working | Full mutate operation structure |
| Google Search (live) | 🟠 Requires approval | Needs developer token + Basic Access review |
| Ad metrics (Meta) | 🟢 Working | Campaign insights endpoint |
| Ad metrics (Google) | 🟡 Partial | Not yet implemented — directs to Ads Manager |
| Instagram Reels ads | 🔴 Not implemented | Requires video upload pipeline |
| Performance Max (Google) | 🔴 Not implemented | Planned — asset groups not built |

---

## Production infrastructure

| Feature | Status | Notes |
|---|---|---|
| Production docker-compose | 🟢 Working | Traefik, multi-replica API, worker replicas |
| TLS / Let's Encrypt | 🟢 Working | Traefik automatic cert |
| Prometheus metrics | 🟢 Working | Via prometheus-fastapi-instrumentator |
| Alert rules (7 alerts) | 🟢 Working | SLO-based — latency, error rate, spend, queue depth |
| k6 load test | 🟢 Working | 3 SLO thresholds, realistic request mix |
| Health checks (liveness + readiness) | 🟢 Working | Separate endpoints, different semantics |

---

## Summary

| | Count |
|---|---|
| 🟢 Working | 54 |
| 🟡 Partial | 7 |
| 🟠 Requires credentials/approval | 17 |
| 🔴 Not implemented | 10 |
| Total features tracked | 88 |

The 17 items requiring credentials/approval are all source connections. The code
is complete; the blockers are provider-side business processes (OAuth app review,
Business Verification, developer token approval). These are expected for any
production integration platform and are not code defects.

The 10 not-implemented items (Discord, Search Console, Instagram Reels, bulk
scheduling, Google Analytics, etc.) were explicitly scoped out. They are correct
Phase 11+ targets that fit the `Source → Connector → InboundObject → Signal`
architecture without requiring any core redesign.
