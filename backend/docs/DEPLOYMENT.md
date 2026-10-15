# Deploying Zoikorum

Two container images and one managed database. Everything is configured with environment variables; no secret is
built into an image or committed to git.

| Image | Built from | Runs as |
|---|---|---|
| `zoikorum-backend` | `backend/Dockerfile` | **api** (default command, port 8000), **worker** (`python -m zoikorum.worker`), **migrate** (`alembic upgrade head`, one-off) |
| `zoikorum-web` | `frontend/Dockerfile` | nginx on port 8080: the built web app, plus `/v1`, `/health`, `/ready` forwarded to the API (one origin, no CORS) |

```
browser ──HTTPS──> load balancer (TLS) ──> web :8080 ──/v1──> api :8000 ──> PostgreSQL (managed)
                                                               worker ────┘     GCS bucket (files), SMTP, partners
```

## Configuration

Every setting is an environment variable starting with `ZK_`. Two templates list all of them, grouped and explained:

| File | For |
|---|---|
| `backend/.env.example` | Local development: copy to `backend/.env`. Nothing real is called (emails print, test card, simulated identity checks) |
| `backend/.env.production.example` | Staging and production: copy to `backend/.env.production` (git-ignored) for `docker-compose.prod.yml`, or enter each line in the host's secret manager. Replace every `<...>` value |

A blank setting means "use the default". Then check it (prints OK / WARN / MISSING per service, never a value; exit code 1
if anything required is missing, so a pipeline can stop):

```
docker compose -f docker-compose.prod.yml run --rm api python -m zoikorum.cli check-config            # settings only
docker compose -f docker-compose.prod.yml run --rm api python -m zoikorum.cli check-config --connect  # also tries DB, Redis, the bucket, SMTP
```

## Services needed

| Service | Setting(s) | Notes |
|---|---|---|
| PostgreSQL 16 | `ZK_DATABASE_URL` (`postgresql+asyncpg://…`) | Managed, with backups and point-in-time recovery |
| Google Cloud Storage bucket | `ZK_STORAGE_PROVIDER=gcs`, `ZK_GCS_BUCKET`, optional `ZK_GCS_KMS_KEY_NAME` | Versioned, private; the service account the app runs as grants access (no key file). See "File storage on Google Cloud" below |
| or Amazon S3 bucket | `ZK_STORAGE_PROVIDER=s3`, `ZK_S3_BUCKET`, `ZK_AWS_REGION`, optional `ZK_S3_KMS_KEY_ID`, Object Lock settings | Alternative to GCS. Versioned; the container's IAM role grants access |
| Email (SMTP) | `ZK_EMAIL_PROVIDER=smtp`, `ZK_SMTP_HOST/PORT/USERNAME/PASSWORD`, `ZK_EMAIL_FROM` | e.g. AWS SES SMTP |
| Payments | `ZK_PAYMENT_PROVIDER=stripe` and the Stripe settings | Only after partner approval (`ZK_PAYMENT_FLOW_APPROVED`) |
| Identity partner | `ZK_VERIFICATION_PROVIDER=veriff` + `ZK_VERIFF_API_KEY`, `ZK_VERIFF_SHARED_SECRET` (or the Persona settings) | Webhook URL in the partner dashboard: `https://<host>/v1/verification/webhooks/veriff` |
| Error reporting | `ZK_SENTRY_DSN`, `ZK_RELEASE` | Optional |
| AI (optional) | `ZK_AI_PROVIDER=anthropic`, `ZK_ANTHROPIC_API_KEY`, `ZK_AI_MODEL`; image needs `pip install .[ai]` | "Describe what you need" search and "Can't find yours?" specialization matching. Without it both use keyword rules, so nothing breaks |
| Redis | `ZK_REDIS_URL` | Rate-limit counters shared by every API process and server. No business data; if it is down the API keeps serving with per-process limits |

Required for every non-local environment: `ZK_ENV` (`staging` or `production`), `ZK_JWT_SECRET` and
`ZK_FIELD_ENCRYPTION_KEY` (long random values, different per environment, kept in the secret manager),
`ZK_WEBHOOK_SECRET`, `ZK_FRONTEND_URL` (the public https address; used in email links).
Development-only switches are refused outside local development: `ZK_DEV_SKIP_MFA`, `ZK_VERIFICATION_PROVIDER=simulated`.

## File storage on Google Cloud

