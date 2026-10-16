import csv
import io
import uuid
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Query, Response
from zoikorum.domains.analytics import service
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.professional import facade as professional
from zoikorum.shared.auth import CurrentActor, PlatformRole
from zoikorum.shared.db import AnalyticsSession, DbSession
from zoikorum.shared.errors import NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit
from zoikorum.shared.report_pdf import render_pdf

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
    actor.require_platform_role(*PlatformRole.ALL)
    validate_dates(since, until)
    return await service.marketplace_health(session, since, until)


@router.post("/v1/admin/analytics/rebuild")
async def rebuild(actor: CurrentActor, session: DbSession):
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN); actor.require_step_up()
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
        lines = ["Zoikorum financial report | amounts in minor currency units", "Date                 Currency    Gross       Fee       Net  Event"]
        lines += [f"{r['date'][:19]} {r['currency'] or '---':>8} {r['grossMinor']:>10} {r['feeMinor']:>9} {r['netMinor']:>9} {r['eventType'].split('.')[-2]}" for r in items]
        content, mime = render_pdf(lines), "application/pdf"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="zoikorum-{role}-report.{format}"'})
