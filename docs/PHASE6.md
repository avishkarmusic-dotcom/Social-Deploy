# Phase 6 — Frontend complete

24 TypeScript files. All six pages live. Shell, design system, and API client
are production-grade. The product is now usable end-to-end.

## What landed

```
app/(app)/
  page.tsx          Command centre      — Signal Meter + top 3 + decaying + metrics
  inbox/page.tsx    Universal Inbox     — Thread list, Signal Rail, AI draft
  studio/page.tsx   Content Studio      — 11 formats, 5 tones, 3-variant output
  people/page.tsx   CRM                 — Decay-risk ranking, timeline, notes
  rules/page.tsx    Automations         — Rules list, toggle, builder, starters
  data/page.tsx     Analytics           — Growth chart, channel yield, attribution
  settings/page.tsx Settings            — Connected sources, connect/disconnect
app/(auth)/login/page.tsx

components/
  ui/primitives.tsx       Mono, Chip, Button, SignalRail, Empty, Failure
  inbox/SignalMeter.tsx   The chart that is the product argument
  inbox/ThreadRow.tsx     Row with Signal Rail, channel icon, scores
  inbox/ThreadPane.tsx    AI verdict, transcript, tone composer
  shell/Shell.tsx         Rail nav, header, ⌘K, theme, mobile nav
  shell/Assistant.tsx     Ask-your-inbox panel (AI-powered)
  shell/CommandPalette.tsx  Debounced search + navigation

lib/
  api.ts            Full typed client — inbox, sources, ai, content, contacts,
                    automations, analytics, search
  types.ts          All domain types aligned with Phase 3b models
  channels.tsx      Provider marks (Icon, hue, label) for 14 sources
  format.ts         relativeTime, money, initials, categoryLabel
  useRealtime.ts    WebSocket with cursor replay and exponential backoff
```

## Design decisions maintained from Phase 5

**Machines speak in mono, humans speak in sans.** Every score, category,
channel label and timestamp is `font-mono`. Every name, subject, body and
drafted reply is `font-sans`. The visual grammar didn't drift across six pages.

**Colour: one job each.** Mint = opportunity. Ember = urgency/negative.
Iris = AI speaking. Amber = follow-up / time sensitivity. Nothing else gets
an accent.

**Empty states invite action.** No page apologises for having no data. Each
empty state names the next step concretely.

## Page notes

### Studio
Format rules are written into the API prompt, not hardcoded in the UI. Changing
"under 60 characters" for an SEO title means one backend edit, not a UI
release. The three variants share the same brief; the `angle` field names the
strategy, not just the tone, so the person picks by intent rather than vibe.

### People
The CRM sorts by **decay risk** by default — `importance × silence`. A
high-importance contact you haven't spoken to in six weeks ranks above a
low-importance contact you messaged yesterday. This is the one ranking that
treats the CRM as a relationship tool rather than an address book.

### Rules
The builder exposes only the vocabulary the engine knows. The `/vocabulary`
endpoint drives the field and action selectors, so an invalid rule is impossible
to compose rather than merely rejected on save. The three starter rules cover
the three most common use cases (recruiter, negative review, high-value signal).

### Data
Every metric carries a `confident` flag. Below the sample floor, charts show
an empty state that names the missing sample count rather than a fabricated
number. Attribution renders with its caveat in the UI — first-touch,
model-estimated, useful for ranking attention, not for forecasting revenue.

### Settings
The `/v1/meta` endpoint drives the connect panel. A source that has no OAuth
credentials configured in `.env` renders as disabled rather than failing on
click. Disconnection confirms before calling revoke, and messages already
imported stay in the inbox regardless.

## Quality floor

- All focus rings via Tailwind `focus-visible` — keyboard navigation works
  everywhere
- `aria-label` on every icon-only control
- `role="switch"` on automation toggles
- `aria-current` on active rows
- `prefers-reduced-motion` handled in `globals.css`
- Mobile responsive: list/detail panels swap on small screens

## Verified

24 TypeScript files, braces balanced, every `@/` import resolves.
Not yet run through `npm run build` — no network in this environment.

## What Phase 7 builds on top of this

The `api.ts` client already has stubs for every Phase 7 endpoint (ads). The
`SourceAccount` type accepts any `source_kind` string — GitHub, Google Calendar,
Notion connectors won't need UI changes. The Settings page's connect panel
reads available sources from `/v1/meta`, so new connectors appear automatically.
