"""Relationship engine and persona versions (plan/37)."""
from __future__ import annotations

from alembic import op

revision = "0033_relationship"
down_revision = "0032_drop_places"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_relationships (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        stage VARCHAR(16) NOT NULL DEFAULT 'new',
        score DOUBLE PRECISION NOT NULL DEFAULT 0,
        started_at TIMESTAMPTZ,
        last_turn_at TIMESTAMPTZ,
        turns INTEGER NOT NULL DEFAULT 0,
        active_days INTEGER NOT NULL DEFAULT 0,
        last_active_day DATE,
        streak_days INTEGER NOT NULL DEFAULT 0,
        facts_remembered INTEGER NOT NULL DEFAULT 0,
        stage_changed_at TIMESTAMPTZ,
        milestones JSONB NOT NULL DEFAULT '[]'::jsonb,
        mood JSONB NOT NULL DEFAULT '{}'::jsonb,
        proactive_day DATE,
        proactive_count INTEGER NOT NULL DEFAULT 0,
        last_proactive_at TIMESTAMPTZ,
        last_proactive_kind VARCHAR(24) NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_agent_relationships_user_agent UNIQUE (user_id, agent_id)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_relationships_user_id ON agent_relationships (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_relationships_agent_id ON agent_relationships (agent_id)")
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_persona_versions (
        id UUID PRIMARY KEY,
        agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label VARCHAR(80) NOT NULL DEFAULT '',
        snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_persona_versions_agent_id ON agent_persona_versions (agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_persona_versions_owner_id ON agent_persona_versions (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_persona_versions_created_at ON agent_persona_versions (created_at)")
    # Every owner who has already talked with a secretary starts with the history they have,
    # not from zero: the counters are rebuilt from completed owner turns.
    op.execute("""
    INSERT INTO agent_relationships (id, user_id, agent_id, stage, started_at, last_turn_at, turns, active_days, last_active_day)
    SELECT gen_random_uuid(), t.owner_id, t.agent_id, 'new', min(t.started_at), max(t.started_at), count(*),
           count(DISTINCT (t.started_at AT TIME ZONE 'Asia/Seoul')::date), max((t.started_at AT TIME ZONE 'Asia/Seoul')::date)
    FROM turns t JOIN conversations c ON c.id = t.conversation_id
    WHERE t.audience = 'owner' AND t.status = 'completed' AND c.simulated = false
    GROUP BY t.owner_id, t.agent_id
    ON CONFLICT (user_id, agent_id) DO NOTHING""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_persona_versions")
    op.execute("DROP TABLE IF EXISTS agent_relationships")
