"""An unfinished federation adapter must not mint a fabricated identity."""
import pytest
from zoikorum.domains.identity.sso import handle_saml_assertion, sync_scim_user
from zoikorum.shared.errors import ServiceUnavailable

@pytest.mark.unit
async def test_unvalidated_saml_assertion_cannot_authenticate():
    with pytest.raises(ServiceUnavailable) as error:
        await handle_saml_assertion('<Assertion><NameID>admin@example.com</NameID></Assertion>')
    assert error.value.code == 'SSO_NOT_CONFIGURED'

@pytest.mark.unit
async def test_scim_never_reports_success_without_provisioning():
    with pytest.raises(ServiceUnavailable) as error:
        await sync_scim_user('DEPROVISION', 'user@example.com', {})
    assert error.value.code == 'SCIM_NOT_CONFIGURED'
