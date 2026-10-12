"""Demo data for manual testing: one staff account, Venky (professional) and Lennox (customer) with every operation.

    .\\start-dev.ps1                                   # API on :8000 and the worker must be running
    .venv\\Scripts\\python.exe backend\\scripts\\seed_demo.py                   # accounts and every operation
    .venv\\Scripts\\python.exe backend\\scripts\\seed_demo.py --accounts-only   # just the four sign-ins, nothing else

Everything goes through the API (the same calls the app makes), so the data is what real use would create:
  Staff   zoikostaff@rum.com     all staff roles (Platform Admin, Compliance, Mediator, Financial Ops, T&S, Legal)
  Venky   venky.demo@example.com      published, verified (Tier B), offerings, payout account, a credential awaiting review
  Lennox  lennox.demo@example.com     buyer organisation, saved professional and search
  Asha    asha.demo@example.com       a second professional (published, not verified) so search has variety
Between Venky and Lennox: an open request, a proposal awaiting decision, an engagement awaiting acceptance, one
completed and reviewed (invoices, payouts), one in dispute, and messages. Password for all: ZoikoDemo@123.

--accounts-only: the same four sign-ins (email confirmed, staff with every role) and nothing else, for testing from
scratch: Venky and Asha start without a profile, Lennox with the organisation every buyer gets at sign-up.

Development only: refuses to run unless the local settings say ZK_ENV=local/development; stops if the demo
accounts already exist. Uses the development two-step bypass (ZK_DEV_SKIP_MFA=true) for signing and staff tools.
"""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx

API = os.environ.get("ZK_SEED_API", "http://127.0.0.1:8000")
PASSWORD = "ZoikoDemo@123"
STAFF = ("zoikostaff@rum.com", "Zoikorum Staff")
BACKEND = Path(__file__).resolve().parents[1]
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def pdf(name: str, body: bytes) -> dict:
    data = b"%PDF-1.4\n" + body
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "contentType": "application/pdf",
            "dataBase64": base64.b64encode(data).decode()}


class User:
    def __init__(self, http: httpx.Client, email: str, token: str):
        self.http, self.email, self.token = http, email, token

    def call(self, method: str, path: str, body=None, idem: bool = False, ok=(200, 201, 204)):
        headers = {"Authorization": f"Bearer {self.token}"}
        if idem:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        r = self.http.request(method, path, json=body, headers=headers)
        if r.status_code not in ok:
            sys.exit(f"FAILED {method} {path}: {r.status_code} {r.text[:400]}")
        return r.json() if r.content else None

    def relogin(self):
        r = self.http.post("/v1/auth/login", json={"email": self.email, "password": PASSWORD})
        self.token = r.json()["tokens"]["accessToken"]


def eventually(check, what: str, seconds: float = 30):
    end = time.time() + seconds
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(0.4)
    sys.exit(f"Timed out waiting for {what}. Is the worker running (start-dev.ps1 starts it)?")


def sign_up(http, email, name, account_type, country) -> User:
    r = http.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "displayName": name, "country": country,
                                             "accountType": account_type, "acceptTerms": True})
    if r.status_code != 201:
        sys.exit(f"Could not create {email}: {r.status_code} {r.text[:300]}")
    body = r.json()
    if body.get("emailConfirmationToken"):
        http.post("/v1/auth/confirm-email", json={"token": body["emailConfirmationToken"]})
    return User(http, email, body["tokens"]["accessToken"])


def preflight(http):
    sys.path.insert(0, str(BACKEND / "src"))
    os.chdir(BACKEND)  # read backend/.env like the API does
    from zoikorum.config import get_settings

    if get_settings().env not in ("local", "development"):
        sys.exit("seed_demo.py is for local development only (ZK_ENV must be local or development)")
    try:
        ready = http.get("/ready")
    except httpx.HTTPError:
        sys.exit(f"The API is not running at {API}. Start it with .\\start-dev.ps1 first.")
    if ready.status_code != 200:
        sys.exit(f"The API is not ready: {ready.text[:200]} (run 'alembic upgrade head' in backend/)")
    if http.post("/v1/auth/login", json={"email": "venky.demo@example.com", "password": PASSWORD}).status_code == 200:
        sys.exit("Demo data is already there (venky.demo@example.com exists). Reset the database to seed again.")


