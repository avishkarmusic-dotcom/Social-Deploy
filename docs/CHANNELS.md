# Channels

Fourteen providers, one thread model. This page is the honest version: what
each channel can actually do, what it costs to keep in sync, and where it will
disappoint someone.

## Capability matrix

| Channel | Delivery | Read | Reply | Publish | Interval | The catch |
|---|---|---|---|---|---|---|
| Gmail | Pub/Sub | ✅ | ✅ | — | push | `historyId` expires in ~7 days; expiry triggers a bounded backfill, never a full re-sync |
| Outlook | Graph webhook | ✅ | ✅ | — | push | Subscriptions expire every 3 days and must be renewed by a cron |
| Instagram | Graph webhook | ✅ | ✅ | ✅ | push | Sender IDs are page-scoped and meaningless across accounts |
| Messenger | Graph webhook | ✅ | ✅ | ✅ | push | Echoes your own sends back; filtered on `is_echo` |
| WhatsApp | Graph webhook | ✅ | ⚠️ | — | push | 24-hour reply window. Outside it, only approved templates send |
| Slack | Events API | ✅ | ✅ | — | push | 3-second timeout, 3 retries, then the event is gone |
| Telegram | Webhook | ✅ | ✅ | — | push | No OAuth — the user pastes a BotFather token |
| Google Business | Poll | ✅ | ✅ | ✅ | 15 min | Review replies can't contain links |
| LinkedIn | Poll | ⚠️ | ✅ | ✅ | 3 min | Messaging API is partner-gated; standard apps get comments and notifications only |
| X | Poll | ✅ | ✅ | ✅ | 15 min | Free tier reads are scarce enough that the interval is the product decision |
| YouTube | Poll | ✅ | ✅ | — | 10 min | Daily quota units, not request counts — 403 means "come back tomorrow" |
| Facebook | Graph webhook | ✅ | ✅ | ✅ | push | Page tokens, not user tokens; re-auth when a page admin changes |
| Threads | Poll | ✅ | ✅ | ✅ | 10 min | API still narrower than Instagram's |
| Discord | Gateway | ✅ | ✅ | — | push | Needs a persistent socket, not a webhook — runs in its own worker |

⚠️ means the capability exists but is materially restricted. The UI says so on
the channel card rather than failing silently later.

## Adding a channel

One file, one line:

```python
@register
class DiscordAdapter(ChannelAdapter):
    kind = ChannelKind.DISCORD
    supports_push = True
    scopes = ("messages.read", "bot")

    def authorize_url(self, *, state, redirect_uri): ...
    async def exchange_code(self, code, *, redirect_uri): ...
    async def sync(self, *, access_token, cursor, limit): ...
    async def send(self, *, access_token, reply_ref, body): ...
```

Then add it to `registry.load_all()`. Nothing else changes — scoring, CRM,
search, automations and the inbox already understand `NormalizedThread`.

## The three rules the pipeline never breaks

**Verify before parsing.** An unsigned webhook body is not a message. Every
adapter's `verify_webhook` defaults to returning `False`, so forgetting to
implement it fails closed.

**Answer fast, work later.** Handlers return 200 in under 50 ms. Meta disables
slow endpoints and Slack gives up after three tries; the ingest, score and
automation chain all run on the queue.

**Replay is normal.** `UNIQUE (thread_id, external_id)` plus `ON CONFLICT`
means the same webhook delivered three times produces one row, one score, and
one notification.

## `reply_ref`, and why it's a loose dict

Replying needs something different everywhere: Gmail wants a `Message-Id`
header, Slack a `thread_ts`, Meta a recipient id, Google Business a review
resource name. Modelling all of them would put fourteen providers' vocabulary
into the core schema for no gain, since only the adapter that produced a message
ever needs to read it back. So `reply_ref` is opaque to everything except its
own adapter — the one place in the codebase where a typed field would have cost
more than it bought.

## Rate limits

Every provider rations differently, so the budget is per `(provider, account)`
with a Redis token bucket, and a server-set `Retry-After` overrides our own
pacing. Backoff carries jitter — without it every worker returns at the same
instant and immediately earns a second 429.

## What breaks first, in practice

1. **Token expiry on re-consent.** Google omits the refresh token unless
   `prompt=consent` is forced. The account then works for an hour and dies
   quietly. Handled in the Gmail adapter; worth remembering for any new Google scope.
2. **Outlook subscription renewal.** Three-day lifetime. If the renewal cron
   stops, mail silently stops arriving with no error anywhere.
3. **WhatsApp's 24-hour window.** Users read the failure as a bug in the
   product. The adapter checks the window before calling and explains it instead.
