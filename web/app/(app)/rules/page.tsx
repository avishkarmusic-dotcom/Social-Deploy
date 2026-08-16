"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, Check, ChevronDown, ChevronRight,
  Loader2, Plus, Trash2, Workflow, Zap,
} from "lucide-react";
import clsx from "clsx";
import { api, ApiFailure } from "@/lib/api";
import type { AutomationRule, AutomationVocabulary } from "@/lib/types";
import { relativeTime } from "@/lib/format";
import { Button, Chip, Empty, Failure, Mono } from "@/components/ui/primitives";

/* ── Rule card ────────────────────────────────────────────────────────── */
function RuleCard({
  rule,
  onToggle,
  onDelete,
  onExpand,
  expanded,
}: {
  rule: AutomationRule;
  onToggle: () => void;
  onDelete: () => void;
  onExpand: () => void;
  expanded: boolean;
}) {
  const filters = rule.trigger.filters ?? [];
  const filterText = filters.length
    ? filters.map((f) => `${f.field} ${f.op} ${f.value}`).join(" and ")
    : "always";

  return (
    <article
      className="rounded-xl border border-line bg-raise"
      style={{ animation: "rise 380ms ease both" }}
    >
      <div className="flex items-center gap-3 p-4">
        {/* Toggle */}
        <button
          role="switch"
          aria-checked={rule.enabled}
          onClick={onToggle}
          className="relative h-[18px] w-8 shrink-0 rounded-full transition-colors"
          style={{
            background: rule.enabled ? "rgb(var(--mint))" : "rgb(var(--line))",
          }}
        >
          <span
            className="absolute top-[2px] h-3.5 w-3.5 rounded-full bg-white transition-all"
            style={{ left: rule.enabled ? 16 : 2 }}
          />
        </button>

        <div className="min-w-0 flex-1">
          <span className="text-[13px] font-medium text-paper">{rule.name}</span>
        </div>

        <Mono className="shrink-0 text-faint">{rule.run_count} runs</Mono>

        <button
          onClick={onExpand}
          className="p-1 text-faint hover:text-paper"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>

        <button
          onClick={onDelete}
          className="p-1 text-faint hover:text-ember"
          aria-label="Delete rule"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {expanded && (
        <div className="border-t border-line px-4 pb-4 pt-3 space-y-2">
          <div className="flex gap-2">
            <Mono className="w-12 shrink-0 text-amber">WHEN</Mono>
            <span className="text-[12px] text-quiet">
              {rule.trigger.event} — {filterText}
            </span>
          </div>
          {rule.actions.map((a, i) => (
            <div key={i} className="flex gap-2">
              <Mono className="w-12 shrink-0 text-mint">THEN</Mono>
              <span className="text-[12px] text-quiet">
                {a.type}
                {Object.keys(a.params).length > 0 && (
                  <span className="text-faint">
                    {" "}
                    ({Object.entries(a.params)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ")})
                  </span>
                )}
              </span>
            </div>
          ))}
          {rule.last_run_at && (
            <Mono className="text-faint">
              Last ran {relativeTime(rule.last_run_at)}
            </Mono>
          )}
        </div>
      )}
    </article>
  );
}

/* ── Builder ──────────────────────────────────────────────────────────── */
const STARTER_RULES = [
  {
    name: "Recruiter with a real role",
    trigger: {
      event: "object.scored",
      filters: [
        { field: "category",          op: "eq",  value: "recruiter" },
        { field: "opportunity_score", op: "gte", value: 70 },
      ],
    },
    actions: [
      { type: "notify",      params: { title: "Recruiter worth answering", priority: "high" } },
      { type: "tag_contact", params: { tag: "Recruiter" } },
    ],
  },
  {
    name: "Review drops below three stars",
    trigger: {
      event: "object.scored",
      filters: [
        { field: "source",    op: "eq", value: "google_business" },
        { field: "sentiment", op: "eq", value: "negative" },
      ],
    },
    actions: [
      { type: "draft_reply", params: { tone: "support" } },
      { type: "notify",      params: { title: "Negative review is public", priority: "high" } },
    ],
  },
  {
    name: "High-value object, set follow-up",
    trigger: {
      event: "object.scored",
      filters: [
        { field: "opportunity_score", op: "gte", value: 75 },
      ],
    },
    actions: [
      { type: "set_followup",    params: { days: 2 } },
      { type: "boost_importance", params: { by: 20 } },
    ],
  },
];

function Builder({
  vocab,
  onCreated,
  onClose,
}: {
  vocab: AutomationVocabulary;
  onCreated: (rule: AutomationRule) => void;
  onClose: () => void;
}) {
  const [name, setName]       = useState("");
  const [event, setEvent]     = useState(vocab.events[0] ?? "object.scored");
  const [field, setField]     = useState(vocab.fields[0] ?? "category");
  const [op, setOp]           = useState("eq");
  const [value, setValue]     = useState("");
  const [action, setAction]   = useState(vocab.actions[0] ?? "notify");
  const [busy, setBusy]       = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const save = async () => {
    if (!name.trim() || !value.trim()) return;
    setBusy(true);
    setFailure(null);
    try {
      const rule = await api.automations.create({
        name,
        trigger: { event, filters: [{ field, op, value }] },
        actions: [{ type: action, params: {} }],
      });
      onCreated(rule);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-iris/30 bg-raise p-5">
      <div className="mb-4 flex items-center gap-2">
        <Sparkles />
        <span className="text-[13px] font-medium text-paper">New rule</span>
        <button onClick={onClose} className="ml-auto text-faint hover:text-paper text-xs">
          Cancel
        </button>
      </div>

      {failure && <div className="mb-4"><Failure message={failure.message} fix={failure.fix} /></div>}

      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs text-quiet" htmlFor="rule-name">Name</label>
          <input
            id="rule-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Recruiters worth answering"
            className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none focus:border-iris"
          />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs text-quiet">Event</label>
            <select
              value={event}
              onChange={(e) => setEvent(e.target.value)}
              className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none"
            >
              {vocab.events.map((ev) => (
                <option key={ev} value={ev}>{ev}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-quiet">Field</label>
            <select
              value={field}
              onChange={(e) => setField(e.target.value)}
              className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none"
            >
              {vocab.fields.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-quiet">Value</label>
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="recruiter / 70 / negative"
              className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none focus:border-iris"
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs text-quiet">Then do</label>
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none"
          >
            {vocab.actions.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>

        <Button primary small onClick={save} disabled={busy || !name.trim() || !value.trim()}>
          {busy ? "Saving…" : "Create rule"}
        </Button>
      </div>
    </div>
  );
}

function Sparkles() {
  return <Zap size={13} className="text-iris" />;
}

/* ── Page ─────────────────────────────────────────────────────────────── */
export default function RulesPage() {
  const [rules, setRules]       = useState<AutomationRule[]>([]);
  const [vocab, setVocab]       = useState<AutomationVocabulary | null>(null);
  const [loading, setLoading]   = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [failure, setFailure]   = useState<ApiFailure | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, v] = await Promise.all([
        api.automations.list(),
        api.automations.vocabulary(),
      ]);
      setRules(r);
      setVocab(v);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggle = async (rule: AutomationRule) => {
    const updated = await api.automations.toggle(rule.id, !rule.enabled);
    setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
  };

  const remove = async (id: string) => {
    await api.automations.delete(id);
    setRules((prev) => prev.filter((r) => r.id !== id));
  };

  const addStarter = async (starter: (typeof STARTER_RULES)[number]) => {
    if (!vocab) return;
    const rule = await api.automations.create(starter);
    setRules((prev) => [rule, ...prev]);
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="mb-1 text-xl font-semibold tracking-tight text-paper">Rules</h1>
          <p className="text-sm text-quiet">
            Runs while you sleep. Rules only fire on facts the system can actually see.
          </p>
        </div>
        <Button primary small onClick={() => setBuilding((b) => !b)}>
          <span className="flex items-center gap-1.5">
            <Plus size={13} /> New rule
          </span>
        </Button>
      </div>

      {failure && <div className="mb-5"><Failure message={failure.message} fix={failure.fix} /></div>}

      {building && vocab && (
        <div className="mb-6">
          <Builder
            vocab={vocab}
            onCreated={(rule) => {
              setRules((prev) => [rule, ...prev]);
              setBuilding(false);
            }}
            onClose={() => setBuilding(false)}
          />
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-12">
          <Loader2 size={16} className="animate-spin text-faint" />
        </div>
      )}

      {!loading && rules.length === 0 && (
        <div>
          <Empty
            icon={<Workflow size={24} />}
            title="No rules yet. Try one of these to start."
          />
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            {STARTER_RULES.map((starter) => (
              <button
                key={starter.name}
                onClick={() => void addStarter(starter)}
                className="rounded-xl border border-line bg-raise p-4 text-left hover:border-iris/40 transition-colors"
              >
                <p className="mb-1 text-[13px] font-medium text-paper">{starter.name}</p>
                <p className="text-xs text-quiet">
                  {starter.actions.map((a) => a.type).join(" · ")}
                </p>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-3">
        {rules.map((rule) => (
          <RuleCard
            key={rule.id}
            rule={rule}
            expanded={expanded === rule.id}
            onExpand={() => setExpanded((e) => (e === rule.id ? null : rule.id))}
            onToggle={() => void toggle(rule)}
            onDelete={() => void remove(rule.id)}
          />
        ))}
      </div>
    </div>
  );
}
