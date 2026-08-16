"use client";

import { useEffect, useState } from "react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { AlertCircle, Loader2, TrendingUp } from "lucide-react";
import { api, ApiFailure } from "@/lib/api";
import type { ChannelYield, GrowthPoint, Metric } from "@/lib/types";
import { money } from "@/lib/format";
import { Empty, Failure, Mono } from "@/components/ui/primitives";

/* ── Metric card ─────────────────────────────────────────────────────── */
function MetricCard({ m, slug }: { m: Metric; slug: string }) {
  const formatValue = () => {
    if (m.value === null) return "—";
    if (slug === "pipeline_usd") return money(m.value) ?? "—";
    if (slug === "response_time") return `${m.value}h`;
    if (slug === "signal_ratio") return `${m.value}%`;
    return m.value.toLocaleString();
  };

  return (
    <div className="rounded-xl border border-line bg-raise p-4">
      <Mono className="text-faint">{m.label}</Mono>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-paper tabular">
        {formatValue()}
      </p>
      {m.confident && m.change_pct !== null && (
        <Mono className={m.change_pct >= 0 ? "text-mint" : "text-ember"}>
          {m.change_pct >= 0 ? "+" : ""}{m.change_pct}%
        </Mono>
      )}
      {!m.confident && m.note && (
        <p className="mt-1 text-[11px] leading-tight text-faint">{m.note}</p>
      )}
    </div>
  );
}

/* ── Custom tooltip ──────────────────────────────────────────────────── */
function ChartTip({ active, payload, label }: Record<string, unknown>) {
  if (!active || !payload) return null;
  return (
    <div className="rounded-lg border border-line bg-raise px-3 py-2 text-xs">
      <Mono className="mb-1 text-faint">{String(label)}</Mono>
      {(payload as { name: string; value: number }[]).map((p) => (
        <div key={p.name} className="flex justify-between gap-4">
          <span className="text-quiet">{p.name}</span>
          <span className="font-semibold text-paper tabular">{p.value}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */
export default function DataPage() {
  const [overview, setOverview]   = useState<Record<string, Metric> | null>(null);
  const [channels, setChannels]   = useState<ChannelYield[]>([]);
  const [growth, setGrowth]       = useState<GrowthPoint[]>([]);
  const [failure, setFailure]     = useState<ApiFailure | null>(null);
  const [loading, setLoading]     = useState(true);

  useEffect(() => {
    Promise.all([
      api.analytics.overview(),
      api.analytics.channels(),
      api.analytics.growth(),
    ])
      .then(([ov, ch, gr]) => {
        setOverview(ov);
        setChannels(ch);
        setGrowth(gr);
      })
      .catch((e) => e instanceof ApiFailure && setFailure(e))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 size={18} className="animate-spin text-faint" />
      </div>
    );
  }

  if (failure) {
    return (
      <div className="flex-1 px-5 py-6 lg:px-8">
        <Failure message={failure.message} fix={failure.fix} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8">
      <h1 className="mb-1 text-xl font-semibold tracking-tight text-paper">Data</h1>
      <p className="mb-6 text-sm text-quiet">
        Reach is vanity until it becomes a thread in the inbox.
      </p>

      {/* Overview metrics */}
      {overview && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Object.entries(overview).map(([slug, m]) => (
            <MetricCard key={slug} slug={slug} m={m} />
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Growth chart */}
        {growth.length > 0 ? (
          <section className="rounded-xl border border-line bg-raise p-4">
            <Mono className="mb-3 text-faint">
              Weekly volume vs opportunities
            </Mono>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={growth}>
                  <defs>
                    <linearGradient id="grad-opp" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="rgb(var(--iris))" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="rgb(var(--iris))" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="grad-vol" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="rgb(var(--quiet))" stopOpacity={0.15} />
                      <stop offset="100%" stopColor="rgb(var(--quiet))" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="2 4"
                    stroke="rgb(var(--line))"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="week"
                    tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "rgb(var(--faint))" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "rgb(var(--faint))" }}
                    axisLine={false}
                    tickLine={false}
                    width={30}
                  />
                  <Tooltip content={<ChartTip />} />
                  <Area
                    type="monotone"
                    dataKey="threads"
                    name="Volume"
                    stroke="rgb(var(--quiet))"
                    strokeWidth={1.5}
                    fill="url(#grad-vol)"
                  />
                  <Area
                    type="monotone"
                    dataKey="opportunities"
                    name="Opportunities"
                    stroke="rgb(var(--iris))"
                    strokeWidth={2}
                    fill="url(#grad-opp)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>
        ) : (
          <section className="rounded-xl border border-line bg-raise p-4">
            <Mono className="mb-3 text-faint">Weekly volume vs opportunities</Mono>
            <Empty
              icon={<TrendingUp size={20} />}
              title="Not enough data yet. Keep using the inbox and this fills in."
            />
          </section>
        )}

        {/* Channel yield */}
        {channels.length > 0 ? (
          <section className="rounded-xl border border-line bg-raise p-4">
            <Mono className="mb-3 text-faint">
              Where opportunities actually come from
            </Mono>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={channels} layout="vertical">
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="channel"
                    tick={{
                      fontSize: 10,
                      fontFamily: "var(--font-mono)",
                      fill: "rgb(var(--faint))",
                    }}
                    axisLine={false}
                    tickLine={false}
                    width={72}
                  />
                  <Tooltip content={<ChartTip />} cursor={{ fill: "rgb(var(--line-soft))" }} />
                  <Bar dataKey="opportunities" name="Opportunities" radius={[0, 4, 4, 0]} barSize={12}>
                    {channels.map((_, i) => (
                      <Cell
                        key={i}
                        fill={i === 0 ? "rgb(var(--mint))" : `rgb(var(--mint) / ${0.7 - i * 0.08})`}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        ) : (
          <section className="rounded-xl border border-line bg-raise p-4">
            <Mono className="mb-3 text-faint">Where opportunities come from</Mono>
            <Empty
              icon={<TrendingUp size={20} />}
              title="Connect more sources and this chart becomes meaningful."
            />
          </section>
        )}
      </div>

      {/* Attribution note */}
      <p className="mt-6 text-[11px] leading-relaxed text-faint">
        Pipeline values are first-touch estimates extracted from message text.
        Useful for ranking where your attention pays off — not for forecasting
        revenue.
      </p>
    </div>
  );
}
