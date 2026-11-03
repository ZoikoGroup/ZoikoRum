import pytest
from pydantic import ValidationError

from zoikorum.domains.firm.schemas import FirmPatch
from zoikorum.domains.identity.schemas import MePatch
from zoikorum.domains.professional.schemas import ProfilePatch
from zoikorum.shared import validation as v

pytestmark = pytest.mark.unit


def test_person_name():
    assert v.person_name("  José  O'Brien-Smith Jr. ") == "José O'Brien-Smith Jr."
    assert v.person_name("வெங்கடேஷ் குமார்")  # combining marks are allowed
    for bad in ("Bob 2", "Bob@", "123", "", "..", "A_B"):
        with pytest.raises(ValueError):
            v.person_name(bad)


def test_org_role_city_language():
    assert v.org_name("Smith & Sons (UK), Ltd.") == "Smith & Sons (UK), Ltd."
    for bad in ("Acme 2", "A", "Acme #1"):
        with pytest.raises(ValueError):
            v.org_name(bad)
    assert v.role_title("CFO / Advisor, SaaS (Fractional)")
    with pytest.raises(ValueError):
        v.role_title("CFO 2")
    assert v.city_name("St. John's") and v.city_name("Hyderabad")
    with pytest.raises(ValueError):
        v.city_name("Paris 75")
    assert v.language_name("English") and v.language_name("Hindi-Urdu")
    with pytest.raises(ValueError):
        v.language_name("en_GB")


def test_registration_number():
    assert v.registration_number(" sc123456 ") == "SC123456"
    assert v.registration_number("U12345MH2020PTC123456") == "U12345MH2020PTC123456"
    assert v.registration_number("de-76/54") == "DE-76/54"
    for bad in ("abc", "AB 1234", "AB#1234", "X" * 31):
        with pytest.raises(ValueError):
            v.registration_number(bad)


def test_website():
    assert v.website_url("https://example.com/path?q=1") == "https://example.com/path?q=1"
    assert v.website_url("http://www.acme.co.uk")
    for bad in ("javascript:alert(1)", "data:text/html,x", "https://localhost", "https://exa mple.com", "example.com", "https://.com", "ftp://a.com"):
        with pytest.raises(ValueError):
            v.website_url(bad)


def test_schemas_enforce_rules_on_write():
    assert FirmPatch(legalName="Acme Ltd", registrationNumber="oc123456", website="https://acme.com").registrationNumber == "OC123456"
    assert FirmPatch(tradingName="", website="").website == ""  # blank clears
    for kw in ({"legalName": "Acme 2"}, {"tradingName": "X1 Co"}, {"registrationNumber": "AB!"}, {"website": "javascript:alert(1)"}):
        with pytest.raises(ValidationError):
            FirmPatch(**kw)
    for kw in ({"displayName": "Bob 1"}, {"city": "Rome1"}, {"headline": "CFO 2"}, {"languages": ["En1"]}, {"legalName": "A$"}):
        with pytest.raises(ValidationError):
            ProfilePatch(**kw)
    assert ProfilePatch(languages=["English", " "], city="Austin").languages == ["English"]
    with pytest.raises(ValidationError):
        MePatch(displayName="Ann 3")
    assert MePatch(displayName="Ann-Marie O'Neil").displayName == "Ann-Marie O'Neil"


def test_policy_names_and_law():
    assert v.policy_name("Acme & Co. (UK), Ltd") == "Acme & Co. (UK), Ltd"
    assert v.variant_name("St. John's-Land") == "St. John's-Land"
    assert v.governing_law("England and Wales (English law)") == "England and Wales (English law)"
    for fn, bad in ((v.policy_name, "Policy 2"), (v.policy_name, "A/B"), (v.variant_name, "UK & IE"), (v.variant_name, "UK1"),
                    (v.governing_law, "Law 4"), (v.governing_law, "Law & Co")):
        with pytest.raises(ValueError):
            fn(bad)


def test_iso_codes():
    assert v.iso_codes(["gb", "IE", "gb"], "country") == ["GB", "IE"]
    assert v.iso_codes(["usd", "EUR"], "currency") == ["EUR", "USD"]
    for kind, bad in (("country", ["ZZ"]), ("country", ["USD"]), ("currency", ["ABC"]), ("currency", ["US"]), ("country", [])):
        with pytest.raises(ValueError):
            v.iso_codes(bad, kind)


def test_policy_schemas_enforce_rules():
    from zoikorum.domains.policy.schemas import ContractVariantIn, ProfileIn, SettingsIn

    org = "00000000-0000-0000-0000-000000000001"
    assert ProfileIn(orgId=org, name="Acme Procurement").name == "Acme Procurement"
    with pytest.raises(ValidationError):
        ProfileIn(orgId=org, name="Policy 2")
    assert SettingsIn(allowedCurrencies=["usd", "eur"], allowedJurisdictions=["gb"]).allowedCurrencies == ["EUR", "USD"]
    for kw in ({"allowedCurrencies": ["ABC"]}, {"allowedJurisdictions": ["ZZ"]}, {"governingLaw": "Law 1"},
               {"acceptanceWindowDays": 5.5}, {"acceptanceWindowDays": "5"}, {"disputeRetentionYears": 2.0},
               {"disputeMediationAboveMinor": 10.5}, {"milestoneMaxSharePercent": True}):
        with pytest.raises(ValidationError):
            SettingsIn(**kw)
    assert SettingsIn(acceptanceWindowDays=7, disputeRetentionYears=3).acceptanceWindowDays == 7
    ok = {"id": "uk-1", "name": "United Kingdom", "jurisdictions": ["gb", "ie"], "governingLaw": "England and Wales"}
    assert ContractVariantIn(**ok).jurisdictions == ["GB", "IE"]
    for patch in ({"name": "UK 2"}, {"jurisdictions": ["GB", "ZZ"]}, {"governingLaw": "Law 3"}):
        with pytest.raises(ValidationError):
            ContractVariantIn(**{**ok, **patch})


def test_frontend_code_lists_match_backend():
    import re
    from pathlib import Path

    from zoikorum.shared.countries import ISO_3166
    from zoikorum.shared.currencies import ISO_4217

    lib = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib"
    for name, backend in (("countries.ts", ISO_3166), ("currencies.ts", ISO_4217)):
        body = re.search(r"`(.*?)`", (lib / name).read_text(encoding="utf8"), re.S).group(1)
        assert set(body.split()) == set(backend), name
    assert len(ISO_3166) == 249
