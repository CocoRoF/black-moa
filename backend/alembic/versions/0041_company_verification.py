"""Company verification by work email (plan/40 §10).

A company's email domain comes from the exchange's homepage where we have one, from an
administrator, or from members who verified an address at that domain and said which
company it is. A verification is one person proving one mailbox; the company they pick is
constrained to the companies known at that domain, or becomes a proposal.
"""
from __future__ import annotations

from alembic import op

revision = "0041_company_verification"
down_revision = "0040_review_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS company_domains (
        id UUID PRIMARY KEY,
        domain VARCHAR(190) NOT NULL,
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        source VARCHAR(16) NOT NULL DEFAULT 'homepage',
        status VARCHAR(16) NOT NULL DEFAULT 'confirmed',
        claims INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_company_domain UNIQUE (domain, company_id)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_domains_domain ON company_domains (domain)")
    op.execute("""
    CREATE TABLE IF NOT EXISTS company_verifications (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
        domain VARCHAR(190) NOT NULL,
        email_masked VARCHAR(190) NOT NULL DEFAULT '',
        email_hash VARCHAR(64) NOT NULL,
        code_hash VARCHAR(64) NOT NULL,
        code_expires_at TIMESTAMPTZ NOT NULL,
        code_verified_at TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_verifications_user ON company_verifications (user_id, status)")
    # One mailbox proves one account: a second account cannot verify with the same address.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_company_verification_email ON company_verifications (email_hash) WHERE status = 'verified'")
    op.execute("ALTER TABLE company_reviews ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE company_reviews DROP COLUMN IF EXISTS verified")
    op.execute("DROP TABLE IF EXISTS company_verifications")
    op.execute("DROP TABLE IF EXISTS company_domains")
