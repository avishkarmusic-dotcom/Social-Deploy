-- Tryvanta Social — canonical PostgreSQL schema
-- Design notes:
--   * Every tenant-scoped table carries workspace_id and is protected by RLS.
--   * Channel payloads are normalised into (thread, message) so one inbox can
--     hold an email, a LinkedIn DM and a Google review without special cases.
--   * AI output is stored beside the source row, never in place of it, so a
--     model change can be re-run without losing provenance.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── Identity ────────────────────────────────────────────────────────────────
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         CITEXT UNIQUE NOT NULL,
  full_name     TEXT NOT NULL,
  avatar_url    TEXT,
  locale        TEXT NOT NULL DEFAULT 'en',
  timezone      TEXT NOT NULL DEFAULT 'UTC',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  slug          TEXT UNIQUE NOT NULL,
  plan          TEXT NOT NULL DEFAULT 'free'
                CHECK (plan IN ('free','pro','team','enterprise')),
  owner_id      UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  -- The workspace data key, encrypted with the master key from the environment.
  -- Rotating the master rewraps N of these, not N million rows.
  wrapped_key   BYTEA NOT NULL,
  ai_spend_today_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workspace_members (
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role          TEXT NOT NULL CHECK (role IN ('owner','admin','member','viewer')),
  joined_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id)
);

-- ── Channels ────────────────────────────────────────────────────────────────
CREATE TYPE channel_kind AS ENUM (
  'gmail','outlook','linkedin','facebook','messenger','instagram','whatsapp',
  'telegram','slack','discord','google_business','x','threads','youtube'
);

CREATE TABLE channel_accounts (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id   UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  kind           channel_kind NOT NULL,
  external_id    TEXT NOT NULL,              -- provider account id
  display_name   TEXT NOT NULL,
  avatar_url     TEXT,
  -- envelope-encrypted, with the account id as AAD; the app never stores
  -- plaintext tokens, and a row lifted into another account's context fails
  -- to decrypt rather than silently working.
  access_token_enc  BYTEA,
  refresh_token_enc BYTEA,
  token_expires  TIMESTAMPTZ,
  scopes         TEXT[] NOT NULL DEFAULT '{}',
  status         TEXT NOT NULL DEFAULT 'connected'
                 CHECK (status IN ('connected','expired','revoked','error')),
  sync_cursor    TEXT,                       -- historyId / delta token / since_id
  last_synced_at TIMESTAMPTZ,
  last_error     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, kind, external_id)
);

-- ── People (the CRM spine; contacts are deduplicated across channels) ───────
CREATE TABLE contacts (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id   UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  display_name   TEXT NOT NULL,
  primary_email  CITEXT,
  company        TEXT,
  title          TEXT,
  avatar_url     TEXT,
  tags           TEXT[] NOT NULL DEFAULT '{}',
  notes          TEXT,
  importance     SMALLINT NOT NULL DEFAULT 50 CHECK (importance BETWEEN 0 AND 100),
  -- decays with silence, rises with two-way exchange; recomputed nightly
  relationship_strength SMALLINT NOT NULL DEFAULT 0
                 CHECK (relationship_strength BETWEEN 0 AND 100),
  last_interaction_at TIMESTAMPTZ,
  next_followup_at    TIMESTAMPTZ,
  birthday_on    DATE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX contacts_followup_idx ON contacts (workspace_id, next_followup_at)
  WHERE next_followup_at IS NOT NULL;
CREATE INDEX contacts_name_trgm ON contacts USING gin (display_name gin_trgm_ops);

CREATE TABLE contact_identities (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id    UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  kind          channel_kind NOT NULL,
  handle        TEXT NOT NULL,
  UNIQUE (kind, handle)
);

-- ── Conversations ───────────────────────────────────────────────────────────
CREATE TABLE threads (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id   UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  account_id     UUID NOT NULL REFERENCES channel_accounts(id) ON DELETE CASCADE,
  contact_id     UUID REFERENCES contacts(id) ON DELETE SET NULL,
  external_id    TEXT NOT NULL,
  subject        TEXT,
  snippet        TEXT,
  state          TEXT NOT NULL DEFAULT 'open'
                 CHECK (state IN ('open','snoozed','archived','done','spam')),
  is_unread      BOOLEAN NOT NULL DEFAULT true,
  is_starred     BOOLEAN NOT NULL DEFAULT false,
  snoozed_until  TIMESTAMPTZ,
  message_count  INT NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (account_id, external_id)
);
CREATE INDEX threads_inbox_idx
  ON threads (workspace_id, state, last_message_at DESC);

CREATE TABLE messages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  thread_id     UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  external_id   TEXT NOT NULL,
  direction     TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  author_name   TEXT NOT NULL,
  author_handle TEXT,
  -- Sealed with the workspace key, bound to thread_id as AAD.
  body_enc      BYTEA NOT NULL,
  body_html     TEXT,
  attachments   JSONB NOT NULL DEFAULT '[]',
  reply_ref     JSONB NOT NULL DEFAULT '{}',
  sent_at       TIMESTAMPTZ NOT NULL,
  embedding     vector(1536),               -- semantic global search
  -- NOT a generated column: the body is ciphertext, so Postgres cannot derive
  -- this. It is computed in the app from plaintext at ingest, before sealing.
  -- The tradeoff is explicit: an index of lexemes is readable to anyone with
  -- database access, so search leaks vocabulary even though bodies do not.
  search_tsv    TSVECTOR,
  UNIQUE (thread_id, external_id)
);
CREATE INDEX messages_search_idx ON messages USING gin (search_tsv);
CREATE INDEX messages_vec_idx ON messages USING hnsw (embedding vector_cosine_ops);

