"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

/** Machine voice. Anything a model or a provider produced is set in this. */
export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("font-mono text-micro uppercase", className)}>{children}</span>;
}

type Tone = "mint" | "iris" | "ember" | "amber" | "quiet";

const TONE: Record<Tone, string> = {
  mint: "text-mint border-mint/20 bg-mint/[0.08]",
  iris: "text-iris border-iris/20 bg-iris/[0.08]",
  ember: "text-ember border-ember/20 bg-ember/[0.08]",
  amber: "text-amber border-amber/20 bg-amber/[0.08]",
  quiet: "text-quiet border-line bg-line/40",
};

const ACTIVE: Record<Tone, string> = {
  mint: "bg-mint text-ink border-mint",
  iris: "bg-iris text-white border-iris",
  ember: "bg-ember text-ink border-ember",
  amber: "bg-amber text-ink border-amber",
  quiet: "bg-quiet text-ink border-quiet",
};

export function Chip({
  children, tone = "quiet", active, onClick,
}: {
  children: ReactNode; tone?: Tone; active?: boolean; onClick?: () => void;
}) {
  if (!onClick) {
    return (
      <span className={clsx("rounded-md border px-2 py-0.5 font-mono text-micro uppercase", TONE[tone])}>
        {children}
      </span>
    );
  }
  return (
    <button
      onClick={onClick}
      className={clsx(
        "rounded-md border px-2 py-0.5 font-mono text-micro uppercase transition-colors",
        active ? ACTIVE[tone] : TONE[tone],
      )}
    >
      {children}
    </button>
  );
}

export function Button({
  children, onClick, primary, disabled, small, type = "button",
}: {
  children: ReactNode; onClick?: () => void; primary?: boolean;
  disabled?: boolean; small?: boolean; type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "rounded-lg border font-medium transition-all disabled:cursor-not-allowed disabled:opacity-45",
        small ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm",
        primary
          ? "border-iris bg-iris text-white hover:brightness-110"
          : "border-line bg-raise text-paper hover:border-quiet",
      )}
    >
      {children}
    </button>
  );
}

/**
 * The signature element: a vertical bar whose fill height is the opportunity
 * score. It sits on every thread row, so scanning the inbox is scanning a bar
 * chart you never have to read.
 */
export function SignalRail({ score, negative }: { score: number; negative?: boolean }) {
  const colour = negative
    ? "bg-ember"
    : score >= 70 ? "bg-mint" : score >= 40 ? "bg-amber" : "bg-faint";
  return (
    <div
      className="w-1 shrink-0 self-stretch rounded-full bg-line-soft"
      role="img"
      aria-label={`Opportunity score ${score} out of 100`}
    >
      <div
        className={clsx("w-1 rounded-full transition-all duration-500", colour)}
        style={{ height: `${Math.max(score, 6)}%` }}
      />
    </div>
  );
}

/** Empty states are an invitation to act, never an apology. */
export function Empty({
  icon, title, action,
}: { icon: ReactNode; title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-8 py-16 text-center">
      <div className="mb-3 text-faint">{icon}</div>
      <p className="max-w-xs text-sm text-quiet">{title}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Failure({ message, fix }: { message: string; fix: string }) {
  return (
    <div className="rounded-xl border border-ember/30 bg-ember/[0.06] px-4 py-3">
      <p className="text-sm text-paper">{message}</p>
      <p className="mt-1 text-xs text-quiet">{fix}</p>
    </div>
  );
}