def staff_account(http) -> User:
    env = {**os.environ, "ZK_ADMIN_PASSWORD": PASSWORD}
    if os.environ.get("ZK_SEED_DATABASE_URL"):  # the database behind ZK_SEED_API, when it is not the one in backend/.env
        env["ZK_DATABASE_URL"] = os.environ["ZK_SEED_DATABASE_URL"]
    subprocess.run([sys.executable, "-m", "zoikorum.cli", "create-admin", "--email", STAFF[0], "--name", STAFF[1], "--country", "IN"],
                   cwd=BACKEND, env={**env, "PYTHONPATH": str(BACKEND / "src")}, check=True, stdout=subprocess.DEVNULL)
    r = http.post("/v1/auth/login", json={"email": STAFF[0], "password": PASSWORD})
    staff = User(http, STAFF[0], r.json()["tokens"]["accessToken"])
    me = staff.call("GET", "/v1/me")
    for role in ("COMPLIANCE_OFFICER", "MEDIATOR", "FINANCIAL_OPS", "TS_ANALYST", "LEGAL"):
        staff.call("POST", f"/v1/admin/identities/{me['id']}/platform-roles", {"role": role})
    staff.relogin()
    return staff


def professional(http, email, name, country, *, headline, bio, primary, secondary, served, offerings) -> tuple[User, dict]:
    u = sign_up(http, email, name, "PROFESSIONAL", country)
    pro = u.call("POST", "/v1/professionals", {})
    u.call("PUT", "/v1/professionals/me/photo", {"contentType": "image/png", "dataBase64": PNG})
    u.call("PATCH", "/v1/professionals/me", {"headline": headline, "bio": bio, "legalName": name,
                                              "engagementTypes": ["PROJECT", "RETAINER"], "deliveryModes": ["REMOTE"],
                                              "pricingModels": ["FIXED", "HOURLY"], "yearsExperienceBand": "3-5",
                                              "languages": ["English"], "city": "Hyderabad" if country == "IN" else "London"})
    u.call("PUT", "/v1/professionals/me/specializations", {"primary": primary, "secondary": secondary})
    u.call("PUT", "/v1/professionals/me/jurisdictions", {"served": served, "licensed": [], "crossBorderAcknowledged": True})
    u.call("PUT", "/v1/professionals/me/availability", {"availability": "NOW", "maxConcurrentEngagements": 4, "weeklyHours": 30})
    for title, price in offerings:
        o = u.call("POST", "/v1/professionals/me/offerings", {
            "title": title, "specialization": primary, "deliverables": ["Working solution", "Documentation"],
            "engagementTypes": ["PROJECT"], "pricingModel": "FIXED", "startingPrice": {"amountMinor": price, "currency": "USD"}})
        u.call("POST", f"/v1/professionals/me/offerings/{o['id']}/activate")
    u.call("POST", "/v1/professionals/me/publish", {"attestAccurate": True})
    return u, pro


def verify_identity(pro_user: User, pro: dict, staff: User):
    case = pro_user.call("POST", "/v1/verification/cases", {"verificationType": "IDENTITY", "subjectType": "PROFESSIONAL",
                                                            "subjectId": pro["id"]})
    config = pro_user.call("GET", "/v1/verification/configuration")
    if config.get("provider") == "simulated":  # the development identity partner: give its answer
        pro_user.call("POST", f"/v1/verification/cases/{case['id']}/hosted-session")
        pro_user.call("POST", f"/v1/verification/cases/{case['id']}/hosted-simulate", {"status": "approved"})
    else:  # upload a document and let the compliance officer decide
        pro_user.call("POST", f"/v1/verification/cases/{case['id']}/evidence",
                      {"evidenceType": "ID_DOCUMENT", "items": [pdf("passport.pdf", b"demo passport")]})
        staff.call("POST", f"/v1/verification/cases/{case['id']}/decision", {"decision": "VERIFIED", "reasonCode": "DOCUMENT_MATCH"})
    eventually(lambda: pro_user.call("GET", f"/v1/trust/professionals/{pro['id']}")["tier"] in ("A", "B"), "Venky's Tier B")


def request(buyer: User, org: dict, pro: dict, service: str, objective: str) -> dict:
    (req,) = buyer.call("POST", "/v1/proposal-requests", {
        "organizationId": org["id"], "professionalIds": [pro["id"]], "service": service, "engagementType": "PROJECT",
        "objective": objective, "details": "Data lives in Postgres; we deploy on AWS.", "desiredStartDate": day(7),
        "estimatedDuration": "THREE_SIX_WEEKS", "budget": {"maxMinor": 2_500_000, "currency": "USD"}, "acknowledged": True}, idem=True)
    return req


