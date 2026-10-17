"""marketplace: Creative & Design category (starter list)

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-10-16 10:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from zoikorum.domains.marketplace.taxonomy_data import default_taxonomy_rows


revision = 'c7d8e9f0a1b2'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None

CATEGORY = 'creative-and-design'


def upgrade() -> None:
    """Reference data: design, video and writing work (stable uuid5 ids; existing rows untouched)."""
    nodes = sa.table(
        'taxonomy_nodes',
        *(sa.column(c) for c in ('id', 'slug', 'name', 'level', 'parent_id', 'category_slug', 'sort_order', 'requires_credential',
                                 'regulated', 'requires_insurance', 'deliverable_templates', 'credential_hints', 'status',
                                 'taxonomy_version')),
        schema='marketplace',
    )
    columns = set(nodes.c.keys())
    for row in default_taxonomy_rows():
        if row['category_slug'] != CATEGORY:
            continue
        values = {k: v for k, v in row.items() if k in columns}
        op.execute(postgresql.insert(nodes).values(**values).on_conflict_do_nothing(index_elements=['slug']))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM marketplace.taxonomy_nodes WHERE category_slug = :c AND level = 'SPECIALIZATION'").bindparams(c=CATEGORY))
    op.execute(sa.text("DELETE FROM marketplace.taxonomy_nodes WHERE category_slug = :c AND level = 'GROUP'").bindparams(c=CATEGORY))
    op.execute(sa.text("DELETE FROM marketplace.taxonomy_nodes WHERE category_slug = :c").bindparams(c=CATEGORY))
