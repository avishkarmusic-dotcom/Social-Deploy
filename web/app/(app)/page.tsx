"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, TrendingUp } from "lucide-react";
import { api, ApiFailure } from "@/lib/api";
import { money } from "@/lib/format";
import type { Metric, Thread } from "@/lib/types";
import { Failure, Mono } from "@/components/ui/primitives";
import { SignalMeter } from "@/components/inbox/SignalMeter";

/**
 * The command centre.
 *
 * Deliberately not a dashboard of totals. The first question every morning is
 * "what should I do first", so the page answers that and nothing else: what's
 * worth the most, and what's decaying fastest.
 */
export default function CommandPage() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [metrics, setMetrics] = useState<Record<string, Metric> | null>(null);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  useEffect(() => {
    Promise.all([api.inbox.list({ sort: "opportunity", limit: 40 }), api.analytics.overview()])
      .then(([page, overview]) => {
        setThreads(page.items);
        setMetrics(overview);
      })
      .catch((e) => e instanceof ApiFailure && setFailure(e));
  }, []);

  const top = [...threads].sort((a, b) => b.opportunity_score - a.opportunity_score).slice(0, 3);
  const decaying = [...threads].sort((a, b) => b.urgency - a.urgency).slice(0, 3);
  const worth = threads.filter((t) => t.opportunity_score >= 60).length;

  const greeting = new Date().toLocaleDateString(undefined, { weekday: "long" });

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8">
      <h1 className="text-2xl font-semibold tracking-tight text-paper">{greeting} morning.</h1>
      <p className="mb-6 text-sm text-quiet">
        {threads.length
          ? `${threads.length} threads waiting. ${worth} of them are worth your morning.`
          : "Nothing waiting. Connect a channel and this page starts working."}
      </p>

      {failure && <Failure message={failure.message} fix={failure.fix} />}

      <SignalMeter threads={threads} />

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-raise p-4">
          <div className="mb-3 flex items-center gap-2">
            <TrendingUp size={13} className="text-mint" />
            <Mono className="text-mint">Worth the most</Mono>
          </div>
          {top.map((t) => (
            <Link
              key={t.id}
              href={`/inbox?thread=${t.id}`}
              className="flex items-start gap-3 border-t border-line-soft py-2.5"
            >
              <span className="min-w-[24px] font-mono text-[13px] text-mint tabular">
                {t.opportunity_score}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] text-paper">{t.sender}</span>
                <span className="block truncate text-xs text-quiet">
                  {t.summary ?? t.snippet}
                </span>
              </span>
            </Link>
          ))}
          {top.length === 0 && <p className="py-6 text-center text-xs text-quiet">Nothing scored yet.</p>}
        </section>

        <section className="rounded-xl border border-line bg-raise p-4">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle size={13} className="text-ember" />
            <Mono className="text-ember">Decaying fastest</Mono>
          </div>
          {decaying.map((t) => (
            <Link
              key={t.id}
              href={`/inbox?thread=${t.id}`}
              className="flex items-start gap-3 border-t border-line-soft py-2.5"
            >
              <Clock size={13} className="mt-0.5 shrink-0 text-ember" />
              <span className="min-w-0">
                <span className="block truncate text-[13px] text-paper">
                  {t.subject ?? t.snippet}
                </span>
                <span className="block truncate text-xs text-quiet">
                  {t.sender} · urgency {t.urgency}
                </span>
              </span>
            </Link>
          ))}
          {decaying.length === 0 && (
            <p className="py-6 text-center text-xs text-quiet">Nothing urgent.</p>
          )}
        </section>
      </div>

      {metrics && (
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Object.entries(metrics).map(([key, m]) => (
            <div key={key} className="rounded-xl border border-line bg-raise p-4">
              <Mono className="text-faint">{m.label}</Mono>
              <p className="mt-1 text-xl font-semibold tracking-tight text-paper tabular">
                {m.value === null
                  ? "—"
                  : key === "pipeline_usd"
                    ? money(m.value)
                    : m.value.toLocaleString()}
              </p>
              {m.confident && m.change_pct !== null && (
                <Mono className={m.change_pct >= 0 ? "text-mint" : "text-ember"}>
                  {m.change_pct >= 0 ? "+" : ""}
                  {m.change_pct}%
                </Mono>
              )}
              {!m.confident && m.note && (
                <p className="mt-1 text-[10px] leading-tight text-faint">{m.note}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
