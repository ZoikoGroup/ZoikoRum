# Deploying Zoikorum

Three container images and one managed database. Everything is configured with environment variables kept in Google
Secret Manager; no secret is built into an image, committed to git or left on the server's disk.

| Image | Built from | Runs as |
|---|---|---|
| `zoikorum-backend` | `backend/Dockerfile` | **api** (port 8000), **worker** (`python -m zoikorum.worker`), **migrate** (migrations, then `cli db-grants`; one-off) |
| `zoikorum-web` | `frontend/Dockerfile` (`VITE_PORTAL=customer`) | nginx on port 8080: customers, professionals, firms, enterprise teams (`app.your-domain.com`) |
| `zoikorum-web-staff` | `frontend/Dockerfile` (`VITE_PORTAL=staff`) | nginx on port 8081: Zoikorum staff only (`staff.your-domain.com`, behind IAP) |

Next to them on the VM: **clamav** (virus scanning of every upload) and **redis** (shared rate limits). Optional:
**prometheus** and **alertmanager** (`--profile monitoring`).

```
browser ─HTTPS─> Google HTTPS load balancer ──app.──> web :8080 ──┐
                 (managed certificates)    └─staff.─> IAP ─> web-staff :8081 ─┤──/v1──> api :8000 ──> Cloud SQL (PostgreSQL)
                                                                          worker ──┘   Cloud KMS, ClamAV,
                                                                                        Stripe, Veriff, email
```

## Configuration

Every setting is an environment variable starting with `ZK_`. Two templates list all of them, grouped and explained:

| File | For |
|---|---|
| `backend/.env.example` | Local development: copy to `backend/.env`. Nothing real is called (emails print, test card, simulated identity checks) |
| `backend/.env.production.example` | Staging and production: the list of settings to create in Secret Manager (below). Replace every `<...>` value |

A blank setting means "use the default". **Production refuses to start** while anything required is missing (test
payments, local files, console email, no virus scanning, no KMS field keys, the development database, one database user,
or no shared passkey domain). See what is missing without printing any value:

```
DC="docker compose --env-file /run/zoikorum/.env.production -f docker-compose.prod.yml"
$DC run --rm api python -m zoikorum.cli check-config            # settings only
$DC run --rm api python -m zoikorum.cli check-config --connect  # also tries Cloud SQL, Redis, ClamAV, email
```

## Services needed

| Service | Setting(s) | Notes |
|---|---|---|
| Cloud SQL (PostgreSQL 16) | `ZK_DATABASE_URL` (app user), `ZK_MIGRATION_DATABASE_URL` (owner), `ZK_DB_APP_ROLE` | Private IP, backups and point-in-time recovery on. Two users: see "Database users" |
| File storage | `ZK_STORAGE_PROVIDER=database` | Files are stored in the PostgreSQL database and backed up with it. See "File storage" |
| Cloud KMS | `ZK_FIELD_KMS_KEY_NAME`, `ZK_FIELD_DATA_KEYS`, `ZK_FIELD_ACTIVE_KEY` | Wraps the keys that encrypt sensitive fields. See "Field encryption keys" |
| ClamAV | `ZK_MALWARE_SCANNER=clamav`, `ZK_CLAMAV_HOST=clamav` | The `clamav` service in `docker-compose.prod.yml`; updates its own signatures. Uploads are refused while it is down |
| Email (SMTP) | `ZK_EMAIL_PROVIDER=smtp`, `ZK_SMTP_HOST/PORT/USERNAME/PASSWORD`, `ZK_EMAIL_FROM` | Any SMTP service; SPF, DKIM and DMARC on the sending domain |
| Payments | `ZK_PAYMENT_PROVIDER=stripe` and the Stripe settings | Only after partner approval (`ZK_PAYMENT_FLOW_APPROVED`). Webhook URL in Stripe: `https://app.<domain>/v1/payments/webhooks/stripe` |
| Identity partner | `ZK_VERIFICATION_PROVIDER=veriff`, `ZK_VERIFF_API_KEY`, `ZK_VERIFF_SHARED_SECRET` | Webhook URL in Veriff: `https://app.<domain>/v1/verification/webhooks/veriff` |
| Web addresses | `ZK_FRONTEND_URL` (customer app), `ZK_STAFF_FRONTEND_URL` (staff app), `ZK_WEBAUTHN_RP_ID` | With `app.` and `staff.` on one domain, the passkey domain is the parent: `your-domain.com` |
| Invoice tax | `ZK_TAX_RULES` | Finance decides the rates; empty shows no tax |
| Error reporting | `ZK_SENTRY_DSN`, `ZK_RELEASE` | Optional |
| AI (optional) | `ZK_AI_PROVIDER=anthropic`, `ZK_ANTHROPIC_API_KEY`, `ZK_AI_MODEL` | Without it the features use rules, so nothing breaks |
| Redis | `ZK_REDIS_URL` | The `redis` service; rate-limit counters only |
| Metrics | `ZK_METRICS_TOKEN` | `GET /metrics` with this bearer token (never through the public web app) |

