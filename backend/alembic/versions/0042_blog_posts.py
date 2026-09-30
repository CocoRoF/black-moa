"""A person's own writing (plan/41 §4).

The blog is the middle of the house: a post is a page on the author's own address and, the
moment it is published, material their secretary can answer from.
"""
from __future__ import annotations

from alembic import op

revision = "0042_blog_posts"
down_revision = "0041_company_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS blog_posts (
        id UUID PRIMARY KEY,
        owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        slug VARCHAR(190) NOT NULL,
        title VARCHAR(200) NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        -- public: anybody. friends: accepted connections. private: the author.
        visibility VARCHAR(16) NOT NULL DEFAULT 'public',
        status VARCHAR(16) NOT NULL DEFAULT 'draft',
        published_at TIMESTAMPTZ,
        -- The knowledge document this post became, so editing one edits the other.
        knowledge_document_id UUID,
        view_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_blog_owner_slug UNIQUE (owner_id, slug)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_blog_posts_owner ON blog_posts (owner_id, status, published_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS blog_posts")
