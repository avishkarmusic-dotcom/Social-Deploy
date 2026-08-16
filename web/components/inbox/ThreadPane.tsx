"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Archive, Check, Copy, CornerUpLeft, Inbox, Loader2, Sparkles, Star, Wand2,
} from "lucide-react";
import { api, ApiFailure } from "@/lib/api";
import { channel } from "@/lib/channels";
import { relativeTime } from "@/lib/format";
import type { ThreadDetail, Tone } from "@/lib/types";
import { Button, Chip, Empty, Failure, Mono } from "@/components/ui/primitives";

const TONES: Tone[] = ["professional", "casual", "confident", "founder", "sales", "support"];

export function ThreadPane({
  thread, loading, onBack, onStateChange,
}: {
  thread: ThreadDetail | null;
  loading: boolean;
  onBack: () => void;
  onStateChange: (id: string, state: string) => void;
}) {
  const [tone, setTone] = useState<Tone>("professional");
  const [draft, setDraft] = useState("");
  const [writing, setWriting] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  useEffect(() => {
    setDraft("");
    setFailure(null);
  }, [thread?.id]);

  const write = useCallback(
    async (next: Tone) => {
      if (!thread) return;
      setTone(next);
      setWriting(true);
      setFailure(null);
      setDraft("");
      try {
        const result = await api.inbox.draft(thread.id, { tone: next });
        setDraft(result.body);
      } catch (e) {
        if (e instanceof ApiFailure) setFailure(e);
      } finally {
        setWriting(false);
      }
    },
    [thread],
  );

  if (!thread && !loading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-panel">
        <Empty icon={<Inbox size={28} />} title="Pick a thread to see what it's worth." />
      </div>
    );
  }
  if (!thread) {
    return (
      <div className="flex flex-1 items-center justify-center bg-panel">
        <Loader2 size={18} className="animate-spin text-faint" />
      </div>
    );
  }

  const { Icon, hue, label } = channel(thread.channel);
  const alarming = thread.urgency >= 85 && thread.opportunity_score < 50;

  return (
    <article className="flex-1 overflow-y-auto bg-panel">
      <header className="sticky top-0 z-10 border-b border-line bg-panel/95 px-5 py-4 backdrop-blur">
        <div className="mb-2 flex items-center gap-2">
          <button onClick={onBack} className="-ml-1 p-1 text-quiet lg:hidden" aria-label="Back">
            <CornerUpLeft size={16} />
          </button>
          <Icon size={13} style={{ color: hue }} />
          <Mono className="text-faint">
            {label} · {relativeTime(thread.last_message_at)}
          </Mono>
          <div className="ml-auto flex gap-1">
            <button className="rounded-md p-1.5 text-faint hover:text-paper" aria-label="Star">
              <Star size={14} />
            </button>
            <button
              onClick={() => onStateChange(thread.id, "archived")}
              className="rounded-md p-1.5 text-faint hover:text-paper"
              aria-label="Archive"
            >
              <Archive size={14} />
            </button>
          </div>
        </div>
        <h1 className="text-lg font-semibold leading-snug tracking-tight text-paper">
          {thread.subject ?? "(no subject)"}
        </h1>
        <p className="mt-0.5 text-[13px] text-quiet">{thread.sender}</p>
      </header>

      <div className="px-5 py-4">
        {/* The AI verdict. The only place iris appears in the reading view. */}
        {thread.summary && (
          <section className="glow mb-5 rounded-xl border border-iris/20 p-4">
            <div className="mb-2.5 flex items-center gap-2">
              <Sparkles size={12} className="text-iris" />
              <Mono className="text-iris">Read before you did</Mono>
            </div>
            <p className="mb-3 text-[13px] leading-relaxed text-paper">{thread.summary}</p>

            <div className="mb-3 flex gap-4">
              {(
                [
                  ["Opportunity", thread.opportunity_score, "bg-mint text-mint"],
                  ["Urgency", thread.urgency, alarming ? "bg-ember text-ember" : "bg-amber text-amber"],
                ] as const
              ).map(([label, value, colour]) => (
                <div key={label} className="flex-1">
                  <Mono className="text-faint">{label}</Mono>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1 flex-1 rounded-full bg-line-soft">
                      <div
                        className={`h-1 rounded-full transition-all duration-700 ${colour.split(" ")[0]}`}
                        style={{ width: `${value}%` }}
                      />
                    </div>
                    <Mono className={colour.split(" ")[1]}>{value}</Mono>
                  </div>
                </div>
              ))}
            </div>

            {thread.action_items.length > 0 && (
              <ul className="space-y-1.5">
                {thread.action_items.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-xs text-quiet">
                    <Check size={12} className="mt-0.5 shrink-0 text-mint" />
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        <div className="mb-6 space-y-4">
          {thread.messages.map((m) => (
            <div key={m.id}>
              <Mono className="text-faint">
                {m.author} · {relativeTime(m.sent_at)}
              </Mono>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-paper">
                {m.body}
              </p>
            </div>
          ))}
        </div>

        <section className="overflow-hidden rounded-xl border border-line bg-raise">
          <div className="flex gap-1.5 overflow-x-auto border-b border-line px-3 py-2.5">
            {TONES.map((t) => (
              <Chip key={t} tone="iris" active={tone === t} onClick={() => write(t)}>
                {t}
              </Chip>
            ))}
          </div>

          <label className="sr-only" htmlFor="reply">Your reply</label>
          <textarea
            id="reply"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={writing ? "" : "Pick a tone above, or write it yourself."}
            rows={draft ? Math.min(draft.split("\n").length + 3, 14) : 4}
            className="w-full resize-none bg-transparent px-4 py-3 text-[13px] leading-relaxed text-paper outline-none placeholder:text-faint"
          />

          {writing && !draft && (
            <div className="flex items-center gap-2 px-4 pb-3">
              <Loader2 size={12} className="animate-spin text-iris" />
              <Mono className="text-iris">Writing in your voice…</Mono>
            </div>
          )}
          {failure && (
            <div className="px-4 pb-3">
              <Failure message={failure.message} fix={failure.fix} />
            </div>
          )}

          <div className="flex items-center gap-2 border-t border-line px-3 py-2.5">
            <Button primary small disabled={!draft}>Send reply</Button>
            <Button small disabled={!draft} onClick={() => setDraft("")}>Clear</Button>
            <button
              disabled={!draft}
              onClick={() => navigator.clipboard?.writeText(draft)}
              className="ml-auto p-1.5 text-faint disabled:opacity-40 hover:text-paper"
              aria-label="Copy draft"
            >
              <Copy size={14} />
            </button>
          </div>
        </section>
      </div>
    </article>
  );
}
