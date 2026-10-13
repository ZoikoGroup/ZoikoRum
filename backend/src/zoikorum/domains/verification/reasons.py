"""Standard reasons for verification decisions, so outcomes are consistent, explained the same way and can be counted.

Staff pick one in the review screen; its message is pre-filled for the professional and can be edited. The API still
accepts other codes (older records, scripts and integrations use them); "OTHER" is the choice for anything not listed.
"""

from __future__ import annotations

# code, label for staff, decisions it fits, message pre-filled for the professional
DECISION_REASONS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("DOCUMENT_MATCH", "Document matches the claim", ("VERIFIED",), ""),
    ("REGISTRY_MATCH", "Confirmed with the official register", ("VERIFIED",), ""),
    ("PARTNER_VERIFIED", "Identity partner's capture reviewed and accepted", ("VERIFIED",), ""),
    ("NO_DOCUMENT", "No document uploaded yet", ("NEEDS_INFO",),
     "We need {expected} to complete this check. Please upload it on your Verification page."),
    ("DOCUMENT_UNRELATED", "Document is unrelated to the check", ("NEEDS_INFO", "FAILED"),
     "The file you uploaded is not the document we asked for. Please upload {expected}."),
    ("WRONG_DOCUMENT_TYPE", "Wrong type of document", ("NEEDS_INFO",),
     "This type of document cannot be used for this check. Please upload {expected}."),
    ("UNREADABLE", "Unreadable, blurry or cropped", ("NEEDS_INFO",),
     "We could not read your document. Please upload a clear, complete photo or scan with all four corners visible."),
    ("EXPIRED_DOCUMENT", "Document has expired", ("NEEDS_INFO", "FAILED"),
     "Your document has expired. Please upload one that is currently valid."),
    ("NAME_MISMATCH", "Name does not match the account", ("NEEDS_INFO", "FAILED"),
     "The name on the document does not match the name on your account. Upload a document in your name, or contact "
     "support if your name has changed."),
    ("DETAILS_MISMATCH", "Details do not match what was entered", ("NEEDS_INFO", "FAILED"),
     "The details on the document (number, issuer or jurisdiction) do not match what you entered. Please correct them "
     "or upload the matching document."),
    ("NOT_IN_REGISTER", "Not found in the official register", ("NEEDS_INFO", "FAILED"),
     "We could not find this licence in the official register. Please check the registration number and jurisdiction."),
    ("SUSPECTED_ALTERED", "Document appears altered or fake", ("FAILED",),
     "We could not accept this document. If you think this is a mistake, you can appeal with an original document."),
    ("OTHER", "Other (write your own message)", ("VERIFIED", "NEEDS_INFO", "FAILED"), ""),
]

# Decisions with these reasons are also raised with Trust & Safety.
ESCALATE = ("SUSPECTED_ALTERED",)

EXPECTED_SHORT = {
    "IDENTITY": "your passport, national ID card or driving licence",
    "CREDENTIAL": "your licence, certificate or registration",
    "FIRM_REGISTRATION": "your firm's company registration certificate",
    "INSURANCE": "your professional indemnity insurance certificate",
    "JURISDICTION": "proof of your right to practise in that jurisdiction",
}


# Reasons that only make sense for some checks (the rest fit every check). The list only guides the review screen.
ONLY_FOR = {
    "PARTNER_VERIFIED": ("IDENTITY",),
    "REGISTRY_MATCH": ("CREDENTIAL", "FIRM_REGISTRATION", "JURISDICTION"),
    "NOT_IN_REGISTER": ("CREDENTIAL", "FIRM_REGISTRATION", "JURISDICTION"),
}


def reasons_for(verification_type: str | None = None) -> list[dict]:
    expected = EXPECTED_SHORT.get(verification_type or "", "the document we asked for")
    return [{"code": code, "label": label, "decisions": list(decisions), "message": message.format(expected=expected)}
            for code, label, decisions, message in DECISION_REASONS
            if not verification_type or verification_type in ONLY_FOR.get(code, (verification_type,))]
