"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Inbox as InboxIcon, Loader2 } from "lucide-react";
import { api, ApiFailure } from "@/lib/api";
import { useRealtime } from "@/lib/useRealtime";
import type { Thread, ThreadDetail } from "@/lib/types";
import { Chip, Empty, Failure } from "@/components/ui/primitives";
import { ThreadRow } from "@/components/inbox/ThreadRow";
import { ThreadPane } from "@/components/inbox/ThreadPane";

type Filter = "all" | "opportunity" | "urgent" | "unread";

const FILTERS: { id: Filter; tone: "quiet" | "mint" | "ember" }[] = [
  { id: "all", tone: "quiet" },
  { id: "opportunity", tone: "mint" },
  { id: "urgent", tone: "ember" },
  { id: "unread", tone: "quiet" },
];

export default function InboxContent() {
  const params = useSearchParams();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [selected, setSelected] = useState<string | null>(params.get("thread"));
  const [detail, setDetail] = useState<ThreadDetail | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const page = await api.inbox.list({
        sort: filter === "urgent" ? "urgency" : "opportunity",
        min_opportunity: filter === "opportunity" ? 60 : 0,
        limit: 100,
      });
      setThreads(page.items);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    setLoadingDetail(true);
    api.inbox
      .get(selected)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoadingDetail(false));
  }, [selected]);

  useRealtime(null, (event) => {
    if (event.event !== "thread.scored") return;
    const data = event.data as { thread_id: string; opportunity_score: number; urgency: number };
    setThreads((current) =>
      current.map((t) =>
        t.id === data.thread_id
          ? { ...t, opportunity_score: data.opportunity_score, urgency: data.urgency }
          : t,
      ),
    );
  });

  const visible = useMemo(() => {
    if (filter === "urgent") return threads.filter((t) => t.urgency >= 70);
    if (filter === "unread") return threads.filter((t) => t.unread);
    return threads;
  }, [threads, filter]);

  const setState = async (id: string, state: string) => {
    await api.inbox.setState(id, state);
    setThreads((c) => c.filter((t) => t.id !== id));
    setSelected(null);
  };

  return (
    <>
      <section
        className={`${selected ? "hidden lg:flex" : "flex"} w-full shrink-0 flex-col border-r border-line bg-panel lg:w-80`}
        aria-label="Threads"
      >
        <div className="flex gap-1.5 overflow-x-auto border-b border-line px-3 pb-2 pt-3">
          {FILTERS.map(({ id, tone }) => (
            <Chip key={id} tone={tone} active={filter === id} onClick={() => setFilter(id)}>
              {id}
            </Chip>
          ))}
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {failure && (
            <div className="p-2">
              <Failure message={failure.message} fix={failure.fix} />
            </div>
          )}

          {loading && !threads.length && (
            <div className="flex justify-center py-12">
              <Loader2 size={16} className="animate-spin text-faint" />
            </div>
          )}

          {!loading && visible.length === 0 && (
            <Empty icon={InboxIcon} title="No threads" />
          )}

          <div className="divide-y divide-line">
            {visible.map((t) => (
              <ThreadRow
                key={t.id}
                active={selected === t.id}
                thread={t}
                onClick={() => setSelected(t.id)}
                onToggleStar={() => setState(t.id, t.state === "starred" ? "open" : "starred")}
                onArchive={() => setState(t.id, "archived")}
                onSpam={() => setState(t.id, "spam")}
              />
            ))}
          </div>
        </div>
      </section>

      <ThreadPane
        loading={loadingDetail}
        thread={detail}
        onClose={() => setSelected(null)}
        onArchive={() => selected && setState(selected, "archived")}
      />
    </>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<div className="flex justify-center py-12"><Loader2 size={16} className="animate-spin text-faint" /></div>}>
      <InboxContent />
    </Suspense>
  );
}