def proposal(pro_user: User, req: dict, title: str, submit: bool = True) -> dict:
    p = pro_user.call("POST", f"/v1/proposal-requests/{req['id']}/proposals", {
        "summary": f"I will deliver {title.lower()} in two milestones, each with clear acceptance criteria.", "scopeAlignment": "CONFIRMED",
        "deliverables": [{"key": "build", "title": f"{title}: build", "acceptanceCriteria": "Runs on your infrastructure with tests passing"},
                         {"key": "handover", "title": f"{title}: handover", "acceptanceCriteria": "Documentation and a recorded walkthrough"}],
        "milestones": [{"title": "Build", "amountMinor": 1_200_000, "deliverableKeys": ["build"]},
                       {"title": "Handover", "amountMinor": 400_000, "deliverableKeys": ["handover"]}],
        "pricingModel": "FIXED", "currency": "USD", "startDate": day(7), "endDate": day(45), "validUntil": day(20),
        "assumptions": ["Read access to the data within week 1"], "exclusions": ["Front-end design"]})
    if submit:
        pro_user.call("POST", f"/v1/proposals/{p['id']}/submit", idem=True)
    return p


def contract_from(buyer: User, pro_user: User, p: dict) -> dict:
    buyer.call("POST", f"/v1/proposals/{p['id']}/accept", idem=True)
    c = eventually(lambda: next((x for x in buyer.call("GET", "/v1/contracts?role=buyer&limit=100")["items"]
                                 if x["proposalId"] == p["id"]), None), "the contract")
    buyer.call("POST", f"/v1/contracts/{c['id']}/sign", {"termsHash": c["termsHash"]}, idem=True)
    pro_user.call("POST", f"/v1/contracts/{c['id']}/sign", {"termsHash": c["termsHash"]}, idem=True)
    eventually(lambda: buyer.call("GET", f"/v1/contracts/{c['id']}")["status"] == "ACTIVE", "the active contract")
    return buyer.call("GET", f"/v1/contracts/{c['id']}")


def fund_and_submit(buyer: User, pro_user: User, c: dict, milestones: list[dict], note: str):
    def opened():  # the worker opens escrow when the contract activates; until then the API answers 404
        found = buyer.call("GET", f"/v1/escrow/by-contract/{c['id']}", ok=(200, 404))
        return found if found and "id" in found else None

    escrow = eventually(opened, "escrow")
    buyer.call("POST", f"/v1/escrow/{escrow['id']}/fund", {"milestoneIds": [m["id"] for m in milestones],
                                                           "paymentMethodToken": "tok_visa"}, idem=True)
    for m in milestones:
        eventually(lambda m=m: next(x for x in pro_user.call("GET", f"/v1/contracts/{c['id']}")["milestones"]
                                    if x["id"] == m["id"])["status"] == "IN_PROGRESS", "the funded milestone")
        pro_user.call("POST", f"/v1/milestones/{m['id']}/submit", {"note": note, "files": [pdf(f"{m['title']}.pdf", note.encode())]})


def accounts_only(http) -> None:
    staff_account(http)
    sign_up(http, "venky.demo@example.com", "Venky Bongu", "PROFESSIONAL", "IN")
    sign_up(http, "asha.demo@example.com", "Asha Menon", "PROFESSIONAL", "GB")
    lennox = sign_up(http, "lennox.demo@example.com", "Lennox Shaw", "BUYER", "GB")
    eventually(lambda: (lennox.relogin(), lennox.call("GET", "/v1/organizations/mine"))[1], "Lennox's organisation")