Always required outside local development: `ZK_ENV` (`staging` or `production`), `ZK_JWT_SECRET`,
`ZK_FIELD_ENCRYPTION_KEY`, `ZK_WEBHOOK_SECRET` (long random values, different per environment).
Development-only switches are refused outside local development: `ZK_DEV_SKIP_MFA`, `ZK_VERIFICATION_PROVIDER=simulated`.

## Google Cloud setup (once per environment)

**As code (recommended).** `backend/deploy/gcp/terraform/` creates everything below: the APIs, service accounts and
their roles, Workload Identity Federation for the Release workflow, Artifact Registry (keeps the last 20 releases),
the KMS key, one Secret Manager secret per line of `secrets.list` (values are added by hand, never in Terraform state),
a private network with Cloud NAT, Cloud SQL (private IP, point-in-time recovery, optional analytics
read replica), the VM without a public address, the firewall rules, and the HTTPS load balancer with a managed
certificate, an http→https redirect and Identity-Aware Proxy on the staff app.

```
cd backend/deploy/gcp/terraform
cp production.tfvars.example production.tfvars          # git-ignored; fill in
gcloud storage buckets create gs://<state-bucket> --location=$REGION --uniform-bucket-level-access --versioning
terraform init -backend-config="bucket=<state-bucket>" -backend-config="prefix=zoikorum/production"
terraform plan -var-file=production.tfvars && terraform apply -var-file=production.tfvars
terraform output                                         # values for the GitHub variables and settings
```

Then add the secret values, create the two database users (below), point DNS at `load_balancer_ip`, and install Docker
and the repository on the VM. Staging is the same with `environment = "staging"` and its own state prefix.

**By hand (the same resources):**

```
PROJECT=<project-id>  REGION=<asia-south1>  ZONE=<asia-south1-a>  DOMAIN=<your-domain.com>
VM_SA=zoikorum-vm@$PROJECT.iam.gserviceaccount.com        # the VM (API, worker) runs as this account
DEPLOY_SA=zoikorum-deploy@$PROJECT.iam.gserviceaccount.com  # GitHub Actions releases as this account (no key file)

# Registry for the three images
gcloud artifacts repositories create zoikorum --repository-format=docker --location=$REGION

# VM: Docker + the Compose plugin, no public SSH (IAP), the service account above, Shielded VM
gcloud compute instances create zoikorum-prod --zone=$ZONE --machine-type=e2-standard-4 --service-account=$VM_SA \
  --scopes=cloud-platform --shielded-secure-boot --image-family=cos-stable --image-project=cos-cloud --tags=zoikorum-web
# Only Google's load balancer (and its health checks) may reach the web ports; SSH only through IAP:
gcloud compute firewall-rules create zoikorum-lb --allow=tcp:8080,tcp:8081 --target-tags=zoikorum-web \
  --source-ranges=35.191.0.0/16,130.211.0.0/22
gcloud compute firewall-rules create zoikorum-iap-ssh --allow=tcp:22 --target-tags=zoikorum-web --source-ranges=35.235.240.0/20
```

