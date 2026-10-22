"""Maker-checker in tests: privileged staff endpoints answer 202 with an approval request, and a second staff member
approves it (admin/approvals.py)."""

from __future__ import annotations

A = "/v1/admin/approval-requests"


async def approve(client, approver, request: dict, note: str | None = None) -> dict:
    """``approver`` (a different staff member holding the required role) approves; returns the decided request."""
    await approver.step_up()
    r = await client.post(f"{A}/{request['id']}/decision", headers=approver.h, json={"approve": True, "note": note})
    assert r.status_code == 200, r.text
    return r.json()


async def approved(client, response, approver) -> dict:
    """A 202 approval request from ``response``, approved and carried out."""
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "REQUESTED"
    done = await approve(client, approver, response.json())
    assert done["status"] == "APPLIED", done
    return done