def main() -> None:
    http = httpx.Client(base_url=API, timeout=30)
    preflight(http)
    print("Creating staff ...")
    if "--accounts-only" in sys.argv[1:]:
        accounts_only(http)
        print(f"""
Accounts ready, nothing else (password for every account: {PASSWORD})
  Staff   {STAFF[0]}    every staff role
  Venky   venky.demo@example.com     Professional, no profile yet
  Asha    asha.demo@example.com      Professional, no profile yet
  Lennox  lennox.demo@example.com    Customer, with an organisation
Open http://localhost:5173/login""")
        return
    staff = staff_account(http)

    print("Creating Venky (professional) ...")
    venky, venky_pro = professional(
        http, "venky.demo@example.com", "Venky Bongu", "IN", headline="AI/ML engineer for startups",
        bio=("I build machine-learning features for startups: data pipelines, model training and evaluation, and the APIs "
             "that serve them in production. Clear milestones, weekly demos and documentation you can hand over."),
        primary="ai-machine-learning-engineering", secondary=["generative-ai-and-llm-applications", "data-engineering"],
        served=["IN", "GB", "US"], offerings=[("Churn prediction model", 1_200_000), ("LLM support assistant", 1_600_000)])
    verify_identity(venky, venky_pro, staff)
    venky.call("PUT", "/v1/payout-accounts/me", {"holderName": "Venky Bongu", "country": "IN", "currency": "USD",
                                                 "accountNumber": "000123456789"})
    venky.call("POST", "/v1/professionals/me/credentials", {
        "credentialType": "CERTIFICATION", "name": "AWS Certified Machine Learning - Specialty", "issuingBody": "Amazon Web Services",
        "registrationNumber": "AWS-ML-0042", "jurisdiction": "us", "expiresOn": day(700),
        "specialization": "ai-machine-learning-engineering"})

    print("Creating Asha (second professional) ...")
    professional(http, "asha.demo@example.com", "Asha Menon", "GB", headline="Fractional finance lead for SaaS",
                 bio=("Month-end close, board reporting and cash forecasting for growing SaaS companies. I set up the routines "
                      "your investors expect and train your team to run them."),
                 primary="fractional-cfo", secondary=[], served=["GB", "US"], offerings=[("Month-end close setup", 900_000)])

    print("Creating Lennox (customer) ...")
    lennox = sign_up(http, "lennox.demo@example.com", "Lennox Shaw", "BUYER", "GB")
    org = eventually(lambda: (lennox.relogin(), lennox.call("GET", "/v1/organizations/mine"))[1], "Lennox's organisation")[0]
    lennox.call("POST", "/v1/saved/professionals", {"professionalId": venky_pro["id"]})
    lennox.call("POST", "/v1/saved/searches", {"name": "Machine learning, verified", "params": {"q": "machine learning", "tier": "B"}})

    print("Engagement 1: completed, paid and reviewed ...")
    r1 = request(lennox, org, venky_pro, "Churn prediction model", "Predict which customers will cancel next quarter")
    c1 = contract_from(lennox, venky, proposal(venky, r1, "Churn model"))
    fund_and_submit(lennox, venky, c1, c1["milestones"], "Delivered with tests and a model card.")
    for m in c1["milestones"]:
        lennox.call("POST", f"/v1/milestones/{m['id']}/accept", idem=True)
    eventually(lambda: lennox.call("GET", f"/v1/contracts/{c1['id']}")["status"] == "COMPLETED", "the completed engagement")
    lennox.call("POST", f"/v1/contracts/{c1['id']}/review", {"rating": 5, "comment": "Clear milestones and excellent handover."}, idem=True)

    print("Engagement 2: work delivered, waiting for Lennox to accept ...")
    r2 = request(lennox, org, venky_pro, "LLM support assistant", "Answer customer questions from our help centre")
    c2 = contract_from(lennox, venky, proposal(venky, r2, "Support assistant"))
    fund_and_submit(lennox, venky, c2, c2["milestones"][:1], "First version live on staging; see the demo link.")

    print("Engagement 3: in dispute ...")
    r3 = request(lennox, org, venky_pro, "Demand forecasting", "Weekly demand forecast per warehouse")
    c3 = contract_from(lennox, venky, proposal(venky, r3, "Forecasting"))
    fund_and_submit(lennox, venky, c3, c3["milestones"][:1], "Forecast pipeline delivered.")
    lennox.call("POST", "/v1/disputes", {"contractId": c3["id"], "milestoneIds": [c3["milestones"][0]["id"]],
                                         "category": "QUALITY_ACCEPTANCE", "desiredOutcome": "PARTIAL_REFUND",
                                         "summary": "The forecast misses the agreed accuracy on two warehouses."}, idem=True)

    print("A proposal waiting for Lennox, and an open request waiting for Venky ...")
    r4 = request(lennox, org, venky_pro, "Recommendation engine", "Product recommendations on our storefront")
    proposal(venky, r4, "Recommendations")
    request(lennox, org, venky_pro, "Data warehouse audit", "Review our dbt models and costs")

    print("Messages, saved buyer and reconciliation ...")
    # The conversation for engagement 2 (open); engagement 3's is read-only while its dispute runs.
    thread = eventually(lambda: next((t for t in lennox.call("GET", "/v1/threads?limit=100")["items"]
                                      if t.get("canSend") and t.get("contextId") in (r2["id"], c2["id"])), None), "a conversation")
    lennox.call("POST", f"/v1/threads/{thread['id']}/messages", {"body": "Thanks Venky - the staging demo looks great. One question on rate limits."}, idem=True)
    venky.call("POST", f"/v1/threads/{thread['id']}/messages", {"body": "Happy to help. Limits are configurable; I'll add a note to the handover."}, idem=True)
    venky.call("POST", "/v1/professionals/me/saved-buyers", {"organizationId": org["id"], "note": "Repeat client; prefers weekly demos"})
    staff.call("POST", "/v1/payments/reconciliations", {"day": date.today().isoformat()})

    print(f"""
Demo data ready (password for every account: {PASSWORD})
  Staff   {STAFF[0]}
  Venky   venky.demo@example.com     Professional, Tier B
  Lennox  lennox.demo@example.com    Customer
  Asha    asha.demo@example.com      Professional, not verified
Open http://localhost:5173/login""")


if __name__ == "__main__":
    main()
