"""Deployment check: is this environment's configuration complete and usable? (python -m zoikorum.cli check-config)

Prints one line per area - OK, WARN or MISSING - and never a configuration value (no addresses, keys or passwords).
With --connect it also tries the database, Redis, the S3 bucket and the email server. Exit code 1 when anything
required for a server deployment is missing or unreachable, so a release pipeline can stop before going live.
In local development everything is reported for information only.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl

from pydantic import ValidationError

from zoikorum.config import DEV_ENVS, Settings

OK, WARN, MISSING = "OK", "WARN", "MISSING"


def review(s: Settings) -> list[tuple[str, str, str]]:
    """(status, area, plain-language detail) for every outside service the platform needs."""
    out: list[tuple[str, str, str]] = []
    add = lambda status, area, detail: out.append((status, area, detail))  # noqa: E731

    # Template values like <sk_live_...> left in by mistake: name the setting, never the value.
    unfilled = [f"ZK_{name.upper()}" for name, value in s.model_dump().items()
                if isinstance(value, str) and "<" in value and ">" in value]
    if unfilled:
        add(MISSING, "Placeholders", "still a template value: " + ", ".join(unfilled))
    add(OK, "Environment", s.env)
    if s.env in DEV_ENVS:
        add(WARN, "Secrets", "development values (fine locally only)")
    else:
        add(OK, "Secrets", "set (the app refuses to start otherwise)")

    if s.email_provider == "smtp" and s.smtp_host and s.smtp_username and s.smtp_password:
        add(OK, "Email", "SMTP configured")
    elif s.email_provider == "smtp":
        add(MISSING, "Email", "ZK_SMTP_HOST, ZK_SMTP_USERNAME and ZK_SMTP_PASSWORD are needed")
    else:
        add(MISSING, "Email", "ZK_EMAIL_PROVIDER=console only prints emails; set smtp so people get confirmation and reset emails")

    if s.payment_provider == "stripe" and s.stripe_secret_key and s.stripe_webhook_secret:
        if not s.payment_flow_approved:
            add(WARN, "Payments", "Stripe configured but ZK_PAYMENT_FLOW_APPROVED=false: funding stays switched off")
        elif not s.payment_operating_countries:
            add(WARN, "Payments", "no ZK_PAYMENT_OPERATING_COUNTRIES: say where payments are switched on")
        else:
            add(OK, "Payments", f"Stripe, {len(s.payment_operating_countries)} countries")
        if s.env == "production" and s.stripe_secret_key.startswith("sk_test_"):
            add(WARN, "Payments", "production is using a Stripe TEST key")
    elif s.payment_provider == "stripe":
        add(MISSING, "Payments", "ZK_STRIPE_SECRET_KEY and ZK_STRIPE_WEBHOOK_SECRET are needed")
    else:
        add(MISSING, "Payments", f"ZK_PAYMENT_PROVIDER={s.payment_provider} cannot take real money; set stripe")

    provider = s.verification_provider
    if provider == "veriff" and s.veriff_api_key and s.veriff_shared_secret:
        add(OK, "Identity checks", "Veriff configured")
    elif provider == "persona" and s.persona_api_key and s.persona_template_id and s.persona_webhook_secret:
        add(OK, "Identity checks", "Persona configured")
    elif provider in ("veriff", "persona"):
        add(MISSING, "Identity checks", f"{provider} keys are incomplete")
    elif provider == "manual":
        add(WARN, "Identity checks", "manual: staff review every identity document themselves")
    else:
        add(MISSING, "Identity checks", f"ZK_VERIFICATION_PROVIDER={provider} is for development; set veriff")

    if s.storage_provider == "s3" and s.s3_bucket:
        add(OK, "File storage", "S3 bucket configured" + (", with Object Lock" if s.s3_object_lock_mode else ""))
        if s.s3_object_lock_mode and not s.s3_retention_days:
            add(MISSING, "File storage", "ZK_S3_OBJECT_LOCK_MODE needs ZK_S3_RETENTION_DAYS")
    elif s.storage_provider == "s3":
        add(MISSING, "File storage", "ZK_S3_BUCKET is needed")
    else:
        add(MISSING, "File storage", "local disk: files are lost when a container is replaced; set s3")

    if s.redis_url:
        add(OK, "Rate limits", "shared through Redis")
    elif s.rate_limit_enabled:
        add(WARN, "Rate limits", "no ZK_REDIS_URL: each API process counts on its own")
    else:
        add(WARN, "Rate limits", "switched off (ZK_RATE_LIMIT_ENABLED=false)")

    if not s.frontend_url.startswith("https://"):
        add(MISSING, "Public address", "ZK_FRONTEND_URL must be the https:// address of the web app")
    else:
        add(OK, "Public address", "https")
    add(OK if s.sentry_dsn else WARN, "Error reporting", "Sentry configured" if s.sentry_dsn else "no ZK_SENTRY_DSN (optional)")
    if s.ai_provider == "anthropic":
        add(OK if s.anthropic_api_key else MISSING, "AI", "Claude configured" if s.anthropic_api_key else "ZK_ANTHROPIC_API_KEY is needed")
    else:
        add(OK, "AI", "off: keyword rules (optional)")
    if s.dispute_challenge_window_days == 0:
        add(WARN, "Rules", "ZK_DISPUTE_CHALLENGE_WINDOW_DAYS=0: accepted work cannot be disputed (management to confirm)")
    return out


async def _database() -> tuple[str, str, str]:
    from zoikorum.shared.db import dispose_engine
    from zoikorum.shared.schema_guard import readiness

    try:
        problem = await readiness()  # None when reachable and migrated; never includes the address
    finally:
        await dispose_engine()
    if problem is None:
        return OK, "Database", "reachable, migrations current"
    if problem == "migrations not current":
        return MISSING, "Database", "reachable, but run: alembic upgrade head"
    return MISSING, "Database", "cannot connect"


def connect(s: Settings) -> list[tuple[str, str, str]]:
    """Try each configured service for real. Failures name the error type only."""
    out = [asyncio.run(_database())]
    if s.redis_url:
        try:
            import redis

            redis.Redis.from_url(s.redis_url, socket_timeout=5).ping()
            out.append((OK, "Redis", "reachable"))
        except Exception as exc:  # noqa: BLE001
            out.append((MISSING, "Redis", f"cannot connect ({type(exc).__name__})"))
    if s.storage_provider == "s3" and s.s3_bucket:
        try:
            import boto3

            boto3.client("s3", region_name=s.aws_region, endpoint_url=s.s3_endpoint_url).head_bucket(Bucket=s.s3_bucket)
            out.append((OK, "S3 bucket", "reachable with this server's credentials"))
        except Exception as exc:  # noqa: BLE001
            out.append((MISSING, "S3 bucket", f"not reachable ({type(exc).__name__})"))
    if s.email_provider == "smtp" and s.smtp_host:
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                if s.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if s.smtp_username and s.smtp_password:
                    smtp.login(s.smtp_username, s.smtp_password)
            out.append((OK, "Email server", "signed in"))
        except Exception as exc:  # noqa: BLE001
            out.append((MISSING, "Email server", f"cannot sign in ({type(exc).__name__})"))
    return out


def run(try_connections: bool = False) -> int:
    try:
        s = Settings()
    except ValidationError as exc:
        print("Configuration is invalid; the API would refuse to start:")
        for e in exc.errors():
            field = ".".join(str(x) for x in e["loc"]) or "settings"
            print(f"  MISSING  {field}: {e['msg'].removeprefix('Value error, ')}")
        return 1
    rows = review(s) + (connect(s) if try_connections else [])
    for status, area, detail in rows:
        print(f"  {status:<8} {area:<16} {detail}")
    blocking = [r for r in rows if r[0] == MISSING]
    if s.env in DEV_ENVS:
        print("\nLocal development: the list above is for information only.")
        return 0
    print("\nRESULT: " + ("ready to deploy" if not blocking else f"NOT ready - {len(blocking)} item(s) missing"))
    return 1 if blocking else 0
