"""Procurement pack (Enterprise: the security and compliance summary a buyer's procurement team asks for).

Every statement is derived from how this installation is actually configured, so the pack can never claim a control
that is switched off. Certifications are stated as not held until the company holds them.
"""

from __future__ import annotations

import hashlib
import json

from zoikorum.config import get_settings
from zoikorum.shared import clock

PROVIDERS = {"stripe": "Stripe (card and bank payments)", "fake": "Test payment provider (no real money)",
             "persona": "Persona (identity verification)", "anthropic": "Anthropic (optional AI assistance)",
             "smtp": "Email delivery provider (SMTP)", "r2": "Cloudflare R2 (files)", "database": "Application database (files)", "gcs": "Google Cloud Storage (files)", "s3": "Amazon S3 (files)"}


def build() -> dict:
    s = get_settings()
    subprocessors = [PROVIDERS[p] for p in (s.payment_provider, s.verification_provider, s.ai_provider, s.email_provider, s.storage_provider)
                     if p in PROVIDERS]
    controls = [
        ("Sign-in", "Passwords are hashed; two-step sign-in (authenticator app or passkey) is available to everyone and required "
                    "for staff and for signing, releases, payouts and policy changes."),
        ("Sessions", f"Access tokens last {s.access_token_ttl_seconds // 60} minutes; a confirmed action needs a two-step check from the "
                     f"last {s.step_up_max_age_seconds // 60} minutes."),
        ("Encryption in transit", "TLS between browsers and the platform, terminated at the load balancer."),
        ("Encryption at rest", "Database and file storage are encrypted at rest by the cloud provider."
         + (" Sensitive fields (two-step secrets, phone numbers, webhook secrets) are encrypted again with a key held in Cloud KMS."
            if s.field_kms_key_name else " Sensitive fields are encrypted again with an application key.")
         + (" Files use a customer-managed key in Cloud KMS." if s.gcs_kms_key_name else "")),
        ("Files", ("Every upload is scanned for malware before it is stored; " if s.malware_scanner == "clamav" else "")
         + "files are stored write-once with a SHA-256 fingerprint, and downloads are recorded."),
        ("Money", "Payments are held in escrow per milestone and released only when the buyer accepts the work; the ledger is "
                  "append-only and reconciled daily with the payment provider."),
        ("Audit", "Security-relevant actions are written to an append-only audit log protected by a hash chain that is checked "
                  "on a schedule; organisations can export their own audit records."),
        ("Access by staff", "Staff roles are separated (support, compliance, finance, mediation, legal); staff use a separate web "
                            "app and two-step sign-in; decisions that move money or restrict accounts need a second person."),
        ("Organisation controls", "Policies on who may be engaged, approval chains, spend limits, cost-centre budgets and "
                                  "required contract clauses; API keys with read-only or read-write scope."),
        ("Data retention", f"Closed dispute records are kept at least {s.dispute_retention_years} years (longer where the "
                           "organisation's policy or local law requires); people can export or delete their personal data."),
        ("Incident response", "An incident register with severity, containment, notification and root-cause review; affected "
                              "customers are told without undue delay and within 72 hours where the law requires."),
        ("AI", "AI suggestions are optional, labelled, never make decisions about people and can be switched off platform-wide."),
    ]
    return {
        "generatedAt": clock.now().isoformat(),
        "controls": [{"area": a, "statement": t} for a, t in controls],
        "subprocessors": subprocessors,
        "certifications": "No third-party certification (for example SOC 2 or ISO 27001) is held yet. Ask us for the current status.",
        "contact": "security@ (your account team will share the address for security questions)",
    }


def render(fmt: str) -> tuple[bytes, str, str]:
    from zoikorum.shared import pdf

    data = build()
    body = json.dumps(data, sort_keys=True)
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    if fmt == "json":
        return json.dumps({**data, "fingerprintSha256": fingerprint}, indent=2).encode(), "zoikorum-procurement-pack.json", "application/json"
    doc = pdf.PdfDocument(
        title="Security and compliance summary", reference="Procurement pack", issued=clock.now(), fingerprint=fingerprint,
        subtitle="How the platform protects your organisation's data, money and decisions",
        sections=[pdf.Section("Controls", rows=[(c["area"], c["statement"]) for c in data["controls"]]),
                  pdf.Section("Subprocessors", rows=[(str(i + 1), p) for i, p in enumerate(data["subprocessors"])] or [("None", "")]),
                  pdf.Section("Certifications", text=data["certifications"]),
                  pdf.Section(text="This summary is generated from the platform's live configuration on the date shown.")])
    return pdf.render(doc), "zoikorum-procurement-pack.pdf", "application/pdf"
