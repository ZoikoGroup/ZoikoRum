# Runbooks

What to do when an alert fires. Each alert in [deploy/monitoring/alerts.yml](../deploy/monitoring/alerts.yml) links to a
section here. Staff screens are in the staff app (`staff.your-domain.com`); commands run on the server from the repository
folder, with `DC="docker compose --env-file backend/.env.production -f docker-compose.prod.yml"`.

Three rules for every incident:

1. **Money first.** If money could move wrongly, pause it before investigating (Administration → Switches & Worker:
   funding, releases, payouts). Paused releases and payouts go out on their own within 10 minutes of switching back on.
2. **Never edit the database by hand** to fix money, contracts or audit records. Use the replay, re-run and switch
   controls below; they are audited.
3. **Write it down.** Open an incident (Administration → Incidents) with the time, what you saw, what you did. Level 3+
   incidents get a post-incident review.

Every log line carries a `correlationId`; one id follows a request through events, the worker and the audit trail
(Audit → filter by correlation id).

## API down or not ready

Alert: `ApiDown`. Also when `/ready` returns 503.

1. `curl -s https://app.your-domain.com/ready` — the body says why: `database` (cannot connect) or `schema` (migrations
   not applied).
2. Schema: `$DC run --rm migrate`, then `$DC up -d api worker`.
3. Database: check Cloud SQL in the Google Cloud console (instance running, connections, storage full). The app
   reconnects on its own when the database is back.
4. Container crash loop: `$DC logs --tail 200 api`. A message "Production settings are incomplete" lists what is missing
   (run `$DC run --rm api python -m zoikorum.cli check-config --connect`); it never prints values.
5. Roll back a bad release: set `ZK_RELEASE` to the previous tag in `.env.production`, `$DC up -d api worker web web-staff`
   (migrations only ever add, so the previous version runs on the newer schema).

## High error rate

Alert: `HighErrorRate` (more than 2% server errors for 10 minutes).

1. Error reporting (Sentry) groups the errors; or `$DC logs api | grep '"severity": "ERROR"'`.
2. 503 `SERVICE_UNAVAILABLE` / `SCANNER_UNAVAILABLE`: a partner is down — see [Partner outage](#partner-outage). ClamAV:
   `$DC restart clamav` (uploads are refused while it is down; nothing unscanned is stored).
3. A new release: roll back (step 5 above).

## Slow responses

Alerts: `SlowSearch`, `SlowProposalChanges`.

1. Cloud SQL → Query insights for the slowest statements; CPU and connections.
2. Traces (if `ZK_TRACING_ENDPOINT` is set) show which step is slow.
3. Short term: add API capacity (`WEB_CONCURRENCY`, or a second server behind the load balancer). Search rebuild:
   `$DC run --rm api python -m zoikorum.cli reindex-search`.

## Worker stopped or behind

Alerts: `EventsNotPublished`, `TimersOverdue`. Without the worker, payments are not confirmed, emails and notifications
are not sent and deadlines do not fire — but nothing is lost: everything waits in the outbox and timers tables.

1. `$DC ps worker` and `$DC logs --tail 200 worker`.
2. `$DC up -d worker` (exactly one worker per database).
3. Administration → Switches & Worker shows the backlog going down. It catches up in order.

## Dead letters

Alerts: `FinancialDeadLetter` (page Financial Operations), `DeadLetters`.

An event failed after every retry, or failed in a way a retry cannot fix.

1. Administration → Dead letters: the error and the event.
2. Fix the cause (a partner outage, a bug fixed in a release, a missing configuration).
3. Replay it from the same screen. Money events can only be replayed by Financial Operations, and only by a person.
   Replays are idempotent: an event already applied is not applied twice.

## Partner outage

Alert: `PartnerCircuitOpen` — calls to a partner (payments, identity checks, email, AI) kept failing and are stopped
for a short time so requests stay fast.

1. Check the partner's status page (Stripe, Veriff, the email provider, Anthropic).
2. Nothing to do in Zoikorum while it is down: payments and refunds are retried automatically; identity checks wait;
   AI features fall back to rules. The circuit closes on its own when calls succeed again.
3. A long payments outage: pause funding (Switches) so buyers are not shown errors at checkout.

## Reconciliation mismatch

Alerts: `ReconciliationMismatch` (P0), `ReconciliationNotRunning`.

1. Pause payouts (Switches) until it is understood.
2. Financial Operations → Reconciliation: the day and the lines that differ (ledger vs provider charges, refunds,
   payouts).
3. Compare with the provider dashboard. Typical causes: a provider event not yet received (re-run the day once it
   arrives), a refund made in the provider dashboard by hand (record it, never repeat it), a chargeback.
4. Re-run the day from the same screen. Resume payouts when the day shows 0 mismatches.
5. `ReconciliationNotRunning`: the worker is stopped (see above) or the provider report is unavailable.

## Audit chain broken

Alert: `AuditChainBroken` (P0: possible tampering).

1. Do not try to "repair" records. Export the audit trail (Audit → Export, with chain verification) and keep the file.
2. The `HASH_CHAIN_BROKEN` event names the first record that does not match. Find who had database write access around
   its time (Cloud SQL audit logs).
3. Inform Legal and the Executive on call. Treat as a security incident (Level 3+, post-incident review).
4. Restore from a backup to a separate instance to compare, if needed. The alert stays until the chain is investigated.

## Incident switches

Alert: `SwitchPausedForADay` — a pause has been on for more than a day. Confirm it is still needed (Administration →
Switches & Worker shows who paused it and why) and switch it back on when the cause is fixed.

## Restore a database backup

1. Cloud SQL → Backups (or point-in-time recovery) → restore to a **new** instance.
2. Point a staging copy of the app at it (`ZK_DATABASE_URL`), run `python -m zoikorum.cli check-config --connect`, open
   `/ready`.
3. To switch production over: pause funding, releases and payouts; stop the worker; change `ZK_DATABASE_URL`; start the
   API and worker; check `/ready`, reconciliation and the audit chain; resume.