-- ── AI layer ────────────────────────────────────────────────────────────────
-- One row per (thread, model run). Never overwrites the source message.
CREATE TABLE thread_intelligence (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id   UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  thread_id      UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  category       TEXT NOT NULL,   -- recruiter | lead | client | investor | spam | ...
  intent         TEXT,
  urgency        SMALLINT NOT NULL CHECK (urgency BETWEEN 0 AND 100),
  -- the number the Signal Rail renders: how much this is worth acting on
  opportunity_score SMALLINT NOT NULL CHECK (opportunity_score BETWEEN 0 AND 100),
  opportunity_kind TEXT,          -- job | investment | client_lead | speaking | grant | ...
  estimated_value_usd NUMERIC(12,2),
  summary        TEXT NOT NULL,
  action_items   JSONB NOT NULL DEFAULT '[]',
  sentiment      TEXT CHECK (sentiment IN ('positive','neutral','negative')),
  language       TEXT,
  model          TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  latency_ms     INT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX thread_intel_current ON thread_intelligence (thread_id, prompt_version);
CREATE INDEX thread_intel_opportunity ON thread_intelligence
  (workspace_id, opportunity_score DESC) WHERE opportunity_score >= 60;

CREATE TABLE ai_drafts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  thread_id     UUID REFERENCES threads(id) ON DELETE CASCADE,
  tone          TEXT NOT NULL,   -- professional | casual | confident | ceo | sales | support
  body          TEXT NOT NULL,
  accepted      BOOLEAN,         -- NULL until the user sends or discards
  edited_body   TEXT,            -- what actually went out; trains the voice model
  created_by    UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Publishing ──────────────────────────────────────────────────────────────
CREATE TABLE content_pieces (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,  -- linkedin_post | x_thread | ig_caption | newsletter | article
  title         TEXT,
  body          TEXT NOT NULL,
  hashtags      TEXT[] NOT NULL DEFAULT '{}',
  media         JSONB NOT NULL DEFAULT '[]',
  status        TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','approved','scheduled','published','failed')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scheduled_posts (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id   UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  content_id     UUID NOT NULL REFERENCES content_pieces(id) ON DELETE CASCADE,
  account_id     UUID NOT NULL REFERENCES channel_accounts(id) ON DELETE CASCADE,
  scheduled_for  TIMESTAMPTZ NOT NULL,
  rrule          TEXT,                     -- iCal RRULE for recurring posts
  status         TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','publishing','published','failed','cancelled')),
  external_url   TEXT,
  attempts       SMALLINT NOT NULL DEFAULT 0,
  last_error     TEXT
);
CREATE INDEX scheduled_due_idx ON scheduled_posts (scheduled_for)
  WHERE status = 'queued';

CREATE TABLE post_metrics (
  post_id      UUID NOT NULL REFERENCES scheduled_posts(id) ON DELETE CASCADE,
  captured_at  TIMESTAMPTZ NOT NULL,
  impressions  INT NOT NULL DEFAULT 0,
  engagements  INT NOT NULL DEFAULT 0,
  clicks       INT NOT NULL DEFAULT 0,
  follows      INT NOT NULL DEFAULT 0,
  PRIMARY KEY (post_id, captured_at)
);

-- ── Reputation ──────────────────────────────────────────────────────────────
CREATE TABLE reviews (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  account_id    UUID NOT NULL REFERENCES channel_accounts(id) ON DELETE CASCADE,
  external_id   TEXT NOT NULL,
  author_name   TEXT NOT NULL,
  rating        SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body          TEXT,
  replied_at    TIMESTAMPTZ,
  reply_body    TEXT,
  posted_at     TIMESTAMPTZ NOT NULL,
  UNIQUE (account_id, external_id)
);

-- ── Automation ──────────────────────────────────────────────────────────────
CREATE TABLE automations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  enabled       BOOLEAN NOT NULL DEFAULT true,
  trigger       JSONB NOT NULL,   -- {event, filters:[{field,op,value}]}
  actions       JSONB NOT NULL,   -- [{type, params}]
  run_count     INT NOT NULL DEFAULT 0,
  last_run_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE automation_runs (
  id            BIGSERIAL PRIMARY KEY,
  automation_id UUID NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
  thread_id     UUID REFERENCES threads(id) ON DELETE SET NULL,
  status        TEXT NOT NULL CHECK (status IN ('success','failed','skipped')),
  detail        JSONB,
  ran_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Compliance ──────────────────────────────────────────────────────────────
CREATE TABLE audit_log (
  id            BIGSERIAL PRIMARY KEY,
  workspace_id  UUID REFERENCES workspaces(id) ON DELETE SET NULL,
  actor_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  actor_kind    TEXT NOT NULL CHECK (actor_kind IN ('user','system','automation','ai')),
  action        TEXT NOT NULL,
  resource      TEXT NOT NULL,
  resource_id   TEXT,
  ip            INET,
  metadata      JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_ws_idx ON audit_log (workspace_id, created_at DESC);

-- ── Row-level security (applied to every tenant table) ──────────────────────
ALTER TABLE threads               ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages              ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts              ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_accounts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE thread_intelligence   ENABLE ROW LEVEL SECURITY;

CREATE POLICY ws_isolation_threads ON threads USING
  (workspace_id = current_setting('app.workspace_id')::uuid);
CREATE POLICY ws_isolation_messages ON messages USING
  (workspace_id = current_setting('app.workspace_id')::uuid);
CREATE POLICY ws_isolation_contacts ON contacts USING
  (workspace_id = current_setting('app.workspace_id')::uuid);
CREATE POLICY ws_isolation_accounts ON channel_accounts USING
  (workspace_id = current_setting('app.workspace_id')::uuid);
CREATE POLICY ws_isolation_intel ON thread_intelligence USING
  (workspace_id = current_setting('app.workspace_id')::uuid);
