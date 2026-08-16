"use client";

import clsx from "clsx";
import { channel } from "@/lib/channels";
import { categoryLabel, relativeTime } from "@/lib/format";
import type { Thread } from "@/lib/types";
import { Chip, Mono, SignalRail } from "@/components/ui/primitives";

export function ThreadRow({
  thread, active, index, onSelect,
}: {
  thread: Thread; active: boolean; index: number; onSelect: () => void;
}) {
  const { Icon, hue, label } = channel(thread.channel);
  const alarming = thread.urgency >= 85 && thread.opportunity_score < 50;

  return (
    <button
      onClick={onSelect}
      aria-current={active}
      className={clsx(
        "flex w-full animate-rise gap-3 rounded-xl border px-3 py-3 text-left transition-all",
        active ? "border-line bg-raise" : "border-transparent hover:bg-raise/60",
      )}
      style={{ animationDelay: `${Math.min(index, 12) * 28}ms` }}
    >
      <SignalRail score={thread.opportunity_score} negative={alarming} />

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <Icon size={12} style={{ color: hue }} className="shrink-0" aria-label={label} />
          <span
            className={clsx(
              "truncate text-sm",
              thread.unread ? "font-medium text-paper" : "text-quiet",
            )}
          >
            {thread.sender}
          </span>
          {thread.unread && (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-iris" aria-label="Unread" />
          )}
          <Mono className="ml-auto shrink-0 text-faint">
            {relativeTime(thread.last_message_at)}
          </Mono>
        </div>

        <p
          className={clsx(
            "mb-1.5 truncate text-[13px]",
            thread.unread ? "text-paper" : "text-quiet",
          )}
        >
          {thread.subject ?? thread.snippet}
        </p>

        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone={alarming ? "ember" : thread.opportunity_score >= 70 ? "mint" : "quiet"}>
            {thread.opportunity_score}
          </Chip>
          <Mono className="text-faint">{categoryLabel(thread.category)}</Mono>
          {thread.opportunity_kind && (
            <Mono className="text-mint">· {categoryLabel(thread.opportunity_kind)}</Mono>
          )}
        </div>
      </div>
    </button>
  );
}
