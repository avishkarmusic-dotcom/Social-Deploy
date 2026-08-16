"""Phase 3b: ChannelAccount→SourceAccount, Thread→InboundObject,
Message→InboundPayload, ThreadIntelligence→Signal.

Strategy: RENAME TABLE + ALTER COLUMN. No data movement. Existing rows
migrate automatically because the column content doesn't change — only the
table names, column names, and the ENUM→TEXT type on source_kind.

Revision ID: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Drop the Postgres ENUM so we can use plain TEXT ─────────────
    # channel_kind was used in channel_accounts.kind and contact_identities.kind
    # ALTER COLUMN ... TYPE TEXT USING ... converts without data loss.
    op.execute("""
        ALTER TABLE channel_accounts
          ALTER COLUMN kind TYPE TEXT USING kind::TEXT
    """)
    op.execute("""
        ALTER TABLE contact_identities
          ALTER COLUMN kind TYPE TEXT USING kind::TEXT
    """)
    op.execute("DROP TYPE IF EXISTS channel_kind CASCADE")

    # ── 2. Rename tables ────────────────────────────────────────────────
    op.rename_table("channel_accounts", "source_accounts")
    op.rename_table("threads", "inbound_objects")
    op.rename_table("messages", "inbound_payloads")
    op.rename_table("thread_intelligence", "signals")

    # ── 3. Rename columns on source_accounts ────────────────────────────
    op.alter_column("source_accounts", "kind", new_column_name="source_kind")

    # ── 4. Add object_kind and payload to inbound_objects ───────────────
    op.add_column("inbound_objects",
        sa.Column("object_kind", sa.Text, nullable=False, server_default="message"))
    op.add_column("inbound_objects",
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"))

    # Rename columns on inbound_objects
    op.alter_column("inbound_objects", "account_id", new_column_name="source_account_id")
    op.alter_column("inbound_objects", "subject", new_column_name="title")
    op.alter_column("inbound_objects", "last_message_at", new_column_name="last_activity_at")
    op.alter_column("inbound_objects", "message_count", new_column_name="payload_count")

    # ── 5. Update inbound_payloads ──────────────────────────────────────
    op.alter_column("inbound_payloads", "thread_id", new_column_name="object_id",
                    nullable=False)
    # body_text column → body_enc (already encrypted in Phase 3); make nullable
    op.alter_column("inbound_payloads", "body_enc", nullable=True)
    # direction becomes nullable for non-communication payloads
    op.alter_column("inbound_payloads", "direction", nullable=True)
    # Rename author fields
    op.alter_column("inbound_payloads", "author_name", new_column_name="actor_name")
    op.alter_column("inbound_payloads", "author_handle", new_column_name="actor_handle")
    # reply_ref → action_ref
    op.alter_column("inbound_payloads", "reply_ref", new_column_name="action_ref")
    # Add structured column
    op.add_column("inbound_payloads",
        sa.Column("structured", postgresql.JSONB, nullable=False, server_default="{}"))

    # ── 6. Update signals (was thread_intelligence) ─────────────────────
    op.alter_column("signals", "thread_id", new_column_name="object_id")
    op.add_column("signals",
        sa.Column("object_kind", sa.Text, nullable=False, server_default="message"))

    # ── 7. Update contact_identities ────────────────────────────────────
    op.alter_column("contact_identities", "kind", new_column_name="source_kind")
    # Constraint rename (the imported initial schema may omit this constraint).
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'uq_identity_handle'
              AND conrelid = 'contact_identities'::regclass
          ) THEN
            ALTER TABLE contact_identities DROP CONSTRAINT uq_identity_handle;
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'uq_identity_handle'
              AND conrelid = 'contact_identities'::regclass
          ) THEN
            ALTER TABLE contact_identities
              ADD CONSTRAINT uq_identity_handle UNIQUE (source_kind, handle);
          END IF;
        END $$;
    """)

    # ── 8. Update ai_drafts ──────────────────────────────────────────────
    op.alter_column("ai_drafts", "thread_id", new_column_name="object_id", nullable=True)

    # ── 9. Update automation_runs ────────────────────────────────────────
    # Drop the FK constraint (thread_id had one), then rename to generic object_id.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'automation_runs_thread_id_fkey'
              AND conrelid = 'automation_runs'::regclass
          ) THEN
            ALTER TABLE automation_runs
              DROP CONSTRAINT automation_runs_thread_id_fkey;
          END IF;
        END $$;
    """)
    op.alter_column("automation_runs", "thread_id", new_column_name="object_id", nullable=True)
    op.add_column("automation_runs",
        sa.Column("object_kind", sa.Text, nullable=True))

    # ── 10. Update scheduled_posts ───────────────────────────────────────
    op.alter_column("scheduled_posts", "account_id", new_column_name="source_account_id")

    # ── 11. Update reviews ───────────────────────────────────────────────
    op.alter_column("reviews", "account_id", new_column_name="source_account_id",
                    nullable=False)

    # ── 12. Rename workspace.accounts relationship column ref ────────────
    # (no column change needed — FK still points to source_accounts.id)

    # ── 13. Update indexes ───────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'threads_inbox_idx') THEN
            DROP INDEX threads_inbox_idx;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'messages_search_idx') THEN
            DROP INDEX messages_search_idx;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'messages_vec_idx') THEN
            DROP INDEX messages_vec_idx;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'thread_intel_current') THEN
            DROP INDEX thread_intel_current;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'thread_intel_opportunity') THEN
            DROP INDEX thread_intel_opportunity;
          END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_objects_inbox
          ON inbound_objects (workspace_id, state, last_activity_at DESC)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_run
          ON signals (object_id, prompt_version)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_signals_opportunity
          ON signals (workspace_id, opportunity_score DESC)
    """)

    # ── 14. Update RLS policies ─────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
          DROP POLICY IF EXISTS ws_isolation_threads ON inbound_objects;
          DROP POLICY IF EXISTS ws_isolation_messages ON inbound_payloads;
          DROP POLICY IF EXISTS ws_isolation_intel ON signals;
          DROP POLICY IF EXISTS ws_isolation_accounts ON source_accounts;
        EXCEPTION WHEN undefined_table THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'inbound_objects' AND policyname = 'ws_isolation_objects'
          ) THEN
            CREATE POLICY ws_isolation_objects ON inbound_objects
              USING (workspace_id = current_setting('app.workspace_id')::uuid);
          END IF;
        EXCEPTION WHEN undefined_object THEN NULL;
        END $$;
    """)


def downgrade() -> None:
    # Reverse only the renames — the ENUM cannot be recreated automatically
    # because it may conflict with existing TEXT data. Manual intervention needed.
    op.rename_table("source_accounts", "channel_accounts")
    op.rename_table("inbound_objects", "threads")
    op.rename_table("inbound_payloads", "messages")
    op.rename_table("signals", "thread_intelligence")
    op.alter_column("channel_accounts", "source_kind", new_column_name="kind")
    op.alter_column("threads", "source_account_id", new_column_name="account_id")
    op.alter_column("threads", "title", new_column_name="subject")
    op.alter_column("threads", "last_activity_at", new_column_name="last_message_at")
    op.alter_column("threads", "payload_count", new_column_name="message_count")
    op.alter_column("messages", "object_id", new_column_name="thread_id")
    op.alter_column("messages", "actor_name", new_column_name="author_name")
    op.alter_column("messages", "actor_handle", new_column_name="author_handle")
    op.alter_column("messages", "action_ref", new_column_name="reply_ref")
    op.alter_column("thread_intelligence", "object_id", new_column_name="thread_id")
    op.alter_column("contact_identities", "source_kind", new_column_name="kind")
    op.alter_column("ai_drafts", "object_id", new_column_name="thread_id")
    op.alter_column("automation_runs", "object_id", new_column_name="thread_id")
    op.alter_column("scheduled_posts", "source_account_id", new_column_name="account_id")
    op.alter_column("reviews", "source_account_id", new_column_name="account_id")