**HTTPS load balancer.** An external Application Load Balancer with a Google-managed certificate for `app.$DOMAIN` and
`staff.$DOMAIN`, an instance group containing the VM with two named ports (`web:8080`, `staff:8081`), two backend
services with health checks on `/ready`, and a URL map with one host rule each. Turn on **Identity-Aware Proxy** for
the staff backend service and allow only staff Google accounts (`roles/iap.httpsResourceAccessor`). Set `ZK_LB_IP` (in
Secret Manager) to the load balancer's address: the web image trusts the visitor address it forwards (rate limits and
the IP recorded with signatures depend on it).

**Cloud SQL.** PostgreSQL 16, private IP in the VM's network, automatic backups and point-in-time recovery on.

### Database users

The app never uses the owner account in production:

```sql
-- as the instance's postgres user
CREATE ROLE zoikorum_owner LOGIN PASSWORD '<owner password>';
CREATE DATABASE zoikorum OWNER zoikorum_owner;
CREATE ROLE zoikorum_app LOGIN PASSWORD '<app password>';
```

`ZK_MIGRATION_DATABASE_URL` uses `zoikorum_owner`, `ZK_DATABASE_URL` uses `zoikorum_app`, `ZK_DB_APP_ROLE=zoikorum_app`.
The migrate step runs `python -m zoikorum.cli db-grants` after every migration: the app user may read and write
ordinary tables but only read and add to the audit trail, escrow ledger, evidence, signatures and the other append-only
tables, and it owns nothing (it cannot drop a table or switch a trigger off).

### Field encryption keys

Sensitive fields (authenticator secrets, phone numbers, webhook secrets) are encrypted with data keys that only Cloud KMS
can unwrap:

```
gcloud kms keyrings create zoikorum --location=$REGION
gcloud kms keys create fields --keyring=zoikorum --location=$REGION --purpose=encryption --rotation-period=365d
gcloud kms keys add-iam-policy-binding fields --keyring=zoikorum --location=$REGION \
  --member=serviceAccount:$VM_SA --role=roles/cloudkms.cryptoKeyEncrypterDecrypter
# Make a data key (prints only its wrapped form, safe to store):
ZK_FIELD_KMS_KEY_NAME=projects/$PROJECT/locations/$REGION/keyRings/zoikorum/cryptoKeys/fields \
  docker compose ... run --rm api python -m zoikorum.cli new-field-key --id 2026-10
```

Store the printed JSON as `ZK_FIELD_DATA_KEYS`, set `ZK_FIELD_ACTIVE_KEY=2026-10`. **Rotation:** make a new data key,
add it to `ZK_FIELD_DATA_KEYS` (keep the old ones), make it active, deploy, then run
`python -m zoikorum.cli rotate-field-keys` to re-encrypt stored values; remove the old id only after that.

### Secrets

Every setting listed in `backend/deploy/gcp/secrets.list` is one Secret Manager secret named after it in lower case
with dashes (`ZK_JWT_SECRET` → `zk-jwt-secret`). Remove the lines you leave at their defaults.

```
printf %s "<value>" | gcloud secrets create zk-jwt-secret --data-file=-        # once per setting
gcloud secrets add-iam-policy-binding zk-jwt-secret --member=serviceAccount:$VM_SA --role=roles/secretmanager.secretAccessor
```

At deploy time `backend/deploy/gcp/fetch-secrets.sh` writes them into a root-only file in memory (`/run/zoikorum`), the
services start, and the file is removed. Values are never printed.

## File storage

Uploaded files (verification documents, profile photos, request and proposal attachments, delivered work, dispute
evidence, message files, data exports) are stored in the PostgreSQL database (table `platform.stored_files`), after a
virus scan. They are backed up and restored with the rest of the data (Cloud SQL backups and point-in-time recovery).
The app writes each file once (never overwrites it) and only ever deletes replaced profile photos.

Set `ZK_STORAGE_PROVIDER=database`. Local disk (`local`) is for development and tests only and is refused in production.
Keep uploads small (see the upload size limits).

## Releasing a version

Releases run from GitHub: **Actions → Release → Run workflow**, with a version tag (`.github/workflows/release.yml`).
The `production` environment's required reviewers approve it. The workflow:

1. builds the backend, customer and staff images, and scans them (a fixable HIGH or CRITICAL vulnerability stops it);
2. pushes them to Artifact Registry;
3. on the VM (`backend/deploy/gcp/deploy.sh`, over IAP SSH): fetches the settings from Secret Manager, pulls the
   images, runs `check-config --connect` (stops if anything is missing), runs migrations and `db-grants`;
