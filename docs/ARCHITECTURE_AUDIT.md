# Architectural Audit — Phase 5 Review
## Principal Architect reviewing own work

**Date:** Before Phase 6 begins  
**Reviewer:** The engineer who wrote every line of this  
**Verdict:** There is real debt. It is fixable now. It will be surgery later.

---

## A. Is the core architecture provider-agnostic enough?

**Partially.** The right things are agnostic. The wrong things are not.

**What is genuinely agnostic and will not need redesign:**

- The workspace/tenant isolation layer (RLS, `workspace_id`, `wrapped_key`) — scales to any number of source types
- The AI router (`AIRouter`, fallback chains, task types) — takes a string prompt, returns a string; has no concept of "message"
- The intelligence scoring concept — a model that reads text and returns a score works on any text-bearing object
- The realtime event stream (Redis Streams, WebSocket gateway) — already emits generic `{event, data}` pairs
- The encryption/crypto layer — seals arbitrary bytes; not message-specific
- The rate limiting and budget tracking — provider-agnostic token buckets
- The automation rule engine **structure** — event names + fact dicts + action handlers is a good abstraction
- The RRF search fusion — algorithm is object-agnostic; the queries feeding it are not

**What is NOT agnostic and will hurt:**

- `ChannelKind` — a closed enum of 14 communication channels
- `NormalizedThread` / `NormalizedMessage` — messaging-only data shapes
- `Thread` / `Message` — ORM tables that embed messaging semantics
- `ContactIdentity.kind` typed as `ChannelKind`
- `facts_for(thread, key)` — signature and body assume a `Thread` with `messages`
- `AutomationRun.thread_id` — FK to `threads`, not to a generic object
- `QueryPlan` intents — `top_opportunities`, `urgent_threads`, `unanswered` are all inbox verbs
- `search` — queries `Thread` and `Message` tables only
- `PostMetric` — `impressions`, `engagements`, `clicks`, `follows` are social-only fields
- `ScheduledPost` → `ContentPiece` → `ChannelAccount` chain — assumes social publishing

---

## B. Integration-by-integration classification

### Communication (already committed)

| Integration | Status | Verdict |
|---|---|---|
| Gmail | 🟢 | Adapter written, works |
| WhatsApp | 🟢 | Adapter written, works |
| Telegram | 🟢 | Adapter written, works |
| Slack | 🟢 | Adapter written, works |
| LinkedIn | 🟢 | Adapter written (comment/notify tier) |
| X | 🟢 | Adapter written, works |
| Instagram | 🟢 | Adapter written, works |

### Work / Development

| Integration | Status | What it needs |
|---|---|---|
| **GitHub** | 🟡 | Issues, PRs, CI runs, commits are not messages. `direction` (inbound/outbound) is meaningless for a commit. `NormalizedThread` physically represents a GitHub issue if you squint — title=subject, comments=messages — but the semantic is wrong and `facts_for` can't extract `pr_status`, `ci_outcome`, `review_requested_from` from the current fact dict. Needs: `ObjectKind.WORK_ITEM`, new fact keys in the automation engine, and a wider assistant query intent. |
| **Google Calendar** | 🔴 | An event is not a thread. It has attendees (not a single author), a start/end time (not `sent_at`), a location, a recurring rule. `is_unread` is nonsensical. Storing a calendar event as a `NormalizedThread` with one `NormalizedMessage` is a lie that will generate bugs for years. The assistant can't answer "what's on my calendar Thursday?" with the current `QueryPlan` intents. Needs: `ObjectKind.EVENT`, a new `events` table or a generic `objects` table, and calendar-specific assistant intents. |
| **Google Docs** | 🔴 | A document is not a thread. It has a title, body, revision history, inline comments, collaborators. The current schema has nowhere to put revision history or collaborator lists. A comment on a Doc is a `NormalizedMessage` if you force it, but the parent is a document, not a conversation. Needs: `ObjectKind.DOCUMENT`. |
| **Notion** | 🔴 | Notion has pages, databases, database rows, and comments. Pages and database rows are structured documents/records, not messages. The `NormalizedThread` abstraction cannot represent a Notion database row with typed properties. Needs: `ObjectKind.DOCUMENT` + `ObjectKind.RECORD`. |
| **Lovable** | 🟡 | Lovable emits webhook events (build started, build succeeded, deployment live). These fit reasonably as `NormalizedThread` with one message each — but `direction` is meaningless and the automation facts (`ci_outcome`, `deploy_url`, `build_duration_s`) don't exist in the current `FACTS` set. Needs: new fact keys, not a schema redesign. Lower friction. |

