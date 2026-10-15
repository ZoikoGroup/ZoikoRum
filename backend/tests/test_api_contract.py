"""The web app's contract test reads frontend/src/api/contract.json; it must match the API as it is now."""

from __future__ import annotations

from pathlib import Path

from zoikorum.api_contract import render

CONTRACT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "contract.json"


def test_the_frontend_contract_file_is_current():
    assert CONTRACT.exists(), "run: python -m zoikorum.cli api-contract"
    assert CONTRACT.read_text(encoding="utf-8") == render(), (
        "The API models changed. Run `python -m zoikorum.cli api-contract` (from backend/) and commit "
        "frontend/src/api/contract.json; the frontend contract test then checks the TypeScript types against it.")
