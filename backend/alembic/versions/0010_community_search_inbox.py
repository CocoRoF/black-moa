"""Community search vector + board write policy, and inbox items without an agent

Community notifications belong in the inbox, but they have no secretary — inbox_items.agent_id
was NOT NULL, which is why they could not go there.

Revision ID: 0010_community_search_inbox
Revises: 0009_community
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_community_search_inbox"
down_revision = "0009_community"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("inbox_items", "agent_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("community_boards", sa.Column("write_policy", sa.String(24), nullable=False, server_default="all"))

    # Search: the same three legs the knowledge base uses — a Korean query has to survive
    # a tokenizer that does not know Korean, so trigram similarity carries what tsvector drops.
    op.execute("ALTER TABLE community_posts ADD COLUMN search tsvector")
    op.execute("""
        CREATE OR REPLACE FUNCTION community_posts_search_update() RETURNS trigger AS $$
        BEGIN
          NEW.search := setweight(to_tsvector('simple', coalesce(NEW.title, '')), 'A')
                     || setweight(to_tsvector('simple', coalesce(NEW.body, '')), 'B');
          RETURN NEW;
        END $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER community_posts_search_trg BEFORE INSERT OR UPDATE OF title, body
        ON community_posts FOR EACH ROW EXECUTE FUNCTION community_posts_search_update()
    """)
    op.execute("UPDATE community_posts SET title = title")   # fire the trigger for existing rows
    op.execute("CREATE INDEX ix_community_posts_search ON community_posts USING gin(search)")
    op.execute("CREATE INDEX ix_community_posts_title_trgm ON community_posts USING gin(title gin_trgm_ops)")
    op.execute("CREATE INDEX ix_community_posts_body_trgm ON community_posts USING gin(body gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_community_posts_body_trgm")
    op.execute("DROP INDEX IF EXISTS ix_community_posts_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_community_posts_search")
    op.execute("DROP TRIGGER IF EXISTS community_posts_search_trg ON community_posts")
    op.execute("DROP FUNCTION IF EXISTS community_posts_search_update()")
    op.execute("ALTER TABLE community_posts DROP COLUMN IF EXISTS search")
    op.drop_column("community_boards", "write_policy")
    op.alter_column("inbox_items", "agent_id", existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)