### AI

| Integration | Status | What it needs |
|---|---|---|
| **Claude (external)** | 🟡 | The `AIRouter` already calls Anthropic. The gap is *bidirectional* AI integration: Claude initiating, Claude as a data source, or Claude-to-GENESIS pipelines. The current architecture has AI as a pure service (request → response). Making AI a *source* of events requires an `ObjectKind.AI_RESPONSE` concept. Manageable extension. |
| **ChatGPT** | 🟡 | Same as Claude. The router already supports OpenAI. The gap is the same: treating model responses as objects in the signal store rather than ephemeral request/response pairs. |
| **GENESIS** | 🟡 | GENESIS is Avishkar's own cognitive orchestration AI. It needs to be both a *consumer* of the intelligence layer (receiving scored signals) and a *producer* of signals (sending outputs back as objects). The current architecture has no concept of AI-to-AI communication channels. Needs: a `ConnectorKind.AI_AGENT` category and a protocol for GENESIS to push events in and pull decisions out. The adapter pattern fits if the contract is widened. Not a redesign — an honest extension. |

### Business / Intelligence

| Integration | Status | What it needs |
|---|---|---|
| **Google Analytics** | 🔴 | GA4 produces metric timeseries, dimension breakdowns, and anomaly alerts — none of which are messages or threads. `body_text` could hold a JSON dump of a report, but that's an abuse. The `Thread` model has no place for metric dimensions, period comparisons, or significance thresholds. Needs: `ObjectKind.METRIC` and a separate metrics store (or a generic `objects` table with a JSONB payload). |
| **Financial dashboards** | 🔴 | Same problem, sharper edge. Revenue figures, P&L lines, cash flow forecasts, transaction alerts — none of these are conversations. A transaction alert has a `severity`, `account`, `amount`, `delta`, `threshold`. None of these fields exist anywhere in the current schema. Needs `ObjectKind.ALERT` with typed payload. |
| **Google Business Profile** | 🟢 | Already built. The GBP adapter treats reviews as inbound threads. Works. |
| **Google Ads** | 🟡 | Phase 7 scope. A campaign is not a thread. `ScheduledPost` cannot represent a campaign with budget, targeting, bid strategy, and A/B variants. The `AdAdapter` contract I described for Phase 7 needs to be a separate abstraction, not an extension of `ChannelAdapter`. The spend cap, audit trail, and confirm step I described are all correct — but the data model needs a `campaigns` table, not a `scheduled_posts` row. Medium extension. |
| **Meta Ads** | 🟡 | Same as Google Ads. The "boost existing post" case (Phase 7) reuses an existing `ContentPiece`, which is clean. The full campaign case needs a separate model. |

---

## C. Hidden assumptions, identified precisely

### 1. `NormalizedMessage.direction: "inbound" | "outbound"` — **messaging-only**

A GitHub commit has no direction. A calendar event has no direction. A GA4 anomaly has no direction. Every non-communication source will either set this to a meaningless default or leave it blank, which is a silent corruption of a field that means something for the things it was designed for.

**Impact:** Medium. The field is on the transport model, not the stored model. But it shapes `facts_for` (`body = last.decrypt(key)` assumes a `Message`) and the UI transcript view.

