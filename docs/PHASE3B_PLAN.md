# Phase 3b Migration Plan
## Old → New data model, affected files, strategy, steps, tests

---

## Semantic decisions

**`Signal`** means something the system has scored and determined requires your attention.
Not every object entering the system is a Signal. A GitHub commit is an inbound object.
A GitHub PR review request **from a key customer** is a Signal. An investor email is a Signal.
A GA4 weekly report is an inbound object. A GA4 conversion anomaly is a Signal.

Communications (email, DMs, reviews) are Signals by default, because a person chose to
contact you and that always requires a decision. Non-communication objects become Signals
only when intelligence decides they are above the attention threshold.

This means `Signal` replaces `ThreadIntelligence` — it is the **scored, attention-requiring
verdict** on an inbound object. Not every `InboundObject` has one.

---

## Naming map

| Old | New | Reason |
|---|---|---|
| `ChannelKind` | `SourceKind` (TEXT, not ENUM) | "Channel" implies messaging; "source" is agnostic |
| `ChannelAccount` | `SourceAccount` | Same reason |
| `ChannelAdapter` | `Connector` | Same reason |
| `NormalizedThread` | `NormalizedObject` | A GitHub PR is not a thread |
| `NormalizedMessage` | `NormalizedPayload` | A commit diff is not a message |
| `Thread` | `InboundObject` | More honest about what it contains |
| `Message` | `InboundPayload` | Individual items within an object |
| `ThreadIntelligence` | `Signal` | This IS the signal; the thread was just the container |
| `thread_id` FK in runs/drafts | `object_id` | No FK (objects live in one table) |

**Unchanged:** `User`, `Workspace`, `WorkspaceMember`, `Contact`, `ContactIdentity` (kind column widens to TEXT), `ContentPiece`, `ScheduledPost`, `PostMetric`, `Review`, `Automation`, `AutomationRun`, `AuditLog`, `AIDraft`

---

## Schema changes

### `source_accounts` (was `channel_accounts`)
- Rename table
- `kind` column: `channel_kind` ENUM → `TEXT` with CHECK constraint
- All other columns identical

### `inbound_objects` (was `threads`)
- Rename table
- Add `object_kind TEXT NOT NULL DEFAULT 'message'` CHECK IN (message, event, work_item, document, metric, alert)
- Add `payload JSONB NOT NULL DEFAULT '{}'` — structured data (event times, PR status, etc.)
- Rename `last_message_at` → `last_activity_at`
- `is_unread` stays but defaults to FALSE for non-communication objects
- `account_id` FK → `source_account_id`

### `inbound_payloads` (was `messages`)
- Rename table
- `direction` TEXT becomes nullable (null = not applicable for non-communication)
- `body_enc` becomes nullable (null for pure-structured payloads)
- `thread_id` FK → `object_id`
- Add `payload JSONB NOT NULL DEFAULT '{}'` for structured data

### `signals` (was `thread_intelligence`)
- Rename table
- `thread_id` FK → `object_id`
- Rename `opportunity_score` → kept as-is (semantically valid for any object type)
- Add `is_signal BOOLEAN NOT NULL DEFAULT TRUE` — explicit: this record IS a Signal
- Add `signal_threshold` SMALLINT — the score at which intelligence decided this warrants attention

### `contact_identities`
- `kind` column: `channel_kind` ENUM → `source_kind TEXT`

### `automation_runs`
- `thread_id` FK → `object_id UUID` (no FK — generic reference)
- Add `object_kind TEXT`

### DROP
- Postgres ENUM type `channel_kind` (after all columns migrated)

---

## Affected files

### Must change (model references)
1. `app/channels/base.py` → `app/connectors/base.py`
2. `app/channels/registry.py` → `app/connectors/registry.py`
3. `app/channels/{gmail,meta,slack,gbp,polling,microsoft,telegram}.py` → `app/connectors/`
4. `app/models.py`
5. `app/services/ingestion.py`
6. `app/services/identity.py`
7. `app/services/intelligence.py`
8. `app/services/automations.py`
9. `app/services/assistant.py`
10. `app/services/search.py`
11. `app/workers/ingest.py`
12. `app/routers/inbox.py`
13. `app/routers/channels.py`
14. `app/routers/crm.py`
15. `app/routers/automations.py`
16. `app/routers/health.py`
17. `app/routers/webhooks.py`
18. `app/seed.py`
19. `schema.sql`

### Stay unchanged (semantics unaffected)
- `app/core/config.py` — no model references
- `app/core/db.py` — no model references
- `app/core/deps.py` — references `workspace_key`, `AIDraft`, `WorkspaceMember` — unchanged
- `app/core/crypto.py` — no model references
- `app/core/ratelimit.py` — no model references
- `app/core/errors.py` — no model references
- `app/services/ai_router.py` — no model references
- `app/services/publishing.py` — references `ScheduledPost`, `ChannelAccount`; update account ref
- `app/services/realtime.py` — no model references
- `app/services/analytics.py` — references `Thread`, `ThreadIntelligence`; update
- `app/routers/ai.py` — no direct model references
- `app/routers/content.py` — references `ChannelAccount`; update to `SourceAccount`
- `app/routers/health.py` — `load_all()` call; update import path

### Tests
- `tests/test_adapters.py` — imports `NormalizedThread`, `NormalizedMessage`; update to new names
- `tests/test_identity.py` — uses `ChannelKind`; update to string
- `tests/test_intelligence.py` — semantically unchanged; update imports
- `tests/test_core.py` — no model references; unchanged
- `tests/conftest.py` — imports `SourceAccount` (was `ChannelAccount`); update
- New: `tests/test_migration.py` — proves no regression

---

## Compatibility strategy

1. The 14 communication adapters produce `NormalizedObject` with `object_kind="message"`.
   The ingestion service writes to `InboundObject` + `InboundPayload`. Behaviour is identical.
2. The intelligence service reads `InboundObject` and creates `Signal` rows. For communications,
   every inbound object creates a Signal (existing behaviour). For non-communications, the
   connector sets `produces_signals=False` and the intelligence service decides.
3. The inbox router queries `InboundObject JOIN Signal`. Same SQL result shape.
4. All tests that were passing continue to pass. New tests are additive.
5. The Alembic migration uses `RENAME TABLE`, `ALTER COLUMN ... USING`, no data loss.

---

## Implementation steps

1. Write new `app/connectors/` package (base, registry, move adapters)
2. Rewrite `app/models.py` with new table names and columns
3. Write `alembic/versions/0002_source_signal.py`
4. Update `schema.sql` (canonical DDL, kept in sync)
5. Update services: ingestion, identity, intelligence, automations, assistant, search, analytics, publishing
6. Update routers: inbox, channels→sources, crm, automations, content, health, webhooks
7. Update worker
8. Update seed
9. Update and extend tests
10. Static verification (import resolution, balanced braces)

---

## Definition of done

- [ ] `docker compose up && alembic upgrade head` succeeds on a fresh database
- [ ] All 14 communication adapters produce `NormalizedObject` without modification to their logic
- [ ] `pytest -q` passes with zero failures
- [ ] `test_migration.py` specifically proves: Signal only created when intelligence runs; InboundObject created for all adapters; source_kind is plain TEXT; contact identity resolves with string source_kind
- [ ] No import of the old name `Thread`, `Message`, `ThreadIntelligence`, `ChannelKind`, `ChannelAccount`, `NormalizedThread`, `NormalizedMessage` anywhere in the production codebase
