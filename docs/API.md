# API reference

Base: `https://api.tryvanta.social` · Auth: `Authorization: Bearer <session-jwt>`
Every response carries `x-request-id`. Errors return
`{error, message, fix}` — `fix` is written for a human to act on.

## Inbox

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/inbox` | `channel[]`, `category[]`, `state`, `min_opportunity`, `sort=newest\|opportunity\|urgency`, `cursor`, `limit` |
| `GET` | `/v1/inbox/{id}` | Thread with messages and current intelligence |
| `POST` | `/v1/inbox/{id}/draft` | `{tone, length, translate_to}` → drafted body |
| `POST` | `/v1/inbox/{id}/send` | Sends via the originating channel; records the sent body as a voice sample |
| `POST` | `/v1/inbox/{id}/state` | `open \| snoozed \| archived \| done \| spam` |
| `POST` | `/v1/inbox/{id}/reclassify` | Force a fresh intelligence run |

## Channels

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/channels` | Connected accounts, sync status, last error |
| `GET` | `/v1/channels/{kind}/connect` | Starts OAuth, returns the authorize URL |
| `DELETE` | `/v1/channels/{id}` | Revokes upstream, then deletes tokens |
| `POST` | `/v1/webhooks/{kind}` | Provider callback, signature-verified |

## AI

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/ai/assistant` | Natural language over workspace data, streams SSE |
| `POST` | `/v1/ai/content` | `{kind, brief, tone, variants}` → generated pieces |
| `POST` | `/v1/ai/rewrite` | `{text, mode}` — shorter, longer, grammar, translate |

## Content and scheduling

`GET|POST /v1/content` · `POST /v1/content/{id}/schedule` ·
`GET /v1/schedule/calendar?from=&to=` · `GET /v1/schedule/best-times`

## CRM

`GET /v1/contacts` (`sort=strength|importance|stale`) ·
`GET /v1/contacts/{id}/timeline` · `POST /v1/contacts/{id}/notes` ·
`GET /v1/contacts/followups`

## Analytics

`GET /v1/analytics/overview?range=30d` · `/growth` · `/content` ·
`/attribution` — revenue and leads traced back to the thread that started them

## Automations

`GET|POST /v1/automations` · `POST /v1/automations/{id}/test` ·
`GET /v1/automations/{id}/runs`

## Realtime

`WSS /v1/ws?token=` — server sends `thread.created`, `thread.scored`,
`thread.updated`, `post.published`, `review.created`. Client sends `ping` every
25s. Reconnect with `?since=<cursor>` to replay missed events.

## Limits

600 requests/minute per workspace, 60/minute on `/v1/ai/*`. Exceeding returns
`429` with `Retry-After`.