### 2. `NormalizedThread.is_unread` — **messaging-only**

An unread calendar event? An unread GitHub commit? These are category errors. The concept of "unread" is a property of a communication, not an object.

**Impact:** Low in isolation. High when `Thread.is_unread` drives the unread count badge and the "unanswered" automation filter.

### 3. `ChannelKind` is a closed enum, and it's a Postgres ENUM type

This is the single most structurally expensive assumption. Adding `GITHUB`, `GOOGLE_CALENDAR`, `NOTION`, `GOOGLE_DOCS`, `GOOGLE_ANALYTICS` to a Postgres `ENUM` type requires `ALTER TYPE ... ADD VALUE`, which is a DDL migration. In a system with row-level security policies that reference this enum (the `channel_accounts` and `contact_identities` tables), every migration touches RLS. More importantly: the word **"channel"** is semantically wrong for a financial dashboard or a GitHub repository. The concept is "source of signals," not "communication channel."

**Impact:** High. Every new non-communication integration requires a migration AND a name that lies about what it is.

### 4. `ContactIdentity.kind: ChannelKind` — **CRM assumes people come from messages**

The CRM's identity resolution is built around the idea that every person arrives through a communication channel. GitHub users, Notion users, Google Calendar attendees — these are all people who may have identities in those systems. But `ContactIdentity` only knows how to store a `ChannelKind` + handle pair.

**Impact:** Medium. Adding `GITHUB` to `ChannelKind` makes GitHub users technically storable. But `identity.handle` for a GitHub user is a username, not a message thread participant. The semantic drift accumulates.

### 5. `facts_for(thread: Thread, key: bytes)` — **automations assume inbox events**

