"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, Clock, ExternalLink, Loader2, RefreshCw,
  User, Users,
} from "lucide-react";
import clsx from "clsx";
import { api, ApiFailure } from "@/lib/api";
import type { Contact, TimelineEntry } from "@/lib/types";
import { relativeTime, initials, categoryLabel } from "@/lib/format";
import { Button, Chip, Empty, Failure, Mono } from "@/components/ui/primitives";

type Sort = "decay_risk" | "strength" | "importance" | "recent" | "name";

const SORTS: { id: Sort; label: string }[] = [
  { id: "decay_risk", label: "Decay risk" },
  { id: "strength",   label: "Strength" },
  { id: "importance", label: "Importance" },
  { id: "recent",     label: "Recent" },
  { id: "name",       label: "Name" },
];

/* ── Strength bar ─────────────────────────────────────────────────────── */
function StrengthBar({ value }: { value: number }) {
  const colour =
    value >= 65 ? "bg-mint" : value >= 35 ? "bg-amber" : "bg-ember";
  return (
    <div className="mt-1 h-1 w-20 rounded-full bg-line-soft">
      <div
        className={clsx("h-1 rounded-full transition-all duration-500", colour)}
        style={{ width: `${value}%` }}
      />
    </div>
  );
}

/* ── Contact row ─────────────────────────────────────────────────────── */
function ContactRow({
  contact,
  active,
  onClick,
}: {
  contact: Contact;
  active: boolean;
  onClick: () => void;
}) {
  const overdue =
    contact.next_followup_at &&
    new Date(contact.next_followup_at) < new Date();

  return (
    <button
      onClick={onClick}
      aria-current={active}
      className={clsx(
        "flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition-all",
        active ? "border-line bg-raise" : "border-transparent hover:bg-raise/60",
      )}
    >
      {/* Avatar */}
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
        style={{
          background: contact.is_stale
            ? "rgb(var(--ember) / 0.12)"
            : "rgb(var(--iris) / 0.12)",
          color: contact.is_stale
            ? "rgb(var(--ember))"
            : "rgb(var(--iris))",
        }}
      >
        {initials(contact.display_name)}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-paper">
            {contact.display_name}
          </span>
          {overdue && (
            <AlertTriangle
              size={11}
              className="shrink-0 text-ember"
              aria-label="Follow-up overdue"
            />
          )}
        </div>
        <Mono className="text-faint">
          {[contact.company, ...contact.tags.slice(0, 2)]
            .filter(Boolean)
            .join(" · ")
            .toUpperCase()}
        </Mono>
      </div>

      <div className="shrink-0 text-right">
        <StrengthBar value={contact.relationship_strength} />
        <Mono className="mt-1 text-faint">
          {contact.days_silent !== null
            ? `${contact.days_silent}d silent`
            : "—"}
        </Mono>
      </div>
    </button>
  );
}

