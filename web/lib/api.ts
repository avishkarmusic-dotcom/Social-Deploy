/**
 * Typed API client.
 *
 * One rule: errors surface unchanged from the server. The backend writes a fix
 * string; the UI renders it. No re-wording in transit.
 */
import type {
  ApiError, AutomationAction, AutomationFilter, AutomationRule, AutomationRun,
  AutomationVocabulary, ChannelYield, Contact, ContentKind, ContentPiece,
  ContentVariant, GrowthPoint, InboundObject, Metric, Page, ScheduledPost,
  SourceAccount, ThreadDetail, TimelineEntry, Tone,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiFailure extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly fix: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function token(): string | null {
  if (typeof document === "undefined") return null;
  return document.cookie.match(/(?:^|;\s*)ts_session=([^;]+)/)?.[1] ?? null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    let body: Partial<ApiError> = {};
    try { body = await res.json(); } catch { /* non-JSON */ }
    throw new ApiFailure(
      body.error ?? "request_failed",
      body.message ?? "The request didn't go through.",
      body.fix ?? "Check your connection and try again.",
      res.status,
    );
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

function qs(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    if (Array.isArray(v)) v.forEach((x) => q.append(k, String(x)));
    else q.set(k, String(v));
  }
  const str = q.toString();
  return str ? `?${str}` : "";
}

export const api = {
  // ── Inbox ──────────────────────────────────────────────────────────
  inbox: {
    list: (params: {
      sort?: "newest" | "opportunity" | "urgency";
      state?: string;
      channel?: string[];
      min_opportunity?: number;
      cursor?: string;
      limit?: number;
    } = {}) => request<Page<InboundObject>>(`/v1/inbox${qs(params)}`),

    get: (id: string) => request<ThreadDetail>(`/v1/inbox/${id}`),

    draft: (id: string, body: { tone: Tone; length?: string; translate_to?: string }) =>
      request<{ draft_id: string; body: string; tone: string }>(
        `/v1/inbox/${id}/draft`,
        { method: "POST", body: JSON.stringify(body) },
      ),

    setState: (id: string, state: string, snoozed_until?: string) =>
      request<{ id: string; state: string }>(`/v1/inbox/${id}/state`, {
        method: "POST",
        body: JSON.stringify({ state, snoozed_until: snoozed_until ?? null }),
      }),
  },

  // ── Sources (was Channels) ─────────────────────────────────────────
  sources: {
    list: () => request<SourceAccount[]>("/v1/channels"),
    connect: (kind: string) =>
      request<{ authorize_url: string; expires_in: number }>(
        `/v1/channels/${kind}/connect`,
      ),
    sync: (id: string) =>
      request<{ queued: boolean; kind: string }>(`/v1/channels/${id}/sync`, {
        method: "POST",
      }),
    disconnect: (id: string) =>
      request<{ disconnected: string }>(`/v1/channels/${id}`, { method: "DELETE" }),
    meta: () =>
      request<{ channels: { kind: string; configured: boolean }[] }>("/v1/meta"),
  },

  // ── AI ────────────────────────────────────────────────────────────
  ai: {
    ask: (question: string) =>
      request<{ answer: string; intent: string; rows_considered: number }>(
        "/v1/ai/assistant",
        { method: "POST", body: JSON.stringify({ question }) },
      ),

    content: (body: {
      kind: ContentKind;
      brief: string;
      tone?: string;
      variants?: number;
    }) =>
      request<ContentVariant[]>("/v1/ai/content", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    rewrite: (text: string, mode: string, target_language?: string) =>
      request<{ text: string; mode: string }>("/v1/ai/rewrite", {
        method: "POST",
        body: JSON.stringify({ text, mode, target_language }),
      }),
  },

  // ── Content & Scheduling ───────────────────────────────────────────
  content: {
    list: (params: { status?: string; limit?: number } = {}) =>
      request<ContentPiece[]>(`/v1/content${qs(params)}`),

    create: (body: { kind: string; title?: string; body: string; hashtags?: string[] }) =>
      request<ContentPiece>("/v1/content", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    schedule: (
      id: string,
      body: { account_id: string; scheduled_for: string; rrule?: string },
    ) =>
      request<{ post_id: string; channel: string; scheduled_for: string }>(
        `/v1/content/${id}/schedule`,
        { method: "POST", body: JSON.stringify(body) },
      ),

    calendar: (start: string, end: string) =>
      request<ScheduledPost[]>(`/v1/content/calendar${qs({ start, end })}`),

    bestTimes: (channel: string) =>
      request<{ channel: string; slots: { day: string; hour: number; engagement_rate: number }[]; note: string }>(
        `/v1/content/best-times${qs({ channel })}`,
      ),
  },

  // ── Contacts / CRM ────────────────────────────────────────────────
  contacts: {
    list: (params: { sort?: string; tag?: string; limit?: number } = {}) =>
      request<Contact[]>(`/v1/contacts${qs(params)}`),

    followups: (within_days?: number) =>
      request<Contact[]>(`/v1/contacts/followups${qs({ within_days })}`),

    timeline: (id: string) =>
      request<TimelineEntry[]>(`/v1/contacts/${id}/timeline`),

    update: (id: string, patch: Partial<Contact & { next_followup_at?: string }>) =>
      request<Contact>(`/v1/contacts/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),

    merge: (keepId: string, absorbId: string) =>
      request<{ kept: string; absorbed: string }>(`/v1/contacts/${keepId}/merge`, {
        method: "POST",
        body: JSON.stringify({ absorb_id: absorbId }),
      }),
  },

  // ── Automations ────────────────────────────────────────────────────
  automations: {
    vocabulary: () => request<AutomationVocabulary>("/v1/automations/vocabulary"),

    list: () => request<AutomationRule[]>("/v1/automations"),

    create: (rule: {
      name: string;
      enabled?: boolean;
      trigger: { event: string; filters: AutomationFilter[] };
      actions: AutomationAction[];
    }) =>
      request<AutomationRule>("/v1/automations", {
        method: "POST",
        body: JSON.stringify(rule),
      }),

    update: (id: string, rule: Partial<AutomationRule>) =>
      request<AutomationRule>(`/v1/automations/${id}`, {
        method: "PATCH",
        body: JSON.stringify(rule),
      }),

    toggle: (id: string, enabled: boolean) =>
      request<AutomationRule>(`/v1/automations/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),

    test: (rule: Partial<AutomationRule>, sample?: number) =>
      request<{ would_fire_on: Record<string, unknown>[]; checked: number; note: string }>(
        `/v1/automations/test${qs({ sample })}`,
        { method: "POST", body: JSON.stringify(rule) },
      ),

    runs: (id: string, limit?: number) =>
      request<AutomationRun[]>(`/v1/automations/${id}/runs${qs({ limit })}`),

    delete: (id: string) =>
      request<{ deleted: string }>(`/v1/automations/${id}`, { method: "DELETE" }),
  },

  // ── Analytics ──────────────────────────────────────────────────────
  analytics: {
    overview: (days = 30) =>
      request<Record<string, Metric>>(`/v1/analytics/overview${qs({ days })}`),

    channels: (days = 90) =>
      request<ChannelYield[]>(`/v1/analytics/channels${qs({ days })}`),

    growth: (days = 180) =>
      request<GrowthPoint[]>(`/v1/analytics/growth${qs({ days })}`),

    attribution: (days = 90) =>
      request<{ window_days: number; by_opportunity_kind: Record<string, unknown>[]; caveat: string }>(
        `/v1/analytics/attribution${qs({ days })}`,
      ),
  },

  // ── Global Search ──────────────────────────────────────────────────
  search: (q: string, limit = 20) =>
    request<{ query: string; hits: Record<string, unknown>[] }>(
      `/v1/search${qs({ q, limit })}`,
    ),
};

export const wsUrl = (session: string, since = "$") =>
  `${BASE.replace(/^http/, "ws")}/v1/ws?token=${session}&since=${since}`;
