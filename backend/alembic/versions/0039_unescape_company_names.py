"""Undo XML entities left in company names by the DART code dictionary (plan/40).

The dictionary is XML read with a regex, and "삼성E&amp;A" was written as the company's
name. The parser now unescapes; this repairs the 29 listed companies (and any unlisted
ones) already written that way, in the name and in the matching key alike.
"""
from __future__ import annotations

from alembic import op

revision = "0039_unescape_company_names"
down_revision = "0038_company_reviews"
branch_labels = None
depends_on = None

_PAIRS = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'"), ("&apos;", "'"))


def upgrade() -> None:
    for col in ("name", "name_norm"):
        expr = col
        for ent, ch in _PAIRS:
            expr = f"replace({expr}, '{ent}', '{ch.replace(chr(39), chr(39) * 2)}')"
        op.execute(f"UPDATE companies SET {col} = {expr} WHERE {col} LIKE '%&%;%'")


def downgrade() -> None:
    pass
