"""The env templates list every setting and load as they are, and check-config tells a deployer what is missing
without ever printing a value."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from prodsettings import PRODUCTION
from zoikorum import config_check
from zoikorum.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
LOCAL, SERVER = BACKEND / ".env.example", BACKEND / ".env.production.example"


def names(path: Path) -> set[str]:
    return set(re.findall(r"^(ZK_[A-Z0-9_]+)=", path.read_text(encoding="utf-8"), flags=re.M))


@pytest.fixture
def no_env(monkeypatch):
    """Only the file decides: the test run's own ZK_ variables would otherwise win over it."""
    for key in [k for k in os.environ if k.startswith("ZK_")]:
        monkeypatch.delenv(key)


@pytest.mark.unit
@pytest.mark.parametrize("path", [LOCAL, SERVER], ids=["local", "server"])
def test_templates_list_every_setting(path):
    every = {f"ZK_{n.upper()}" for n in Settings.model_fields}
    server_omits = {"ZK_DEV_SKIP_MFA", "ZK_STORAGE_DIR", "ZK_KAFKA_BOOTSTRAP", "ZK_SERVICE_NAME", "ZK_JWT_ISSUER"}
    expected = every - {"ZK_SERVICE_NAME", "ZK_JWT_ISSUER"} - (server_omits if path == SERVER else set())
    assert expected - names(path) == set()
    assert names(path) - every == set()  # no setting the app does not read


@pytest.mark.unit
def test_local_template_loads_as_is(no_env):
    s = Settings(_env_file=LOCAL)
    assert s.env == "local" and s.storage_provider == "local" and s.redis_url is None  # blank means the default
    assert s.payment_operating_countries == [] and s.verification_provider == "simulated"


@pytest.mark.unit
def test_server_template_is_refused_until_filled_in(no_env, capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(SERVER.read_text(encoding="utf-8"), encoding="utf-8")
    assert config_check.run() == 1
    out = capsys.readouterr().out
    assert "ZK_JWT_SECRET must be set to a long random value" in out

    filled = SERVER.read_text(encoding="utf-8").replace("<random-48-characters>", "x" * 48)
    filled = filled.replace("https://<app.your-domain.com>", "https://app.example.com")
    (tmp_path / ".env").write_text(filled, encoding="utf-8")
    assert config_check.run() == 1
    out = capsys.readouterr().out
    assert "still a template value" in out and "ZK_STRIPE_SECRET_KEY" in out and "NOT ready" in out
    assert "x" * 48 not in out and "sk_live" not in out  # names settings, never values


@pytest.mark.unit
def test_review_of_a_complete_production_configuration():
    s = Settings(_env_file=None, **PRODUCTION, email_provider="smtp", smtp_host="smtp.example.com", smtp_username="u",
                 smtp_password="secret-password", payment_provider="stripe", stripe_secret_key="sk_test_123",
                 stripe_webhook_secret="whsec_123", payment_flow_approved=True, payment_operating_countries=["GB"],
                 verification_provider="veriff", veriff_api_key="k", veriff_shared_secret="s", storage_provider="database",
                 redis_url="redis://cache:6379/0",
                 database_url="postgresql+asyncpg://app:pw@db.internal:5432/zoikorum", malware_scanner="clamav",
                 field_kms_key_name="projects/p/locations/l/keyRings/r/cryptoKeys/k", field_data_keys={"k1": "d3JhcHBlZA=="},
                 field_active_key="k1", migration_database_url="postgresql+asyncpg://owner:pw@db.internal:5432/zoikorum",
                 db_app_role="zoikorum_app")
    rows = config_check.review(s)
    assert not [r for r in rows if r[0] == config_check.MISSING]
    assert ("WARN", "Payments", "production is using a Stripe TEST key") in rows
    text = " ".join(" ".join(r) for r in rows)
    assert "secret-password" not in text and "smtp.example.com" not in text and "whsec_123" not in text


@pytest.mark.unit
def test_production_does_not_start_with_test_services_but_staging_may():
    with pytest.raises(RuntimeError) as refused:
        config_check.refuse_incomplete_production(Settings(_env_file=None, **PRODUCTION,
                                                           database_url=Settings.model_fields["database_url"].default))
    for area in ("Email", "Payments", "File storage", "Identity checks", "Database"):
        assert area in str(refused.value)
    config_check.refuse_incomplete_production(Settings(_env_file=None, **{**PRODUCTION, "env": "staging"}))


@pytest.mark.unit
def test_separate_staff_domain_needs_a_shared_passkey_domain():
    split = {**PRODUCTION, "frontend_url": "https://app.zoikorum.test", "staff_frontend_url": "https://staff.zoikorum.test"}
    rows = {area: status for status, area, _ in config_check.review(Settings(_env_file=None, **split))}
    assert rows["Passkeys"] == "MISSING"
    rows = {area: status for status, area, _ in config_check.review(Settings(_env_file=None, **split, webauthn_rp_id="zoikorum.test"))}
    assert rows["Passkeys"] == "OK"


@pytest.mark.unit
def test_development_providers_are_reported_missing_for_servers():
    rows = {area: status for status, area, _ in config_check.review(Settings(_env_file=None, **PRODUCTION))}
    assert rows["Email"] == rows["Payments"] == rows["File storage"] == rows["Identity checks"] == "MISSING"