Uploaded files (verification documents, profile photos, request and proposal attachments, delivered work, dispute
evidence, message files, data exports) go to one private bucket. The app writes each file once (never overwrites it),
keeps every version, and only ever deletes replaced profile photos.

```
PROJECT=<project-id>  REGION=<asia-south1>  BUCKET=<zoikorum-prod-files>
SA=<zoikorum-api@PROJECT.iam.gserviceaccount.com>   # the service account the API and worker run as

gcloud storage buckets create gs://$BUCKET --project=$PROJECT --location=$REGION     --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$BUCKET --versioning
# Old versions of replaced profile photos: remove after 30 days.
gcloud storage buckets update gs://$BUCKET --lifecycle-file=- <<'EOF'
{"rule": [{"action": {"type": "Delete"}, "condition": {"isLive": false, "daysSinceNoncurrentTime": 30,
           "matchesPrefix": ["professionals/"]}}]}
EOF
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$SA --role=roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$SA --role=roles/storage.legacyBucketReader
```

Then `ZK_STORAGE_PROVIDER=gcs` and `ZK_GCS_BUCKET=$BUCKET`. The image already contains the Google client (`gcs` extra).

- **Encryption with your own key (optional):** create a Cloud KMS key in the bucket's region, let the Cloud Storage
  service agent use it (`roles/cloudkms.cryptoKeyEncrypterDecrypter`), and set `ZK_GCS_KMS_KEY_NAME`.
- **Keeping evidence for a fixed period (optional, legal decision):** use a bucket retention policy *instead of*
  versioning (Cloud Storage does not allow both on one bucket; the app accepts either):
  `gcloud storage buckets update gs://$BUCKET --no-versioning --retention-period=<7y>`. Nothing can then be deleted or
  replaced early, including replaced profile photos (the app keeps them quietly). Locking the policy
  (`--lock-retention-period`) is permanent: only with Legal's sign-off.
- **Legal holds** on single files use Cloud Storage temporary holds.
- **Check:** `python -m zoikorum.cli check-config --connect` reports whether the bucket is reachable and versioned.

## Releasing a version

1. Build both images with the release tag: `ZK_RELEASE=2026.10.1 docker compose -f docker-compose.prod.yml build`
   (or the same `docker build` commands in CI, pushed to the container registry).
2. Check the configuration: `docker compose -f docker-compose.prod.yml run --rm api python -m zoikorum.cli check-config --connect`.
3. Run migrations once: `docker compose -f docker-compose.prod.yml run --rm migrate`. The API and the worker refuse to
   start against a database whose migrations are not current, so a forgotten step fails safely.
4. Start or roll the services: `docker compose -f docker-compose.prod.yml up -d api worker web`.
5. Check: `GET /ready` returns `{"status": "ready"}` (database reachable and migrated); `GET /health` is liveness only.
6. When the release adds search fields (as `15081f5c2ac6`, track record, does), rebuild the search index once:
   `docker compose -f docker-compose.prod.yml run --rm api python -m zoikorum.cli reindex-search`. Until then those
   fields fill in as each professional's next event arrives.

Run **one worker per database** (it relays events and fires timers). The API can scale horizontally; set
`WEB_CONCURRENCY` (default 2 processes per container). With `ZK_REDIS_URL` all processes and servers share one
request budget per caller; without it each process counts on its own (the API logs a warning at start outside
development).

## Load test (staging, before launch and before big releases)

`backend/scripts/load_test.py` runs many simulated visitors (search, profiles, taxonomy, a few "describe what you
need") and, with a staging buyer account, signed-in buyers (profile, contracts, notifications) at once. It is
read-only apart from signing in, refuses URLs that do not look like staging, and ends with PASS or FAIL against a p95
latency and error-rate limit (exit code 1 on FAIL, so CI can use it):

```
python scripts/load_test.py --base-url https://staging-api.<domain> --users 100 --duration 300     --email loadtest-buyer@<domain> --password '…' --p95-ms 800 --max-error-rate 0.01
```

All simulated visitors come from one address, so the per-address limit (60 a minute) answers most of them with 429;
the script counts those separately. To measure capacity, run it with `ZK_RATE_LIMIT_ENABLED=false` on staging for the
duration (and turn it back on), or from several machines. Record the result (users, p95 per endpoint, requests per
second, server sizes) in the launch checklist.

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
`backend/.env.production` (git-ignored; start from `backend/.env.production.example`) and a TLS load balancer or reverse proxy in
front of port 8080.
