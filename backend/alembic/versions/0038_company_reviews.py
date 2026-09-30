"""Company reviews, follows, views and the numbers derived from them (plan/40).

One review row carries everything a person can say about an employer — the five ratings,
the pros and cons, and optionally what they were paid, how the interview went and which
benefits they had — so 연봉·면접·복지 are views over one table rather than three forms.
The companies row keeps the derived numbers (rating, counts, popularity, a stats blob) so
the directory can be sorted and the dashboard read without touching the reviews at all.
"""
from __future__ import annotations

from alembic import op

revision = "0038_company_reviews"
down_revision = "0037_relay_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS company_reviews (
        id UUID PRIMARY KEY,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        author_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status VARCHAR(16) NOT NULL DEFAULT 'published',
        employment VARCHAR(16) NOT NULL DEFAULT 'current',
        job_code VARCHAR(32) NOT NULL DEFAULT '',
        work_year INTEGER NOT NULL,
        title VARCHAR(120) NOT NULL DEFAULT '',
        pros TEXT NOT NULL DEFAULT '',
        cons TEXT NOT NULL DEFAULT '',
        advice TEXT NOT NULL DEFAULT '',
        rating REAL NOT NULL,
        rating_pay INTEGER NOT NULL,
        rating_balance INTEGER NOT NULL,
        rating_culture INTEGER NOT NULL,
        rating_promotion INTEGER NOT NULL,
        rating_management INTEGER NOT NULL,
        recommend BOOLEAN NOT NULL DEFAULT true,
        ceo_approval BOOLEAN,
        growth VARCHAR(8) NOT NULL DEFAULT 'flat',
        salary INTEGER,
        experience_years INTEGER,
        interview JSONB NOT NULL DEFAULT '{}'::jsonb,
        benefits JSONB NOT NULL DEFAULT '[]'::jsonb,
        topics JSONB NOT NULL DEFAULT '[]'::jsonb,
        helpful_count INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_company_review_author UNIQUE (company_id, author_id)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_reviews_company ON company_reviews (company_id, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_reviews_author_id ON company_reviews (author_id)")

    op.execute("""
    CREATE TABLE IF NOT EXISTS company_follows (
        id UUID PRIMARY KEY,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_company_follow UNIQUE (company_id, user_id)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_follows_user_id ON company_follows (user_id)")

    op.execute("""
    CREATE TABLE IF NOT EXISTS company_views (
        id UUID PRIMARY KEY,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        viewer_key VARCHAR(64) NOT NULL,
        day VARCHAR(10) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_company_view UNIQUE (company_id, viewer_key, day)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_views_company ON company_views (company_id, created_at)")

    for col, ddl in (
        ("review_count", "INTEGER NOT NULL DEFAULT 0"),
        ("rating", "REAL NOT NULL DEFAULT 0"),
        ("follow_count", "INTEGER NOT NULL DEFAULT 0"),
        ("view_count", "INTEGER NOT NULL DEFAULT 0"),
        ("views_7d", "INTEGER NOT NULL DEFAULT 0"),
        ("open_jobs", "INTEGER NOT NULL DEFAULT 0"),
        ("popularity", "REAL NOT NULL DEFAULT 0"),
        ("stats", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ("tags", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ):
        op.execute(f"ALTER TABLE companies ADD COLUMN IF NOT EXISTS {col} {ddl}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_companies_popularity ON companies (popularity DESC) WHERE hidden = false")
    # A first ranking, so the dashboard has an order before the worker's first pass: the
    # exchange tier and a homepage are the only signals a fresh directory has.
    op.execute("""
    UPDATE companies SET popularity =
        CASE market WHEN '유가' THEN 1.0 WHEN '코스닥' THEN 0.6 WHEN '코넥스' THEN 0.3 ELSE 0 END
        + CASE WHEN homepage <> '' THEN 0.2 ELSE 0 END
        + ln(1 + COALESCE(employees, 0)) / 4.0
    WHERE popularity = 0 AND (market <> '' OR industry_text <> '' OR address <> '' OR biz_no IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_views")
    op.execute("DROP TABLE IF EXISTS company_follows")
    op.execute("DROP TABLE IF EXISTS company_reviews")
    for col in ("review_count", "rating", "follow_count", "view_count", "views_7d", "open_jobs",
                "popularity", "stats", "tags"):
        op.execute(f"ALTER TABLE companies DROP COLUMN IF EXISTS {col}")
