"""Reviews answer concrete questions instead of rating five scales (plan/40 §8).

The answers live in one JSONB column; the five area scores and the overall are derived
from them and kept in the existing columns — as reals now, since an area is the mean of
its questions and not a whole star.
"""
from __future__ import annotations

from alembic import op

revision = "0040_review_answers"
down_revision = "0039_unescape_company_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE company_reviews ADD COLUMN IF NOT EXISTS answers JSONB NOT NULL DEFAULT '{}'::jsonb")
    # Double, not real: an area is the mean of its questions (4.35), and a float32 would
    # hand 4.3499999 back to the page.
    for col in ("rating", "rating_pay", "rating_balance", "rating_culture", "rating_promotion", "rating_management"):
        op.execute(f"ALTER TABLE company_reviews ALTER COLUMN {col} TYPE DOUBLE PRECISION")
    op.execute("ALTER TABLE companies ALTER COLUMN rating TYPE DOUBLE PRECISION")
    op.execute("ALTER TABLE companies ALTER COLUMN popularity TYPE DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE company_reviews DROP COLUMN IF EXISTS answers")
