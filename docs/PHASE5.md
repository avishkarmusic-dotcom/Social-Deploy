# Phase 5 — the frontend

Next.js 15, App Router, React 19. The point where this stops being a repo and
starts being something you open every morning.

## The design thesis, stated once

**Machines speak in mono. Humans speak in sans.**

Every score, channel label, timestamp, category and status is set in the
monospace face. Every subject line, message body and drafted reply is set in
the sans face. You can tell at a glance which parts of the screen a model
produced and which parts a person wrote — without a single "AI generated"
badge, which is the thing every competitor reaches for.

Colour carries meaning, never decoration. Three accents, one job each:

| | |
|---|---|
| **mint** | opportunity, value, worth your morning |
| **ember** | urgency, decaying, public and angry |
| **iris** | the AI is speaking |

Everything else is greyscale, deliberately. On a screen where a number decides
what you do next, a stray accent colour is a lie.

## The signature element

The **Signal Rail** — a vertical bar on every thread row whose fill height is
the opportunity score. Scanning the inbox is scanning a bar chart you never
have to read.

Its companion is the **Signal Meter** on the command page: every waiting thread
as one stripe, sorted by score, mint fading to grey. That gradient *is* the
product argument. No other inbox can draw that chart, because no other inbox
knows what its messages are worth.

## What landed

```
app/
  layout.tsx                  root, theme class on <html>
  (auth)/login/page.tsx       magic-link sign-in
  (app)/layout.tsx            shell wrapper
  (app)/page.tsx              command centre
  (app)/inbox/page.tsx        universal inbox + thread pane
components/
  ui/primitives.tsx           Mono, Chip, Button, SignalRail, Empty, Failure
  inbox/SignalMeter.tsx       the signature chart
  inbox/ThreadRow.tsx         row with rail, channel mark, score, category
  inbox/ThreadPane.tsx        verdict card, transcript, tone composer
  shell/Shell.tsx             rail, header, ⌘K, theme, mobile nav
  shell/Assistant.tsx         ask-your-inbox panel
  shell/CommandPalette.tsx    debounced search + navigation
lib/
  api.ts                      typed client, ApiFailure carries the server's fix
  types.ts                    hand-written until `npm run generate:api`
  useRealtime.ts              WebSocket with cursor replay + backoff
  format.ts, channels.tsx     relative time, compact money, provider marks
```

## Three decisions worth your review

### 1. The client never rewords a server error

`ApiFailure` carries the backend's `message` and `fix` straight to the UI. The
backend already writes a sentence explaining what to do — re-wording it in the
client makes it worse *and* puts two copies out of sync. `<Failure>` renders
both, always.

### 2. Realtime updates in place, with no toast and no jump

When a thread is scored, the rail grows and the number changes. Nothing
reorders under the cursor, nothing pops a notification. An inbox that rearranges
itself while you're reading is an inbox you stop trusting. Reordering happens
when *you* change the filter.

The cursor in `useRealtime` is why: a tab asleep for two minutes reconnects with
its last event id and the server replays the gap. Reconnect backs off
exponentially, capped at 30s, so a server restart doesn't produce a thundering
herd from every open tab.

### 3. The login page argues instead of decorating

Five bars at the scores the demo inbox actually produces — 94 investor, 86
recruiter, 81 client, 41 review, 4 newsletter. Someone who has never heard of
this understands the pitch before typing an email address. No stock
illustration, no gradient mesh.

## Quality floor, not announced in the UI

- Responsive to mobile: list and detail swap on small screens, bottom nav appears
- `:focus-visible` ring on everything, `aria-label` on every icon-only control
- The Signal Rail is `role="img"` with a spoken score, so it isn't a colour-only signal
- `prefers-reduced-motion` kills every animation
- Theme is CSS variables and a class on `<html>` — switching doesn't re-render components that know hex values

## Verified

19 TypeScript files, braces balanced, every `@/` import resolves to a file that
exists. Not yet run through `npm run build` — no network in this environment.

## Next

Phase 6: Studio, Scheduler, People, Rules builder, Settings/Channels. The shell,
tokens and primitives are all in place, so those pages are assembly rather than
invention.
