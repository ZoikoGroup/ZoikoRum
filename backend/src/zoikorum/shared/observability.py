"""Logging and error reporting for the API and the worker (Engineering Handbook: structured logs with correlation ids).

``ZK_LOG_FORMAT``: ``json`` (one JSON object per line, for log shippers) or ``text`` (readable, for a terminal); by
default text in local development and JSON everywhere else. ``ZK_LOG_LEVEL`` sets the level. Extra fields are passed
as ``log.info("request", extra={"fields": {...}})``. ``ZK_SENTRY_DSN`` turns on error reporting when the optional
``sentry-sdk`` package is installed (``pip install -e "backend[monitoring]"``); personal data is never sent.
Nothing here logs configuration values or secrets.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from zoikorum.shared import context

log = logging.getLogger("zoikorum.observability")
_configured = False


def _correlation_id() -> str | None:
    ctx = context._ctx.get()  # read only: never create a context just to log
    return ctx.correlation_id if ctx else None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        body = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if cid := _correlation_id():
            body["correlationId"] = cid
        body.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            body["exc"] = self.formatException(record.exc_info)
        return json.dumps(body, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = dict(getattr(record, "fields", None) or {})
        if cid := _correlation_id():
            fields.setdefault("correlationId", cid)
        return line + ("  " + " ".join(f"{k}={v}" for k, v in fields.items()) if fields else "")


def configure_logging(env: str, log_format: str | None, level: str) -> None:
    """Once per process. Tests keep pytest's own logging capture."""
    global _configured
    if _configured or env == "test":
        return
    handler = logging.StreamHandler(sys.stdout)
    use_json = (log_format or ("text" if env in ("local", "development") else "json")) == "json"
    handler.setFormatter(JsonFormatter() if use_json else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = []  # one format: uvicorn logs go through the root handler
        logging.getLogger(name).propagate = True
    _configured = True


def init_error_reporting(dsn: str | None, env: str, release: str) -> bool:
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("Error reporting is configured but sentry-sdk is not installed; install backend[monitoring]")
        return False
    sentry_sdk.init(dsn=dsn, environment=env, release=release, send_default_pii=False, traces_sample_rate=0.0)
    return True


def setup(service: str) -> None:
    from zoikorum.config import get_settings

    s = get_settings()
    configure_logging(s.env, s.log_format, s.log_level)
    if init_error_reporting(s.sentry_dsn, s.env, f"{service}@{s.release}"):
        log.info("error reporting on", extra={"fields": {"service": service}})