/* ── Contact detail pane ─────────────────────────────────────────────── */
function ContactPane({
  contact,
  onBack,
}: {
  contact: Contact | null;
  onBack: () => void;
}) {
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [loadingTl, setLoadingTl] = useState(false);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!contact) { setTimeline([]); return; }
    setLoadingTl(true);
    api.contacts
      .timeline(contact.id)
      .then(setTimeline)
      .finally(() => setLoadingTl(false));
    setNote(contact.notes ?? "");
  }, [contact?.id]);

  const saveNote = async () => {
    if (!contact) return;
    setSaving(true);
    try {
      await api.contacts.update(contact.id, { notes: note });
    } finally {
      setSaving(false);
    }
  };

  if (!contact) {
    return (
      <div className="flex flex-1 items-center justify-center bg-panel">
        <Empty icon={<User size={24} />} title="Pick a person to see the full picture." />
      </div>
    );
  }

  return (
    <article className="flex-1 overflow-y-auto bg-panel">
      <header className="sticky top-0 z-10 border-b border-line bg-panel/95 px-5 py-4 backdrop-blur">
        <button onClick={onBack} className="-ml-1 mb-2 p-1 text-quiet lg:hidden" aria-label="Back">
          ←
        </button>
        <div className="flex items-start gap-3">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold"
            style={{
              background: "rgb(var(--iris) / 0.12)",
              color: "rgb(var(--iris))",
            }}
          >
            {initials(contact.display_name)}
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-paper">
              {contact.display_name}
            </h1>
            <Mono className="text-faint">
              {[contact.company, contact.title].filter(Boolean).join(" · ").toUpperCase()}
            </Mono>
          </div>
        </div>
      </header>

      <div className="space-y-6 px-5 py-4">
        {/* Scores */}
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[
            ["Importance",   contact.importance,            "text-iris"],
            ["Strength",     contact.relationship_strength, "text-mint"],
            ["Days silent",  contact.days_silent ?? "—",   "text-quiet"],
          ].map(([label, value, cls]) => (
            <div key={label as string} className="rounded-lg border border-line bg-raise p-3">
              <Mono className="text-faint">{label as string}</Mono>
              <p className={clsx("mt-1 text-xl font-semibold tabular", cls)}>
                {value}
              </p>
            </div>
          ))}
        </section>

        {/* Tags */}
        {contact.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {contact.tags.map((t) => (
              <Chip key={t}>{t}</Chip>
            ))}
          </div>
        )}

        {/* Follow-up */}
        {contact.next_followup_at && (
          <div className="flex items-center gap-2 rounded-lg border border-amber/25 bg-amber/[0.06] px-3 py-2">
            <Clock size={13} className="text-amber" />
            <Mono className="text-amber">
              Follow up {relativeTime(contact.next_followup_at)}
            </Mono>
          </div>
        )}

        {/* Notes */}
        <section>
          <Mono className="mb-2 text-faint">Notes</Mono>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            className="w-full resize-none rounded-lg border border-line bg-raise px-3 py-2.5 text-[13px] leading-relaxed text-paper outline-none placeholder:text-faint focus:border-iris"
            placeholder="Anything worth remembering about this relationship."
          />
          <div className="mt-2">
            <Button small onClick={saveNote} disabled={saving}>
              {saving ? "Saving…" : "Save note"}
            </Button>
          </div>
        </section>

        {/* Timeline */}
        <section>
          <Mono className="mb-3 text-faint">History</Mono>
          {loadingTl && (
            <div className="flex justify-center py-6">
              <Loader2 size={14} className="animate-spin text-faint" />
            </div>
          )}
          {!loadingTl && timeline.length === 0 && (
            <p className="text-sm text-quiet">No conversation history yet.</p>
          )}
          <div className="space-y-3">
            {timeline.map((entry) => (
              <div
                key={`${entry.thread_id}-${entry.sent_at}`}
                className="rounded-lg border border-line bg-raise px-3.5 py-3"
              >
                <div className="mb-1 flex items-center gap-2">
                  <Mono className="text-faint">{entry.channel?.toUpperCase()}</Mono>
                  <Mono className="ml-auto text-faint">{relativeTime(entry.sent_at)}</Mono>
                  {entry.direction === "outbound" && (
                    <Mono className="text-mint">You</Mono>
                  )}
                </div>
                <p className="line-clamp-2 text-[13px] leading-relaxed text-quiet">
                  {entry.body}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </article>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */
export default function PeoplePage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [sort, setSort] = useState<Sort>("decay_risk");
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const result = await api.contacts.list({ sort });
      setContacts(result);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setLoading(false);
    }
  }, [sort]);

  useEffect(() => { void load(); }, [load]);

  const current = contacts.find((c) => c.id === selected) ?? null;

  return (
    <>
      {/* List panel */}
      <section
        className={clsx(
          "flex w-full shrink-0 flex-col border-r border-line bg-panel lg:w-80",
          selected ? "hidden lg:flex" : "flex",
        )}
        aria-label="Contacts"
      >
        <div className="flex items-center gap-2 border-b border-line px-3 py-3">
          <Users size={14} className="text-faint" />
          <Mono className="text-faint">Sort:</Mono>
          <div className="flex gap-1 overflow-x-auto">
            {SORTS.map((s) => (
              <Chip
                key={s.id}
                tone="quiet"
                active={sort === s.id}
                onClick={() => setSort(s.id)}
              >
                {s.label}
              </Chip>
            ))}
          </div>
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {failure && (
            <div className="p-2">
              <Failure message={failure.message} fix={failure.fix} />
            </div>
          )}

          {loading && (
            <div className="flex justify-center py-12">
              <Loader2 size={16} className="animate-spin text-faint" />
            </div>
          )}

          {!loading && contacts.length === 0 && !failure && (
            <Empty
              icon={<Users size={22} />}
              title="Nobody here yet. Contacts are created automatically as messages arrive."
            />
          )}

          {contacts.map((c) => (
            <ContactRow
              key={c.id}
              contact={c}
              active={selected === c.id}
              onClick={() => setSelected(c.id)}
            />
          ))}
        </div>
      </section>

      {/* Detail panel */}
      <div className={clsx("flex min-w-0 flex-1", selected ? "flex" : "hidden lg:flex")}>
        <ContactPane contact={current} onBack={() => setSelected(null)} />
      </div>
    </>
  );
}

/* Extend Contact type locally until the API generates it */
declare module "@/lib/types" {
  interface Contact {
    notes?: string | null;
    is_stale?: boolean;
  }
}
