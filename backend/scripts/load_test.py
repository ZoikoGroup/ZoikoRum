"""Load test for a staging deployment: many simulated visitors and signed-in buyers at once, with a pass/fail verdict.

    python scripts/load_test.py --base-url https://staging.example.com --users 50 --duration 120 \
        [--email buyer@example.com --password ...] [--p95-ms 800] [--max-error-rate 0.01]

What each simulated user does, in a loop with short think time:
  - visitors: search professionals (a mix of queries and filters), open a public profile, read the taxonomy
  - signed-in buyers (only with --email/--password): their profile, contracts, unread notifications, organisations
  - a few "describe what you need" requests (light: they cost an AI call when Claude is configured)

It reports requests per second and p50/p95/p99 latency per endpoint, and exits 1 if p95 or the error rate is over the
limit, so it can gate a release. 429 (rate limited) responses are counted separately: they show the limiter working,
not a failure. To measure capacity rather than the limiter, raise or turn off rate limits on staging for the run
(ZK_RATE_LIMIT_ENABLED=false), and say so in the result.

Read-only apart from sign-in: it never creates, changes or pays for anything. It refuses production-looking URLs
unless --allow-production is given.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import defaultdict
from urllib.parse import urlparse

import httpx

QUERIES = ["tax", "transfer pricing", "fractional CFO", "machine learning", "audit", "data engineering", "SOX", "VAT",
           "cloud", "security", "contract", "payroll", "forecasting", "M&A", "", "", ""]
FILTERS = [{}, {"tier": "A,B"}, {"availability": "NOW"}, {"delivery": "REMOTE"}, {"sort": "verified"}, {"jurisdiction": "GB"},
           {"engagementType": "PROJECT"}, {"sort": "price_asc"}]
NEEDS = ["An ongoing fractional CFO who can start now, remote", "Transfer pricing documentation for our UK subsidiary",
         "A machine learning engineer to build a churn model"]


class Stats:
    def __init__(self) -> None:
        self.latency: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, int] = defaultdict(int)
        self.limited: dict[str, int] = defaultdict(int)
        self.samples: dict[str, str] = {}

    def record(self, name: str, ms: float, status: int | None, detail: str = "") -> None:
        if status == 429:
            self.limited[name] += 1
        elif status is None or status >= 400:
            self.errors[name] += 1
            self.samples.setdefault(name, detail or f"HTTP {status}")
        else:
            self.latency[name].append(ms)


async def timed(client: httpx.AsyncClient, stats: Stats, name: str, method: str, url: str, **kw) -> httpx.Response | None:
    start = time.perf_counter()
    try:
        r = await client.request(method, url, **kw)
    except httpx.HTTPError as exc:
        stats.record(name, 0, None, type(exc).__name__)
        return None
    stats.record(name, (time.perf_counter() - start) * 1000, r.status_code, f"HTTP {r.status_code}")
    return r


async def visitor(client: httpx.AsyncClient, stats: Stats, stop: float, think: float, ids: list[str]) -> None:
    while time.monotonic() < stop:
        params = {"q": random.choice(QUERIES), **random.choice(FILTERS), "limit": "20"}
        r = await timed(client, stats, "search", "GET", "/v1/search/professionals", params={k: v for k, v in params.items() if v})
        if r is not None and r.status_code == 200:
            found = [i["professionalId"] for i in r.json().get("items", [])]
            if found and len(ids) < 200:
                ids.extend(found)
        if ids:
            await timed(client, stats, "profile", "GET", f"/v1/professionals/{random.choice(ids)}")
        if random.random() < 0.2:
            await timed(client, stats, "taxonomy", "GET", "/v1/taxonomy")
        if random.random() < 0.03:
            await timed(client, stats, "describe-need", "POST", "/v1/search/intent", json={"text": random.choice(NEEDS)})
        await asyncio.sleep(random.uniform(0.5, 1.5) * think)


async def buyer(client: httpx.AsyncClient, stats: Stats, stop: float, think: float, token: str) -> None:
    h = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < stop:
        await timed(client, stats, "me", "GET", "/v1/me", headers=h)
        await timed(client, stats, "contracts", "GET", "/v1/contracts", params={"role": "buyer"}, headers=h)
        await timed(client, stats, "unread", "GET", "/v1/notifications/unread-count", headers=h)
        if random.random() < 0.3:
            await timed(client, stats, "organisations", "GET", "/v1/organizations/mine", headers=h)
        await asyncio.sleep(random.uniform(0.5, 1.5) * think)


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True, help="API base URL, e.g. https://staging-api.example.com")
    ap.add_argument("--users", type=int, default=20, help="simultaneous simulated users (default 20)")
    ap.add_argument("--duration", type=int, default=60, help="seconds (default 60)")
    ap.add_argument("--think", type=float, default=1.0, help="average seconds between a user's actions (default 1)")
    ap.add_argument("--buyer-share", type=float, default=0.3, help="share of users signed in as the buyer (default 0.3)")
    ap.add_argument("--email", help="a staging buyer account for the signed-in mix")
    ap.add_argument("--password", help="its password (two-step sign-in must be off for this account on staging)")
    ap.add_argument("--p95-ms", type=float, default=800, help="fail if any endpoint's p95 is above this (default 800)")
    ap.add_argument("--max-error-rate", type=float, default=0.01, help="fail above this share of errors (default 0.01)")
    ap.add_argument("--allow-production", action="store_true", help="run against a production-looking URL anyway")
    a = ap.parse_args()

    host = urlparse(a.base_url).hostname or ""
    if not a.allow_production and not any(w in host for w in ("staging", "stage", "test", "localhost", "127.0.0.1", "preview")):
        print(f"Refusing to load-test {host}: it does not look like staging. Use --allow-production if you are sure.")
        return 2

    stats = Stats()
    limits = httpx.Limits(max_connections=a.users * 2, max_keepalive_connections=a.users)
    async with httpx.AsyncClient(base_url=a.base_url.rstrip("/"), timeout=30, limits=limits) as client:
        try:
            ready = await client.get("/ready")
        except httpx.HTTPError as exc:
            print(f"Cannot reach {a.base_url} ({type(exc).__name__}); not starting.")
            return 2
        if ready.status_code != 200:
            print(f"The API is not ready ({ready.status_code}); not starting.")
            return 2
        token = None
        if a.email and a.password:
            r = await client.post("/v1/auth/login", json={"email": a.email, "password": a.password})
            if r.status_code != 200:
                print(f"Sign-in failed ({r.status_code}); check the account, or run without --email.")
                return 2
            token = r.json()["tokens"]["accessToken"]
        buyers = int(a.users * a.buyer_share) if token else 0
        print(f"{a.users} users ({buyers} signed in) for {a.duration}s against {a.base_url} ...")
        ids: list[str] = []
        stop = time.monotonic() + a.duration
        began = time.perf_counter()
        tasks = [buyer(client, stats, stop, a.think, token) for _ in range(buyers)]
        tasks += [visitor(client, stats, stop, a.think, ids) for _ in range(a.users - buyers)]
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - began

    names = sorted(set(stats.latency) | set(stats.errors) | set(stats.limited))
    total_ok = sum(len(v) for v in stats.latency.values())
    total_err = sum(stats.errors.values())
    total_limited = sum(stats.limited.values())
    total = total_ok + total_err + total_limited
    print(f"\n{'endpoint':<16}{'ok':>8}{'errors':>8}{'429':>7}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'mean ms':>9}")
    failed = []
    for n in names:
        v = stats.latency[n]
        p95 = pct(v, 95)
        print(f"{n:<16}{len(v):>8}{stats.errors[n]:>8}{stats.limited[n]:>7}{pct(v, 50):>9.0f}{p95:>9.0f}{pct(v, 99):>9.0f}"
              f"{(statistics.fmean(v) if v else 0):>9.0f}")
        if p95 > a.p95_ms:
            failed.append(f"{n} p95 {p95:.0f} ms > {a.p95_ms:.0f} ms")
    rate = total_err / total if total else 1.0
    print(f"\n{total} requests in {elapsed:.0f}s = {total / elapsed:.1f} requests/s; errors {rate:.2%}; rate limited {total_limited}")
    for n, sample in stats.samples.items():
        print(f"  first {n} error: {sample}")
    if total == 0:
        failed.append("no requests completed")
    if rate > a.max_error_rate:
        failed.append(f"error rate {rate:.2%} > {a.max_error_rate:.2%}")
    if total_limited and total_limited > total * 0.05:
        print("Note: over 5% of requests were rate limited. To measure capacity, raise or turn off rate limits on staging.")
    print("\nRESULT: " + ("PASS" if not failed else "FAIL - " + "; ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
