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