The function signature accepts a `Thread`. Its body decrypts the last message body, reads `thread.account.kind`, reads `thread.current_intel`. A GitHub PR has no `current_intel` yet (that's a new scoring run). A calendar event has no `last message`. A GA4 anomaly has no `contact`.

The available `FACTS` set (`channel`, `category`, `opportunity_score`, `urgency`, `sentiment`, `estimated_value_usd`, `language`, `sender`, `subject`, `body`, `is_unread`, `rating`, `contact_tags`) has zero vocabulary for: `pr_status`, `ci_outcome`, `event_start`, `event_attendees`, `metric_name`, `metric_delta`, `campaign_spend`, `document_owner`.

**Impact:** High. The automation engine is the product's most powerful feature for an AI operating layer. If it can only reason about inbox events, its value for the full ecosystem is cut by 80%.

### 6. `AutomationRun.thread_id` — FK to threads table

Automation runs are recorded with a reference to the thread that triggered them. For non-thread objects, this FK has nowhere to point. You'd either null it (losing provenance) or add more nullable FKs (one per object type, which is the anti-pattern that costs you dearly at object type 6).

**Impact:** Medium. Fixable with a generic `object_id: UUID` + `object_kind: str` pair, but that's a breaking schema change.

### 7. `QueryPlan` intents — assistant can only ask about inbox and CRM

Current intents: `top_opportunities`, `urgent_threads`, `unanswered`, `stale_contacts`, `by_category`, `by_channel`, `summary_of_day`, `unknown`.

There is no intent for: "what's on my calendar this week," "what PRs are waiting for my review," "how is my GA4 performing," "what's my ad spend today," "show me open Notion tasks."

The `fetch` function only queries `Thread`, `ThreadIntelligence`, and `Contact`. Adding a new intent requires modifying this function and the SQL it runs. That's manageable for 3 intents. For 20 intents across 15 object types, it becomes a maintenance problem.

**Impact:** High for the "personal AI operating layer" vision. The assistant is the primary interface for an operating layer. If it can only see the inbox, it's not an operating layer — it's an inbox with a chatbot.

### 8. `search` queries `Thread` and `Message` only

The search service runs `websearch_to_tsquery` against `messages.search_tsv` and cosine distance against `messages.embedding`. GitHub issues, Notion pages, Google Docs, calendar events — none of these are in `messages`. They'd be invisible to search.

**Impact:** High. Global search that can't find a PR you're waiting on or a Notion page you wrote last week isn't global search.

### 9. `PostMetric(impressions, engagements, clicks, follows)` — social-only fields

These four fields are correct for Instagram posts and LinkedIn updates. They are wrong for Google Ads (which has `conversions`, `cost`, `ctr`, `roas`) and meaningless for GitHub (which has `reviews`, `comments`, `ci_status`). Shoehorning ad metrics into `engagements` is the kind of technical debt that produces "engagement" meaning three different things in three different parts of the codebase.

**Impact:** Medium for now (Phases 1-6 don't need it). High if Phase 7 reuses `PostMetric` for ads.

### 10. `ScheduledPost → ContentPiece → ChannelAccount` — social publishing chain

This chain correctly models "post this piece of content to this social account at this time." It does not model "run this GitHub Action," "send this Google Docs invite," "trigger this Notion template," or "launch this ad campaign." Adding non-social scheduled objects means either extending `ScheduledPost` until it's incoherent, or creating separate scheduling models per object type.

**Impact:** Medium. The publishing scheduler is clean for its stated purpose. The problem is if "scheduler" becomes the answer to all time-based actions across the operating layer.

---

## D. Should the architecture be `Source → Connector → Normalized Event/Object → Intelligence Layer → Action Layer`?

**Yes. Unambiguously.**

Here is the exact reason, not a general one:

The current model is:
```
Channel (14 comm channels) → Message → Thread → ThreadIntelligence → Automation(thread)
```

The vision is:
```
Source (GitHub, Calendar, Notion, GA4, Ads, Gmail, ...) → ??? → Intelligence → Action
```

The `Thread + Message` model answered a specific question: "what are the messages in this conversation?" That is the right answer for Gmail, WhatsApp, and Slack. It is the wrong answer for GitHub, Google Calendar, Google Analytics, and Notion. Those aren't conversations. They're **objects** — a PR, an event, a metric, a page.

The correct abstraction is:

```
SourceKind          (open string enum, not closed)
    ↓
Connector           (replaces ChannelAdapter, same registry pattern, wider contract)
    ↓
NormalizedObject    (union: Message | Event | WorkItem | Document | Metric | Alert)
    ↓
Signal              (replaces Thread — one row per object instance, generic)
    ↓
SignalIntelligence  (replaces ThreadIntelligence — scores any Signal)
    ↓
Action Layer        (automation engine, but facts_for dispatches on object_kind)
```

**Why `Signal` is a better name than `Thread`:**

A `Signal` is "something that arrived from a source that may require attention." An email is a signal. A GitHub PR review request is a signal. A GA4 anomaly is a signal. A calendar invitation is a signal. A financial alert is a signal.

A `Thread` is specifically "a conversation between people." Only some signals are threads.

**What changes in the data model:**

The good news is this is an **expand-then-contract** migration, not a teardown:

```sql
-- Add alongside Thread, not replacing it
CREATE TABLE signals (
  id            UUID PRIMARY KEY,
  workspace_id  UUID NOT NULL,
  source_id     UUID NOT NULL REFERENCES source_accounts(id),
  object_kind   TEXT NOT NULL,  -- message | event | work_item | document | metric | alert
  external_id   TEXT NOT NULL,
  title         TEXT,           -- subject, PR title, event name, metric name
  body_enc      BYTEA,          -- encrypted text content where applicable
  payload       JSONB,          -- structured data that doesn't fit body (event times, PR status, etc.)
  actor_name    TEXT,           -- who originated this (sender, PR author, calendar organiser)
  actor_handle  TEXT,
  contact_id    UUID REFERENCES contacts(id),
  state         TEXT DEFAULT 'open',
  is_unread     BOOLEAN DEFAULT true,  -- kept but nullable/false for non-communication objects
  occurred_at   TIMESTAMPTZ NOT NULL,
  last_activity_at TIMESTAMPTZ NOT NULL,
  UNIQUE (source_id, external_id)
);
```

The 14 communication channel adapters that produce `NormalizedThread` continue working — they produce `NormalizedObject` with `object_kind = "message"`, which writes into `signals` with the same semantics. The inbox only shows signals where `object_kind IN ('message', 'dm', 'review', 'comment', 'mention')`. The unified command layer shows everything.

**What does NOT change:**

- The AI router and intelligence scoring prompts (they take text, they return JSON — object-agnostic)
- The workspace/tenant isolation
- The encryption layer
- The realtime event stream
- The CRM (contacts remain contacts; identities get `source_kind` instead of `channel_kind`)
- The automation rule engine structure (events + fact dicts + action handlers)
- The frontend shell, Signal Rail, and design system (the rail renders a score — it doesn't care what produced it)

---

## The actual debt register

| Item | Severity | Fix before Phase 6? |
|---|---|---|
| `ChannelKind` closed enum — wrong concept, wrong scope | **Critical** | Yes |
| `NormalizedThread + NormalizedMessage` — messaging-only shapes | **Critical** | Yes |
| `Thread + Message` tables — messaging-only schema | **Critical** | Yes |
| `ContactIdentity.kind: ChannelKind` | **High** | Yes |
| `facts_for(thread)` — automation can't reason about non-thread objects | **High** | Yes |
| `AutomationRun.thread_id` — FK assumes thread | **High** | Yes |
| `QueryPlan` intents — assistant blind to non-inbox sources | **High** | Yes |
| `search` — queries messages only | **High** | Yes |
| `PostMetric` fields — social-only | **Medium** | No (Phase 7 boundary) |
| `ScheduledPost` chain — social-only | **Medium** | No (Phase 7 boundary) |

---

## Recommendation

**Do not write Phase 6 code yet.**

The four Critical and four High items above are all in the data layer and two service files. Fixing them now costs one focused session and one migration. Fixing them after Phase 6 (when the frontend has 6 more pages built against `Thread`) costs three painful sessions and a migration that touches every layer.

The fix is not a rewrite. The core intelligence logic, the AI router, the encryption, the automation rule structure, the frontend shell — none of that changes. The fix is:

1. Rename `ChannelKind` → `SourceKind`, make it an open `TEXT` column with a CHECK constraint instead of a Postgres ENUM type
2. Rename `ChannelAccount` → `SourceAccount` (or keep the name, change the concept)
3. Introduce `NormalizedObject` as the transport type, with `object_kind` discriminating the subtype
4. Rename `Thread` → `Signal` in the ORM and schema, widen the columns
5. Replace `NormalizedThread.messages: list[NormalizedMessage]` with `payload: dict` (structured) + `body_text: str | None` (searchable content)
6. Change `ContactIdentity.kind` to `source_kind: str` (TEXT, not enum)
7. Change `AutomationRun.thread_id` → `object_id: UUID` (no FK, since objects live in one table now)
8. Add `object_kind` to the automation fact dict and make `facts_for` dispatch on it
9. Widen `QueryPlan` intents to include calendar, code, and analytics contexts
10. Make search query `signals` rather than `threads + messages`

This is the difference between building on a foundation and building on a floor that was poured for a smaller building.

The 14 communication adapters already written do not need to change at all. They produce objects, and objects go into signals. Everything they built is valid — it just needs to live in a more general container.

---

## One final thing

The Signal Rail — the vertical bar that fills to the opportunity score — is the right signature element for the entire operating layer, not just the inbox. A GitHub PR review request from a critical customer should score 88 and appear in the rail. A GA4 conversion spike should score 75. A financial alert about runway should score 95 and fire an automation.

The visual language is correct. The data model it sits on top of needs to match the ambition of the product.

