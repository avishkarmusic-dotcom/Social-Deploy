"use client";

import type { Thread } from "@/lib/types";
import { Mono } from "@/components/ui/primitives";

/**
 * The header that justifies the product in one glance.
 *
 * Every thread becomes one vertical stripe, sorted by score. The gradient from
 * mint to grey *is* the argument: this is how much of what arrived was worth
 * your morning. No other inbox can draw this chart.
 */
export function SignalMeter({ threads }: { threads: Thread[] }) {
  if (threads.length === 0) return null;
  const worth = threads.filter((t) => t.opportunity_score >= 60).length;
  const pct = Math.round((worth / threads.length) * 100);
  const sorted = [...threads].sort((a, b) => b.opportunity_score - a.opportunity_score);

  return (
    <section
      className="mb-3 rounded-xl border border-line bg-raise p-4"
      aria-label="Signal overview"
    >
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-sm text-quiet">
          <span className="text-2xl font-semibold tracking-tight text-paper tabular">
            {worth}
          </span>{" "}
          of {threads.length} threads are worth acting on
        </p>
        <Mono className="text-mint">{pct}% signal</Mono>
      </div>

      <div className="flex h-8 gap-px overflow-hidden rounded-md">
        {sorted.map((t) => (
          <div
            key={t.id}
            title={`${t.sender} · ${t.opportunity_score}`}
            className={
              t.urgency >= 85 && t.opportunity_score < 50
                ? "flex-1 bg-ember"
                : t.opportunity_score >= 70
                  ? "flex-1 bg-mint"
                  : t.opportunity_score >= 40
                    ? "flex-1 bg-amber"
                    : "flex-1 bg-line"
            }
            style={{ opacity: 0.25 + (t.opportunity_score / 100) * 0.75 }}
          />
        ))}
      </div>

      <div className="mt-2 flex justify-between">
        <Mono className="text-faint">Highest value</Mono>
        <Mono className="text-faint">Noise</Mono>
      </div>
    </section>
  );
}
