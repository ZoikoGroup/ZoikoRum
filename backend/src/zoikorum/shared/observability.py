"""Logging and error reporting for the API and the worker (Engineering Handbook: structured logs with correlation ids).

``ZK_LOG_FORMAT``: ``json`` (one JSON object per line, for log shippers) or ``text`` (readable, for a terminal); by
default text in local development and JSON everywhere else. ``ZK_LOG_LEVEL`` sets the level. Extra fields are passed
as ``log.info("request", extra={"fields": {...}})``. ``ZK_SENTRY_DSN`` turns on error reporting when the optional
``sentry-sdk`` package is installed (``pip install -e "backend[monitoring]"``); personal data is never sent.
``ZK_TRACING_ENDPOINT`` (an OpenTelemetry collector, e.g. ``http://otel-collector:4318/v1/traces``) turns on traces of
API requests, database queries, partner calls and event consumers, with the ``tracing`` extra installed. Spans carry the
correlation id; URLs are recorded without their query string (search text, signed links).
Nothing here logs configuration values or secrets.
"""

from __future__ import annotations

import contextlib
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


_tracing = False


def init_tracing(endpoint: str | None, service: str, env: str, release: str, ratio: float) -> bool:
    """Once per process. Parent-based sampling: a trace started upstream keeps its decision."""
    global _tracing
    if _tracing or not endpoint:
        return _tracing
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
    except ImportError:
        log.warning("Tracing is configured but its packages are not installed; install backend[tracing]")
        return False
    provider = TracerProvider(
        resource=Resource.create({"service.name": f"zoikorum-{service}", "service.version": release,
                                  "deployment.environment": env}),
        sampler=ParentBasedTraceIdRatio(ratio))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()  # partner calls (Stripe, Veriff, Persona)
    _tracing = True
    return True


def _path_only(span, scope) -> None:
    """Query strings can hold a buyer's search text or a signed link: keep the path only."""
    if span and span.is_recording():
        path = scope.get("path", "")
        for key in ("http.url", "http.target", "url.full", "url.query"):
            span.set_attribute(key, path if key != "url.query" else "")


def instrument_app(app) -> None:
    if not _tracing:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics", server_request_hook=_path_only)


def instrument_engine(engine) -> None:
    if not _tracing:
        return
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    # Its declared range stops below SQLAlchemy 2.1; the engine events it uses are unchanged in 2.1.
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, skip_dep_check=True)  # statements, never values


def tag_current_span(**attributes) -> None:
    """Add attributes (e.g. the correlation id) to the active span; nothing when tracing is off."""
    if not _tracing:
        return
    from opentelemetry import trace

    span = trace.get_current_span()
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(f"zoikorum.{key}", str(value))


def span(name: str, **attributes):
    """A span around worker work (an event consumer, a timer); a no-op context when tracing is off."""
    if not _tracing:
        return contextlib.nullcontext()
    from opentelemetry import trace

    return trace.get_tracer("zoikorum").start_as_current_span(
        name, attributes={f"zoikorum.{k}": str(v) for k, v in attributes.items() if v is not None})


def setup(service: str) -> None:
    from zoikorum.config import get_settings

    s = get_settings()
    configure_logging(s.env, s.log_format, s.log_level)
    if init_error_reporting(s.sentry_dsn, s.env, f"{service}@{s.release}"):
        log.info("error reporting on", extra={"fields": {"service": service}})
    if init_tracing(s.tracing_endpoint, service, s.env, s.release, s.tracing_sample_ratio):
        log.info("tracing on", extra={"fields": {"service": service}})
