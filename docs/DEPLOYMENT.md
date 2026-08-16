# Deployment

## Shape

```
Cloudflare → web (Vercel or Cloud Run) → api (2+ replicas, autoscaled on p95)
                                          ├─ Postgres 16, HA, PITR on
                                          ├─ Redis 7, AOF, replica
                                          └─ workers (3+ replicas, arq)
```

## Before the first deploy

- [ ] `DATA_ENCRYPTION_KEY` generated and stored in the secret manager, never in CI logs
- [ ] `APP_SECRET` rotated off the default
- [ ] OAuth redirect URIs registered for the production domain on all 14 providers
- [ ] Postgres `shared_preload_libraries` includes `vector`
- [ ] Backups verified by restoring into staging, not by reading a green checkmark

## Migrations

```bash
alembic upgrade head        # runs as a pre-deploy job, not at app start
```
Migrations are expand-then-contract: add the column, ship code that writes both,
backfill, ship code that reads the new one, drop the old. No deploy ever needs
the API and the database to change at the same instant.

## Environments

| | Staging | Production |
|---|---|---|
| Data | Anonymised weekly clone | Live |
| AI keys | Separate, low budget | Separate, alerted at 80% of budget |
| Ingestion | Polling only | Push + polling |

## Watch these four

1. **p95 on `GET /v1/inbox`** — target under 200 ms. It's the whole product.
2. **Classification lag** — enqueue to scored. Over 60s, the inbox feels stale.
3. **Channel sync errors by kind** — a single provider's token expiry looks like
   an outage to the user; alert per channel, not in aggregate.
4. **AI spend per workspace per day** — the one cost that scales with usage
   rather than with users.

## Rollback

Images are tagged by commit SHA. `kubectl rollout undo` or redeploy the previous
tag. Because migrations are expand-then-contract, the previous image always runs
against the current schema.