4. **canary:** starts the new API next to the running one and waits for its `/ready`. If it never gets there, the deploy
   stops with its log lines and the running release is untouched;
5. **switch:** restarts the services on the new release and waits for `/ready` on both web apps. If they do not
   become ready, the previous release (recorded in `/var/lib/zoikorum/release`) is started again automatically and
   the workflow fails.

One-time GitHub setup: repository variables `GCP_PROJECT`, `GCP_REGION`, `GCP_REGISTRY`, `GCP_VM`, `GCP_ZONE`,
`GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `ZK_FRONTEND_URL`, `ZK_STAFF_FRONTEND_URL`, and Workload Identity Federation so
GitHub signs in to Google without a stored key (`$DEPLOY_SA` needs Artifact Registry writer and IAP-secured SSH to the VM).

**Roll back by choice:** run the workflow again with the previous version (migrations only ever add, so an earlier version runs on
the newer schema). By hand on the VM: `sudo ZK_RELEASE=<previous> ZK_REGISTRY=<registry>/ ./backend/deploy/gcp/deploy.sh`.

**After a release that adds search fields:** `$DC run --rm api python -m zoikorum.cli reindex-search` once.

Run **one worker per database** (it relays events and fires timers). The API can scale out; set `WEB_CONCURRENCY`
(default 2 processes per container).

## Monitoring and alerts

`backend/deploy/monitoring/`: a Prometheus scrape configuration (`prometheus.yml`), 13 alert rules (`alerts.yml`) and
Alertmanager routing (`alertmanager.yml`). Each alert links its section in [RUNBOOKS.md](RUNBOOKS.md); a test fails if a
rule names a metric the API does not export. Run them on the VM (`$DC --profile monitoring up -d prometheus alertmanager`,
with `ZK_METRICS_TOKEN` in `backend/deploy/monitoring/metrics_token`) or load the same files into Google Cloud Managed
Service for Prometheus. Put your paging tool and email in `alertmanager.yml`.

Logs are JSON lines in the shape Cloud Logging reads (`severity`, `message`, `time`), each with the request's
`correlationId` (also shown in error messages and attached to help requests) and the acting user and organisation.
Docker rotates them (20 MB × 5 per container). Logs never contain configuration values, secrets, passwords or tokens.

## Load test (staging, before launch and before big releases)

`backend/scripts/load_test.py` runs many simulated visitors and, with a staging buyer account, signed-in buyers at once.
It is read-only apart from signing in, refuses URLs that do not look like staging, and ends with PASS or FAIL against a
p95 latency and error-rate limit:

```
python scripts/load_test.py --base-url https://staging-app.<domain> --users 100 --duration 300 --email loadtest-buyer@<domain> --password '…' --p95-ms 800 --max-error-rate 0.01
```

All simulated visitors come from one address, so the per-address limit answers most of them with 429 (counted
separately). To measure capacity, run it with `ZK_RATE_LIMIT_ENABLED=false` on staging for the duration, or from several
machines. Record the result in the launch checklist.

### Write path: the proposal flow

`backend/scripts/proposal_load_test.py` exercises writes: a buyer sends a proposal request, a professional drafts and
submits a proposal, the buyer reads and rejects it, and the request is cancelled (every iteration ends closed; nothing is
accepted, signed or paid). It uses staging **test accounts** listed in a JSON file (buyers with their organisation id,
professionals with their professional id; two-step sign-in off for them) and refuses any URL that does not look like
staging - there is no production override.

```
python scripts/proposal_load_test.py --base-url https://staging-app.<domain> --accounts loadtest-accounts.json --workers 10 --duration 300 --p95-ms 1000
```

## Chaos experiments (staging)

`backend/scripts/staging_chaos.sh` injects one fault at a time on the staging host and checks the platform degrades the
way it should, then recovers. It only runs when the environment file says `ZK_ENV=staging` and with
`--yes-this-is-staging`, and always removes the fault again (also on Ctrl-C).

| Experiment | Fault | Expected |
|---|---|---|
| `kill-worker` | the worker container is killed | API stays ready; events and timers wait (EventsNotPublished alert after 2 minutes); everything is delivered once it is back |
| `delay-db` | 300 ms (`--delay-ms`) network delay on the API container (database traffic included), via `tc netem` in a netshoot sidecar | slower answers, maybe latency alerts, no error storm; normal as soon as it ends |
| `drop-redis` | Redis stopped | API stays ready: rate limits fall back per process, the read cache reads the database ("read cache unavailable" warnings) |

```
sudo ./backend/scripts/staging_chaos.sh drop-redis --seconds 120 --yes-this-is-staging
```

Run them with the load test going in another terminal to see the effect under traffic, one at a time, and write down
what the alerts did. A run that does not end with RECOVERED is an incident to investigate before release.

## Enterprise sign-in, token keys and data protection settings

* **SAML 2.0 SSO**: an Organisation Admin uploads the identity provider's metadata (`PUT /v1/organizations/{id}/sso` with
  `protocol: "SAML"`). The identity provider needs Zoikorum's metadata from `GET /v1/auth/saml/metadata`; it posts to
  `<ZK_PUBLIC_API_URL or ZK_FRONTEND_URL>/v1/auth/saml/acs`. Responses must be signed (SHA-256 or stronger); encrypted
  assertions are not supported.
* **Session policy**: `PUT /v1/organizations/{id}/session-policy` sets the maximum session age, idle timeout, two-step
  requirement and allowed sign-in methods for members; sessions follow it from their next refresh.
* **RS256 tokens**: create a Cloud KMS asymmetric signing key (RSA_SIGN_PKCS1_2048_SHA256), give the VM account
  `roles/cloudkms.signerVerifier` and `roles/cloudkms.publicKeyViewer` on it, set `ZK_JWT_KMS_KEY_NAME` to its key
  version and `ZK_JWT_SIGNING=rs256`. Keep `ZK_JWT_ACCEPT_HS256=true` for at least one access-token lifetime (15 minutes)
  after the switch, then set it to false. Public keys: `GET /.well-known/jwks.json`. Without KMS, `python -m zoikorum.cli
  new-jwt-key` makes a key for `ZK_JWT_PRIVATE_KEYS`.
* **Evidence retention**: `ZK_RETENTION_RULES` (days per evidence type and country), `python -m zoikorum.cli
  retention-report` to see what is due, `ZK_RETENTION_PURGE_ENABLED=true` to let the daily job remove it. Files under
  legal hold are never removed.
* **Escrow ledger snapshots** run daily (03:30 UTC) with an integrity check; `python -m zoikorum.cli escrow-snapshots`
  runs them by hand. A mismatch pages Financial Operations (RUNBOOKS.md).
* **Edge and disaster recovery (Terraform)**: Cloud Armor (`cloud_armor_enabled`, start with `cloud_armor_preview = true`),
  and an optional cross-region Cloud SQL read
  replica (`db_cross_region_replica_region`, promoted by hand in a region outage).
* **Signed images**: the Release workflow signs every image with cosign (keyless, GitHub OIDC); `deploy.sh` verifies the
  signatures before pulling when cosign is installed on the VM (`ZK_COSIGN_REQUIRED=true` makes it mandatory).

## Health checks

| Check | Path | Use |
|---|---|---|
| Liveness | `GET /health` | Restart the container if it fails |
| Readiness | `GET /ready` | Load balancer health check: traffic only when 200 (503 with a reason otherwise) |

## Security headers and sessions

The API sets its headers on every response (`shared/http.py`); nginx sets the web app's own (content security policy,
frame blocking, HSTS) in `frontend/nginx.conf.template`. TLS ends at the load balancer. The web app keeps its refresh
token in an HttpOnly, Secure, SameSite=Strict cookie for `/v1/auth`; only the 15-minute access token is in memory.

## Single-host setup without the release workflow

`docker-compose.prod.yml` runs everything on one machine. With the settings file in place (`fetch-secrets.sh`, or a
hand-made `backend/.env.production` for staging): `$DC build`, `$DC run --rm migrate`,
`$DC up -d api worker clamav redis web web-staff`. Put a TLS load balancer or reverse proxy in front of 8080 and 8081.
