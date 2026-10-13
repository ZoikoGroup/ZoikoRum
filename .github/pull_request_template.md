## What changed

<!-- One or two sentences. Link the issue or the product-document section. -->

## Why

## Test plan

- [ ] Backend tests (`pytest`) pass; new tests cover success **and** failure
- [ ] Frontend `npm run lint`, `npm test`, `npm run build` pass
- [ ] Manual check (steps, screenshots or API examples below)

## Migration notes

<!-- New Alembic revision? Data backfill? Anything to run after deploy (`alembic upgrade head`)? Write "None" if none. -->

## Rollout and rollback

<!-- How it goes live (setting, switch, order of steps) and how to undo it. A migration must have a working downgrade
     or say why not. -->

## Review checklist (Engineering Handbook 28)

- [ ] Right domain owns it; other domains are reached only through their `facade`
- [ ] State changes go through the state machine
- [ ] Event published for every state change (catalog updated)
- [ ] Audit record written for anything Legal, Finance or Compliance may ask about
- [ ] Permissions checked (organisation role / platform role / step-up where sensitive)
- [ ] Policy evaluated where required
- [ ] Safe to run twice (idempotency key, unique constraint or inbox)
- [ ] Failure halfway through leaves a consistent state (or retries / compensates)
- [ ] Logs, metrics and traces exist for it; runbook or launch checklist updated if operations change

## Security considerations

<!-- Personal data, secrets, new inputs from users, new partner calls, new public endpoints. Never commit .env files. -->
