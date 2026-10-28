import csv
import io
import uuid
from datetime import datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Query, Request, Response
from zoikorum.config import get_settings
from zoikorum.domains.analytics import service
from zoikorum.domains.analytics.schemas import ClientEventsIn
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.identity import facade as identity
from zoikorum.domains.professional import facade as professional
from zoikorum.shared import clock, ratelimit
from zoikorum.shared.auth import CurrentActor, OptionalActor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.db import AnalyticsSession, DbSession
from zoikorum.shared.errors import NotFound, RateLimited, ValidationFailed
from zoikorum.shared.http import caller_key
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit
from zoikorum.shared.report_pdf import render_table_pdf

router = APIRouter(tags=["reports and analytics"])


async def member(session, actor, org_id):
    if not await buyer.get_member_roles(session, org_id, actor.identity_id):
        raise NotFound("Organisation not found")


async def own_professional(session, actor):
    pro = await professional.get_professional_by_identity(session, actor.identity_id)
    if not pro:
        raise NotFound("Professional profile not found")
    return pro


@router.get("/v1/dashboards/buyer")
async def buyer_dashboard(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession):
    await member(session, actor, organizationId)
    summary = service.summarize(await service.facts(session, org_id=organizationId))
    saved = set()
    for row in await service.facts(session, identity_id=actor.identity_id):
        if row.event_type == E.PROFESSIONAL_SAVED: saved.add(row.payload["professionalId"])
        if row.event_type == E.PROFESSIONAL_UNSAVED: saved.discard(row.payload["professionalId"])
    return {**summary, "savedProfessionals": len(saved)}


@router.get("/v1/dashboards/professional")
async def professional_dashboard(actor: CurrentActor, session: DbSession):
    pro = await own_professional(session, actor)
    return service.summarize(await service.facts(session, professional_id=pro.id), role="professional")


@router.get("/v1/analytics/marketplace-health")
async def marketplace_health(actor: CurrentActor, session: AnalyticsSession, since: datetime | None = Query(None, alias="from"), until: datetime | None = Query(None, alias="to")):
    """Marketplace health for the window [from, to): totals, a per-day (UTC) series of the key counts, and the current
    trust tier distribution, which is a snapshot rather than windowed. Totals are computed in the database, so the cost
    does not grow with the number of events kept."""
    actor.require_capability(Cap.ANALYTICS_READ)
    validate_dates(since, until)
    return await service.marketplace_health(session, since, until)


# Funnel events arrive in small batches from every page view: a budget per signed-in session or client address on top of
# the general limit, so one browser cannot flood the facts table.
EVENTS_LIMIT = (60, 30)  # batches per minute, burst


@router.post("/v1/analytics/events", status_code=202)
async def client_events(body: ClientEventsIn, request: Request, session: DbSession, actor: OptionalActor):
    """Product-funnel events from the web app (sign-in optional). Only allowlisted names and a few short, non-personal
    properties are stored, at the server's time; the visit id is kept only as a one-way hash. Unknown names are skipped."""
    if get_settings().rate_limit_enabled:
        if not await ratelimit.get_buckets().take(ratelimit.bucket_key("client-events", ":".join(caller_key(request))), *EVENTS_LIMIT):
            raise RateLimited("Too many analytics events. Please wait a minute.")
    return await service.record_client_events(session, body.events, body.sessionId, actor is not None)


def funnel_window(since, until):
    validate_dates(since, until)
    until = until or clock.now()
    return since or until - timedelta(days=30), until


@router.get("/v1/admin/analytics/funnels/onboarding")
async def onboarding_funnel(actor: CurrentActor, session: AnalyticsSession, since: datetime | None = Query(None, alias="from"),
                            until: datetime | None = Query(None, alias="to")):
    """Professional onboarding for [from, to) (default the last 30 days): per-step views, completions and drop-off,
    the completion rate, and the median time from sign-up to a published profile (from profile records)."""
    actor.require_capability(Cap.ANALYTICS_READ)
    since, until = funnel_window(since, until)
    published = await professional.publish_times(session, since, until)
    signed_up = await identity.created_at_many(session, list({i for i, _, _ in published}))
    hours = [(p - signed_up.get(i, c)).total_seconds() / 3600 for i, c, p in published]
    return await service.onboarding_funnel(session, since, until, hours)


@router.get("/v1/admin/analytics/funnels/request")
async def request_funnel(actor: CurrentActor, session: AnalyticsSession, since: datetime | None = Query(None, alias="from"),
                         until: datetime | None = Query(None, alias="to")):
    """The buyer request flow (per-step completion, abandonment per step) and the proposal flow for [from, to)."""
    actor.require_capability(Cap.ANALYTICS_READ)
    since, until = funnel_window(since, until)
    return await service.request_funnel(session, since, until)


@router.get("/v1/admin/analytics/funnels/search")
async def search_funnel(actor: CurrentActor, session: AnalyticsSession, since: datetime | None = Query(None, alias="from"),
                        until: datetime | None = Query(None, alias="to")):
    """Search micro-conversions for [from, to): filters, specializations, quick views, comparisons and more per 100 searches."""
    actor.require_capability(Cap.ANALYTICS_READ)
    since, until = funnel_window(since, until)
    return await service.search_micro_conversions(session, since, until)


@router.post("/v1/admin/analytics/rebuild")
async def rebuild(actor: CurrentActor, session: DbSession):
    actor.require_capability(Cap.ANALYTICS_REBUILD); actor.require_step_up()
    return await service.rebuild(session, actor)


def validate_dates(since, until):
    if since and since.tzinfo is None or until and until.tzinfo is None:
        raise ValidationFailed("Report dates require a timezone")
    if since and until and since >= until:
        raise ValidationFailed("The end date must follow the start date")


@router.get("/v1/reports/{role}")
async def report(role: Literal["buyer", "professional"], actor: CurrentActor, session: DbSession,
                 organizationId: uuid.UUID | None = None, format: Literal["json", "csv", "pdf"] = "json",
                 since: datetime | None = Query(None, alias="from"), until: datetime | None = Query(None, alias="to")):
    validate_dates(since, until)
    if role == "buyer":
        if not organizationId:
            raise ValidationFailed("Select an organisation")
        await member(session, actor, organizationId)
        rows = await service.facts(session, org_id=organizationId, since=since, until=until)
    else:
        pro = await own_professional(session, actor)
        rows = await service.facts(session, professional_id=pro.id, since=since, until=until)
    items = service.report(rows)
    record_audit(session, "analytics.report.exported", object_type="Report", object_id=role,
                 tenant_id=organizationId if role == "buyer" else None, details={"format": format, "rows": len(items)})
    if format == "json":
        snapshot_rows = await service.facts(session, org_id=organizationId) if role == "buyer" else await service.facts(session, professional_id=pro.id)
        return {"items": items, "summary": service.summarize(snapshot_rows, role=role), "summaryScope": "current snapshot",
                "amountUnit": "minor currency units"}
    fields = ["eventId", "date", "eventType", "contractId", "currency", "grossMinor", "feeMinor", "netMinor"]
    if format == "csv":
        buf = io.StringIO(); writer = csv.DictWriter(buf, fieldnames=fields); writer.writeheader(); writer.writerows(items)
        content, mime = buf.getvalue().encode(), "text/csv"
    else:
        content, mime = render_table_pdf("Zoikorum financial report", "Amounts in minor currency units (e.g. cents)", items), "application/pdf"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="zoikorum-{role}-report.{format}"'})
