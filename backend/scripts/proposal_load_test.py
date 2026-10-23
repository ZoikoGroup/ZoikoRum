"""Write-path load test for STAGING: the proposal flow, with a pass/fail verdict.

    python scripts/proposal_load_test.py --base-url https://staging.example.com --accounts accounts.json \
        --workers 10 --duration 120 [--p95-ms 1000] [--max-error-rate 0.01]

accounts.json (test accounts that exist on staging, two-step sign-in off for them; never real customers):

    {"buyers": [{"email": "load-buyer-1@test.example", "password": "...", "organizationId": "<uuid>"}],
     "professionals": [{"email": "load-pro-1@test.example", "password": "...", "professionalId": "<uuid>"}]}

Each worker loops: a buyer sends a proposal request to one professional (Idempotency-Key, like the web app), the
professional drafts a two-milestone proposal and submits it, the buyer reads it and rejects it, and the request is
cancelled - so every iteration ends closed and staging does not fill up with open work. Nothing is accepted, signed or
paid (reason codes NOT_SELECTED and BUYER_CANCELLED).

It refuses a URL that does not look like staging (no --allow-production switch: this test writes data), reports p50/p95/
p99 per step, and exits 1 when p95 or the error rate is over the limit. 429 answers are counted apart (the limiter
working); for capacity runs raise or turn off rate limits on staging and say so in the result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_test import Stats, pct  # noqa: E402 - same reporting as the read-path load test

STAGING_WORDS = ("staging", "stage", "test", "localhost", "127.0.0.1", "preview")


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


async def step(client: httpx.AsyncClient, stats: Stats, name: str, method: str, url: str, token: str, *, idem: bool = False,
               **kw) -> httpx.Response | None:
    headers = {"Authorization": f"Bearer {token}"}
    if idem:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    start = time.perf_counter()
    try:
        r = await client.request(method, url, headers=headers, **kw)
    except httpx.HTTPError as exc:
        stats.record(name, 0, None, type(exc).__name__)
        return None
    stats.record(name, (time.perf_counter() - start) * 1000, r.status_code, f"HTTP {r.status_code}: {r.text[:120]}")
    return r if r.status_code < 400 else None


async def sign_in(client: httpx.AsyncClient, account: dict) -> str:
    r = await client.post("/v1/auth/login", json={"email": account["email"], "password": account["password"]})
    if r.status_code != 200:
        raise SystemExit(f"Sign-in failed for a test account ({r.status_code}); check accounts.json.")
    return r.json()["tokens"]["accessToken"]


async def iteration(client: httpx.AsyncClient, stats: Stats, buyer: dict, pro: dict, n: int) -> None:
    r = await step(client, stats, "request.create", "POST", "/v1/proposal-requests", buyer["token"], idem=True, json={
        "organizationId": buyer["organizationId"], "professionalIds": [pro["professionalId"]],
        "service": "Load test engagement", "engagementType": "PROJECT", "objective": f"Load test iteration {n}",
        "details": "Synthetic staging load test; will be rejected and cancelled.", "desiredStartDate": day(10),
        "estimatedDuration": "THREE_SIX_WEEKS", "budget": {"maxMinor": 1_000_000, "currency": "USD"},
        "deliverables": ["Report"], "acknowledged": True})
    if r is None:
        return
    req = r.json()[0]
    r = await step(client, stats, "proposal.draft", "POST", f"/v1/proposal-requests/{req['id']}/proposals", pro["token"], json={
        "summary": "Synthetic proposal from the staging load test.", "scopeAlignment": "CONFIRMED",
        "deliverables": [{"key": "a", "title": "Draft", "acceptanceCriteria": "Delivered"},
                         {"key": "b", "title": "Final", "acceptanceCriteria": "Accepted"}],
        "milestones": [{"title": "Draft", "amountMinor": 300_000, "deliverableKeys": ["a"]},
                       {"title": "Final", "amountMinor": 200_000, "deliverableKeys": ["b"]}],
        "pricingModel": "FIXED", "currency": "USD", "startDate": day(10), "endDate": day(40), "validUntil": day(20)})
    if r is not None:
        proposal = r.json()
        if await step(client, stats, "proposal.submit", "POST", f"/v1/proposals/{proposal['id']}/submit", pro["token"], idem=True):
            await step(client, stats, "proposal.read", "GET", f"/v1/proposals/{proposal['id']}", buyer["token"])
            await step(client, stats, "proposal.reject", "POST", f"/v1/proposals/{proposal['id']}/reject", buyer["token"], idem=True,
                       json={"reasonCode": "NOT_SELECTED", "note": "Load test"})
    await step(client, stats, "request.cancel", "POST", f"/v1/proposal-requests/{req['id']}/cancel", buyer["token"], idem=True,
               json={"reasonCode": "BUYER_CANCELLED", "note": "Load test"})


async def worker(client: httpx.AsyncClient, stats: Stats, stop: float, think: float, buyers: list[dict], pros: list[dict]) -> None:
    n = 0
    while time.monotonic() < stop:
        n += 1
        await iteration(client, stats, random.choice(buyers), random.choice(pros), n)
        await asyncio.sleep(random.uniform(0.5, 1.5) * think)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--accounts", required=True, help="JSON file with staging test accounts (see above)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--think", type=float, default=1.0)
    ap.add_argument("--p95-ms", type=float, default=1000)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    a = ap.parse_args()

    host = urlparse(a.base_url).hostname or ""
    if not any(w in host for w in STAGING_WORDS):
        print(f"Refusing to run a write load test against {host}: staging only.")
        return 2
    accounts = json.loads(Path(a.accounts).read_text(encoding="utf-8"))
    if not accounts.get("buyers") or not accounts.get("professionals"):
        print("accounts.json needs at least one buyer and one professional.")
        return 2
    stats = Stats()
    async with httpx.AsyncClient(base_url=a.base_url.rstrip("/"), timeout=30,
                                 limits=httpx.Limits(max_connections=a.workers * 3)) as client:
        if (await client.get("/ready")).status_code != 200:
            print("The API is not ready; not starting.")
            return 2
        buyers = [{**b, "token": await sign_in(client, b)} for b in accounts["buyers"]]
        pros = [{**p, "token": await sign_in(client, p)} for p in accounts["professionals"]]
        print(f"{a.workers} workers for {a.duration}s against {a.base_url} (proposal write path) ...")
        stop = time.monotonic() + a.duration
        began = time.perf_counter()
        await asyncio.gather(*[worker(client, stats, stop, a.think, buyers, pros) for _ in range(a.workers)])
        elapsed = time.perf_counter() - began

    names = sorted(set(stats.latency) | set(stats.errors) | set(stats.limited))
    total_ok = sum(len(v) for v in stats.latency.values())
    total_err, total_limited = sum(stats.errors.values()), sum(stats.limited.values())
    total = total_ok + total_err + total_limited
    print(f"\n{'step':<18}{'ok':>7}{'errors':>8}{'429':>6}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}")
    failed = []
    for n in names:
        v = stats.latency[n]
        print(f"{n:<18}{len(v):>7}{stats.errors[n]:>8}{stats.limited[n]:>6}{pct(v, 50):>9.0f}{pct(v, 95):>9.0f}{pct(v, 99):>9.0f}")
        if pct(v, 95) > a.p95_ms:
            failed.append(f"{n} p95 {pct(v, 95):.0f} ms > {a.p95_ms:.0f} ms")
    rate = total_err / total if total else 1.0
    print(f"\n{total} requests in {elapsed:.0f}s = {total / max(elapsed, 1e-9):.1f}/s; errors {rate:.2%}; rate limited {total_limited}")
    for n, sample in stats.samples.items():
        print(f"  first {n} error: {sample}")
    if total == 0:
        failed.append("no requests completed")
    if rate > a.max_error_rate:
        failed.append(f"error rate {rate:.2%} > {a.max_error_rate:.2%}")
    print("\nRESULT: " + ("PASS" if not failed else "FAIL - " + "; ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
