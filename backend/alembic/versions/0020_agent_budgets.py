"""Usage caps move from the plan to the secretary (plan/34).

A plan says what an account *is* — how many secretaries, how much knowledge, which models,
and what it is granted each month. How hard a particular secretary may be worked is its
owner's business, so the per-turn, per-day and visitor caps live on the agent, where the
owner can see them next to the thing they limit. 0 means no limit; the credit balance is
the limit that always applies.

The network node ceiling goes entirely: connections are people now, not rows an owner
types, and a cap on them limits nothing but the product.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_agent_budgets"
down_revision = "0019_plan_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("turn_cost_cap_credits", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("agents", sa.Column("daily_credit_cap", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agents", sa.Column("monthly_credit_cap", sa.Integer(), nullable=False, server_default="0"))
    # Carry the cap each secretary is running under today, so nothing changes mid-flight
    # for an install that is already serving turns.
    op.execute("""
        UPDATE agents a SET turn_cost_cap_credits = GREATEST(1, COALESCE(p.turn_cost_cap_credits, 50))
        FROM users u LEFT JOIN plans p ON p.id = u.plan_id
        WHERE u.id = a.owner_id
    """)
    for col in ("max_network_nodes", "turn_cost_cap_credits", "daily_credit_cap", "visitor_turns_per_day"):
        op.drop_column("plans", col)


def downgrade() -> None:
    op.add_column("plans", sa.Column("max_network_nodes", sa.Integer(), nullable=False, server_default="300"))
    op.add_column("plans", sa.Column("turn_cost_cap_credits", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("plans", sa.Column("daily_credit_cap", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("plans", sa.Column("visitor_turns_per_day", sa.Integer(), nullable=False, server_default="200"))
    for col in ("monthly_credit_cap", "daily_credit_cap", "turn_cost_cap_credits"):
        op.drop_column("agents", col)
