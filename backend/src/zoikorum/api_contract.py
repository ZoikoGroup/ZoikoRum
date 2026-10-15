"""The API contract the web app is checked against: every response and request model with its field names.

`python -m zoikorum.cli api-contract` writes it to frontend/src/api/contract.json. A backend test fails when the
file is out of date, and a frontend test fails when a TypeScript type reads a field the backend does not send.
"""

from __future__ import annotations

import json


def build() -> dict[str, list[str]]:
    from zoikorum.main import app

    schemas = app.openapi().get("components", {}).get("schemas", {})
    return {name: sorted((schema.get("properties") or {}).keys()) for name, schema in sorted(schemas.items())
            if schema.get("type") == "object" and schema.get("properties")}


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=True) + "\n"
