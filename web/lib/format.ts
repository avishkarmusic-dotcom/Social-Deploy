/** Formatting the interface leans on. Kept together so tone stays consistent. */

export function relativeTime(iso: string): string {
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h`;
  if (mins < 60 * 24 * 7)
    return then.toLocaleDateString(undefined, { weekday: "short" });
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Compact money, because a sidebar has no room for eleven digits. */
export function money(usd: number | null): string | null {
  if (usd === null || usd === undefined) return null;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
  if (usd >= 1_000) return `$${Math.round(usd / 1000)}K`;
  return `$${Math.round(usd)}`;
}

export function initials(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/** Category labels read as English, not as enum values. */
export function categoryLabel(c: string | null): string {
  if (!c) return "";
  return c.replace(/_/g, " ");
}
