"""Regressions for combining partial acceptance with deferred policy releases."""
import pytest
from zoikorum.domains.escrow.service import _accepted_gross
from zoikorum.shared.errors import Conflict

@pytest.mark.parametrize("accepted,funded,expected", [(None, 10000, 10000), (6000, 10000, 6000), (10000, 10000, 10000)])
def test_release_uses_persisted_acceptance(accepted, funded, expected):
    assert _accepted_gross(accepted, funded) == expected

@pytest.mark.parametrize("accepted", [0, -1, 10001])
def test_invalid_acceptance_cannot_release_funds(accepted):
    with pytest.raises(Conflict):
        _accepted_gross(accepted, 10000)
