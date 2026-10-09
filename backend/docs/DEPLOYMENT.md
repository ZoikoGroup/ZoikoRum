# Deploying Zoikorum

Two container images and one managed database. Everything is configured with environment variables; no secret is
built into an image or committed to git.

| Image | Built from | Runs as |
|---|---|---|
| `zoikorum-backend` | `backend/Dockerfile` | **api** (default command, port 8000), **worker** (`python -m zoikorum.worker`), **migrate** (`alembic upgrade head`, one-off) |
| `zoikorum-web` | `frontend/Dockerfile` | nginx on port 8080: the built web app, plus `/v1`, `/health`, `/ready` forwarded to the API (one origin, no CORS) |

```
browser ──HTTPS──> load balancer (TLS) ──> web :8080 ──/v1──> api :8000 ──> PostgreSQL (managed)
                                                               worker ────┘     S3 (files), SMTP, partners
```

## Services needed

| Service | Setting(s) | Notes |
|---|---|---|
| PostgreSQL 16 | `ZK_DATABASE_URL` (`postgresql+asyncpg://…`) | Managed, with backups and point-in-time recovery |
| S3 bucket | `ZK_STORAGE_PROVIDER=s3`, `ZK_S3_BUCKET`, `ZK_AWS_REGION`, optional `ZK_S3_KMS_KEY_ID`, Object Lock settings | Versioned; the container's IAM role grants access (no keys in env where possible) |
| Email (SMTP) | `ZK_EMAIL_PROVIDER=smtp`, `ZK_SMTP_HOST/PORT/USERNAME/PASSWORD`, `ZK_EMAIL_FROM` | e.g. AWS SES SMTP |
| Payments | `ZK_PAYMENT_PROVIDER=stripe` and the Stripe settings | Only after partner approval (`ZK_PAYMENT_FLOW_APPROVED`) |
| Identity partner | `ZK_VERIFICATION_PROVIDER=veriff` + `ZK_VERIFF_API_KEY`, `ZK_VERIFF_SHARED_SECRET` (or the Persona settings) | Webhook URL in the partner dashboard: `https://<host>/v1/verification/webhooks/veriff` |
| Error reporting | `ZK_SENTRY_DSN`, `ZK_RELEASE` | Optional |
| Redis | `ZK_REDIS_URL` | Rate-limit counters shared by every API process and server. No business data; if it is down the API keeps serving with per-process limits |

Required for every non-local environment: `ZK_ENV` (`staging` or `production`), `ZK_JWT_SECRET` and
`ZK_FIELD_ENCRYPTION_KEY` (long random values, different per environment, kept in the secret manager),
`ZK_WEBHOOK_SECRET`, `ZK_FRONTEND_URL` (the public https address; used in email links).
Development-only switches are refused outside local development: `ZK_DEV_SKIP_MFA`, `ZK_VERIFICATION_PROVIDER=simulated`.

## Releasing a version

1. Build both images with the release tag: `ZK_RELEASE=2026.10.1 docker compose -f docker-compose.prod.yml build`
   (or the same `docker build` commands in CI, pushed to the container registry).
2. Run migrations once: `docker compose -f docker-compose.prod.yml run --rm migrate`. The API and the worker refuse to
   start against a database whose migrations are not current, so a forgotten step fails safely.
3. Start or roll the services: `docker compose -f docker-compose.prod.yml up -d api worker web`.
4. Check: `GET /ready` returns `{"status": "ready"}` (database reachable and migrated); `GET /health` is liveness only.

Run **one worker per database** (it relays events and fires timers). The API can scale horizontally; set
`WEB_CONCURRENCY` (default 2 processes per container). With `ZK_REDIS_URL` all processes and servers share one
request budget per caller; without it each process counts on its own (the API logs a warning at start outside
development).

## Health checks for the platform

| Check | Path | Use |
|---|---|---|
| Liveness | `GET /health` | Restart the container if it fails |
| Readiness | `GET /ready` | Send traffic only when it returns 200 (503 with a reason otherwise) |

## Logs

One line per event, JSON by default outside local development (`ZK_LOG_FORMAT=json`), each with the request's
`correlationId` (also returned to the browser in `X-Correlation-Id` and shown in error messages), so a user's report can
be traced through the API and the worker. Logs never contain configuration values, secrets, passwords or tokens.

## Security headers

The API sets them on every response (`shared/http.py`); nginx sets the web app's own (content security policy, frame
blocking, HSTS) in `frontend/nginx.conf.template`. TLS ends at the load balancer; the API trusts its `X-Forwarded-*`
headers (`--proxy-headers`).

## Single-host setup

`docker-compose.prod.yml` runs everything on one machine for staging or a small production. Put the configuration in
`backend/.env.production` (git-ignored; start from `backend/.env.example`) and a TLS load balancer or reverse proxy in
front of port 8080.
