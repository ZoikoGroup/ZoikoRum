from __future__ import annotations

from pydantic import BaseModel, Field


class SpecializationIn(BaseModel):
    groupSlug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=2, max_length=200)
    requiresCredential: bool = False
    regulated: bool = False
    deliverableTemplates: list[str] = Field(default_factory=list, max_length=12)
    credentialHints: list[str] = Field(default_factory=list, max_length=20)


class SpecializationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    requiresCredential: bool | None = None
    regulated: bool | None = None
    deliverableTemplates: list[str] | None = Field(default=None, max_length=12)
    credentialHints: list[str] | None = Field(default=None, max_length=20)


class SpecializationAdminOut(BaseModel):
    slug: str
    name: str
    groupSlug: str
    categorySlug: str
    requiresCredential: bool
    regulated: bool
    deliverableTemplates: list[str]
    credentialHints: list[str]
    status: str
    taxonomyVersion: int
