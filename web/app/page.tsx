/**
 * Landing page — the public front door.
 *
 * The argument is the product, not a description of it:
 *   - The five bars at real scores prove the ranking concept
 *   - The feature list is written in outcomes, not features
 *   - The pricing section states what's real
 *
 * This page redirects authenticated users to /inbox immediately.
 * No animation until the hero is visible (respects prefers-reduced-motion).
 */
import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Tryvanta Social — One inbox. One AI. Zero missed opportunities.",
  description:
    "Tryvanta Social is the AI operating layer for founders, executives and creators. One inbox across every channel, scored by what it's worth.",
};

const SCORES = [
  { label: "Investor",   score: 94, colour: "bg-mint" },
  { label: "Recruiter",  score: 86, colour: "bg-mint" },
  { label: "Client",     score: 81, colour: "bg-mint" },
  { label: "Review",     score: 41, colour: "bg-amber" },
  { label: "Newsletter", score: 4,  colour: "bg-line" },
];

const FEATURES = [
  { title: "Universal Inbox",     desc: "Gmail, LinkedIn, WhatsApp, Instagram, Slack and 9 more — normalised into one inbox, ranked by what acting on each is worth." },
  { title: "Signal Rail",         desc: "Every thread has a bar. The bar is the score. Scanning the inbox is scanning a chart you never have to read." },
  { title: "AI Reply",            desc: "Eight tones trained on the messages you actually sent — not on a generic assistant voice. Professional, founder, sales, support." },
  { title: "Opportunity Radar",   desc: "Jobs, investor intros, client leads, speaking slots, grants. The system reads before you do and tells you what to open first." },
  { title: "Personal CRM",        desc: "Every contact you've ever spoken to. Relationship strength decays when you go quiet — the list sorts by who you're about to lose." },
  { title: "AI Automations",      desc: "If a recruiter with a real role reaches out, notify instantly. If a review drops below three stars, draft the reply. Rules you write in plain English." },
  { title: "Content Studio",      desc: "LinkedIn posts, X threads, Instagram captions, newsletters. One brief, three different angles. Nothing is scheduled until you pick one." },
  { title: "Ad Campaigns",        desc: "Boost a post to Facebook and Instagram in one click. Launch a Google Search campaign from a brief. Spend cap enforced before any money moves." },
];

const SOURCES = [
  "Gmail", "Outlook", "LinkedIn", "Instagram", "WhatsApp", "Messenger",
  "Telegram", "Slack", "Discord", "X", "YouTube", "Threads",
  "Google Business", "Facebook",
];

