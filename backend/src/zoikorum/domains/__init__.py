"""Bounded contexts. Each sub-package is one domain with this layout:

    models.py    SQLAlchemy tables in the domain's own Postgres schema (private)
    schemas.py   Pydantic request/response DTOs (private)
    service.py   commands + queries; aggregates enforce invariants here (private)
    api.py       FastAPI router ``router`` (HTTP surface)
    handlers.py  event subscriptions + timer handlers (private)
    facade.py    the ONLY module other domains may import (sync query API)

Cross-domain rule: ``zoikorum.domains.X`` may import ``zoikorum.domains.Y.facade``
and nothing else from Y. tests/test_architecture.py enforces it.
"""

DOMAINS = (
    "identity",
    "buyer",
    "firm",
    "professional",
    "marketplace",
    "search",
    "proposal",
    "contract",
    "escrow",
    "payments",
    "verification",
    "trust",
    "policy",
    "dispute",
    "audit",
    "messaging",
    "notification",
    "ai",
    "admin",
    "analytics",
    "review",
)
