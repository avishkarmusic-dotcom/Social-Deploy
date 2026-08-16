/**
 * Domain types — aligned with Phase 3b models.
 * Run `npm run generate:api` to regenerate from the live schema.
 */

// ── Sources ──────────────────────────────────────────────────────────────
export type SourceKind = string;   // plain string — not a closed enum
export type ChannelKind = SourceKind;  // Alias for backward compatibility

export interface SourceAccount {
  id: string;
  source_kind: SourceKind;
  display_name: string;
  avatar_url: string | null;
  status: "connected" | "expired" | "revoked" | "error";
  last_synced_at: string | null;
  last_error: string | null;
  supports_push: boolean;
  can_publish: boolean;
}

// ── Inbox ────────────────────────────────────────────────────────────────
export type Tone =
  | "professional" | "casual" | "polite" | "confident"
  | "ceo" | "founder" | "sales" | "support";

export type ObjectKind = "message" | "event" | "work_item" | "document" | "metric" | "alert";

export interface InboundObject {
  id: string;
  channel: SourceKind;
  object_kind: ObjectKind;
  subject: string | null;
  snippet: string;
  sender: string;
  unread: boolean;
  starred: boolean;
  last_message_at: string;
  category: string | null;
  opportunity_score: number;
  opportunity_kind: string | null;
  urgency: number;
  summary: string | null;
  action_items: string[];
}

// Legacy alias so existing components don't break
export type Thread = InboundObject;

export interface ThreadDetail extends InboundObject {
  messages: {
    id: string;
    author: string;
    direction: "inbound" | "outbound" | null;
    sent_at: string;
    body: string;
  }[];
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  unread_total: number;
}

// ── Contacts / CRM ───────────────────────────────────────────────────────
export interface Contact {
  id: string;
  display_name: string;
  company: string | null;
  title: string | null;
  primary_email: string | null;
  tags: string[];
  importance: number;
  relationship_strength: number;
  last_interaction_at: string | null;
  next_followup_at: string | null;
  days_silent: number | null;
  channels: string[];
}

export interface TimelineEntry {
  thread_id: string;
  channel: string;
  subject: string | null;
  direction: string;
  body: string;
  sent_at: string;
}

// ── Content & Scheduling ─────────────────────────────────────────────────
export interface ContentPiece {
  id: string;
  kind: string;
  title: string | null;
  body: string;
  hashtags: string[];
  status: string;
  created_at: string;
  scheduled_for: string | null;
  external_url: string | null;
}

export interface ScheduledPost {
  post_id: string;
  title: string;
  channel: string;
  scheduled_for: string;
  status: string;
  external_url: string | null;
  last_error: string | null;
}

export type ContentKind =
  | "linkedin_post" | "x_thread" | "instagram_caption" | "facebook_post"
  | "blog_article" | "newsletter" | "email_campaign" | "product_launch"
  | "hashtags" | "seo_title" | "meta_description";

export interface ContentVariant {
  angle: string;
  body: string;
  hashtags: string[];
}

// ── Automations ──────────────────────────────────────────────────────────
export interface AutomationFilter {
  field: string;
  op: string;
  value: unknown;
}

export interface AutomationAction {
  type: string;
  params: Record<string, unknown>;
}

export interface AutomationRule {
  id: string;
  name: string;
  enabled: boolean;
  trigger: { event: string; filters: AutomationFilter[] };
  actions: AutomationAction[];
  run_count: number;
  last_run_at: string | null;
}

export interface AutomationVocabulary {
  events: string[];
  fields: string[];
  operators: string[];
  actions: string[];
}

export interface AutomationRun {
  id: number;
  status: "success" | "failed" | "skipped";
  object_id: string | null;
  object_kind: string | null;
  detail: Record<string, unknown> | null;
  ran_at: string;
}

// ── Analytics ────────────────────────────────────────────────────────────
export interface Metric {
  value: number | null;
  label: string;
  change_pct: number | null;
  confident: boolean;
  note: string | null;
}

export interface ChannelYield {
  channel: string;
  threads: number;
  opportunities: number;
  hit_rate: number;
  estimated_value_usd: number;
}

export interface GrowthPoint {
  week: string;
  threads: number;
  opportunities: number;
}

// ── Shared ───────────────────────────────────────────────────────────────
export interface ApiError {
  error: string;
  message: string;
  fix: string;
}

export interface RealtimeEvent {
  cursor: string;
  event: "thread.created" | "thread.scored" | "object.scored" | "notification" | "ping";
  at: string;
  data: Record<string, unknown>;
}