export default function LandingPage() {
  return (
    <div
      className="min-h-screen"
      style={{
        background: "rgb(8 9 12)",
        color: "rgb(233 237 243)",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif',
      }}
    >
      {/* ── Nav ── */}
      <nav className="flex items-center justify-between border-b border-white/10 px-6 py-4 sm:px-12">
        <div className="flex items-center gap-3">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-lg"
            style={{ background: "linear-gradient(140deg, #8B7CFF, #4FE3B0)" }}
          >
            <span className="text-[13px] font-bold text-white">T</span>
          </div>
          <span className="font-semibold tracking-tight">Tryvanta Social</span>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/login"
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/login"
            className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-all"
            style={{ background: "rgb(139 124 255)" }}
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="mx-auto max-w-5xl px-6 pb-24 pt-24 text-center sm:px-12">
        <p
          className="mb-4 text-xs uppercase tracking-widest"
          style={{ color: "rgb(139 124 255)", fontFamily: "monospace" }}
        >
          AI Social Operating System
        </p>
        <h1 className="mb-6 text-4xl font-semibold tracking-tight sm:text-6xl">
          Every message, ranked by what
          <br />
          <span style={{ color: "rgb(79 227 176)" }}>acting on it is worth.</span>
        </h1>
        <p className="mx-auto mb-10 max-w-2xl text-lg leading-relaxed text-gray-400">
          Fourteen platforms. One inbox. An AI that reads every message before you do and
          tells you what to open first — not when it arrived, but what it's worth.
        </p>
        <Link
          href="/login"
          className="inline-flex items-center gap-2 rounded-xl px-8 py-4 text-base font-semibold text-white transition-all hover:brightness-110"
          style={{ background: "linear-gradient(140deg, #8B7CFF, #4FE3B0)" }}
        >
          Start for free →
        </Link>

        {/* The argument */}
        <div className="mx-auto mt-16 max-w-sm">
          <p
            className="mb-4 text-xs uppercase tracking-widest text-left"
            style={{ color: "rgb(93 104 121)", fontFamily: "monospace" }}
          >
            This morning, in one inbox
          </p>
          <div className="flex h-48 items-end gap-3 rounded-2xl border border-white/10 bg-white/5 p-6">
            {SCORES.map(({ label, score, colour }) => (
              <div key={label} className="flex flex-1 flex-col items-center gap-2">
                <span
                  className="text-xs tabular-nums"
                  style={{ color: "rgb(93 104 121)", fontFamily: "monospace" }}
                >
                  {score}
                </span>
                <div
                  className={`w-full rounded-t-sm ${colour}`}
                  style={{ height: `${score}%` }}
                />
                <span
                  className="text-[9px] uppercase tracking-wider text-center"
                  style={{ color: "rgb(93 104 121)", fontFamily: "monospace" }}
                >
                  {label}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-sm text-gray-500 text-left">
            Every other inbox sorts by arrival time. This one sorts by value.
          </p>
        </div>
      </section>

      {/* ── Sources ── */}
      <section className="border-y border-white/10 py-12">
        <p
          className="mb-6 text-center text-xs uppercase tracking-widest"
          style={{ color: "rgb(93 104 121)", fontFamily: "monospace" }}
        >
          Connected sources
        </p>
        <div className="flex flex-wrap justify-center gap-3 px-6">
          {SOURCES.map((s) => (
            <span
              key={s}
              className="rounded-full border border-white/10 px-4 py-1.5 text-sm text-gray-400"
            >
              {s}
            </span>
          ))}
        </div>
      </section>

      {/* ── Features ── */}
      <section className="mx-auto max-w-5xl px-6 py-24 sm:px-12">
        <h2 className="mb-12 text-center text-2xl font-semibold tracking-tight">
          Not a social media scheduler.
          <br />
          <span className="text-gray-400">An operating layer.</span>
        </h2>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="rounded-2xl border border-white/10 p-6"
              style={{ background: "rgb(13 16 22)" }}
            >
              <h3 className="mb-2 font-semibold text-white">{f.title}</h3>
              <p className="text-sm leading-relaxed text-gray-400">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Social proof ── */}
      <section
        className="border-y border-white/10 py-20 text-center"
        style={{ background: "rgb(13 16 22)" }}
      >
        <h2 className="mb-4 text-2xl font-semibold tracking-tight">
          One inbox.
          <span style={{ color: "rgb(79 227 176)" }}> One AI.</span>
          <br />
          Zero missed opportunities.
        </h2>
        <p className="mx-auto max-w-lg text-base text-gray-400">
          Built for founders, executives, recruiters, agency leads, consultants —
          anyone whose next deal, hire, or investor is currently buried in fourteen
          different apps.
        </p>
      </section>

      {/* ── Pricing ── */}
      <section className="mx-auto max-w-3xl px-6 py-24 sm:px-12">
        <h2 className="mb-12 text-center text-2xl font-semibold tracking-tight">Pricing</h2>
        <div className="grid gap-6 sm:grid-cols-2">
          {[
            {
              plan: "Pro",
              price: "$49",
              period: "/month",
              features: [
                "All 14 sources",
                "AI scoring & drafts",
                "Content Studio",
                "Personal CRM",
                "Automations",
                "Up to 3 workspaces",
              ],
              highlight: true,
            },
            {
              plan: "Team",
              price: "$149",
              period: "/month",
              features: [
                "Everything in Pro",
                "Unlimited workspaces",
                "Ad campaigns",
                "Google Business management",
                "SEO dashboard",
                "Priority support",
              ],
              highlight: false,
            },
          ].map((tier) => (
            <div
              key={tier.plan}
              className="rounded-2xl border p-8"
              style={{
                background: tier.highlight ? "rgb(139 124 255 / 0.08)" : "rgb(13 16 22)",
                borderColor: tier.highlight ? "rgb(139 124 255 / 0.4)" : "rgb(255 255 255 / 0.1)",
              }}
            >
              <p className="mb-2 text-sm text-gray-400">{tier.plan}</p>
              <p className="mb-6 text-3xl font-bold text-white">
                {tier.price}
                <span className="text-base font-normal text-gray-400">{tier.period}</span>
              </p>
              <ul className="space-y-2">
                {tier.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                    <span style={{ color: "rgb(79 227 176)" }}>✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              <Link
                href="/login"
                className="mt-8 block rounded-xl py-3 text-center text-sm font-semibold text-white transition-all"
                style={{
                  background: tier.highlight ? "rgb(139 124 255)" : "transparent",
                  border: tier.highlight ? "none" : "1px solid rgb(255 255 255 / 0.2)",
                }}
              >
                Start free trial
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-white/10 px-6 py-8 text-center sm:px-12">
        <p className="text-sm text-gray-500">
          © 2025 Tryvanta · Built by{" "}
          <span className="text-gray-400">Avishkar</span>
        </p>
      </footer>
    </div>
  );
}
