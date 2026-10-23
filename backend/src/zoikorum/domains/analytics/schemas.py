"""Request bodies of the analytics domain."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClientEventIn(BaseModel):
    """One product-funnel event from the web app. The name must be on the allowlist and only a few short, non-personal
    properties are kept (service.clean_props); anything else is dropped, not stored."""

    name: str = Field(max_length=60)
    props: dict[str, str | int | bool | None] = Field(default_factory=dict)


class ClientEventsIn(BaseModel):
    """A batch of funnel events. ``sessionId`` is a random id the browser makes for one visit (never an account id);
    it is stored only as a one-way hash, so steps of one visit can be counted together."""

    sessionId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    events: list[ClientEventIn] = Field(min_length=1, max_length=25)
