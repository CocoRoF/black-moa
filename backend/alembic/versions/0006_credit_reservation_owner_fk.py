"""credit_reservations.owner_id foreign key

Revision ID: 0006_credit_reservation_owner_fk
Revises: 0005_job_dedupe

``CreditReservation.owner_id`` is declared with ``owner_col()`` (users.id ON
DELETE CASCADE) but 0004 created the table with a plain column, so deleting an
account left its reservation rows behind forever: ``sweep_reservations`` only
trims terminal rows, and a leftover ``held`` row is never reclaimed. Bring the
deployed schema back in line with the model.
"""
from __future__ import annotations

from alembic import op

revision = "0006_credit_reservation_owner_fk"
down_revision = "0005_job_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM credit_reservations r
        WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = r.owner_id)
    """)
    op.execute("""
        ALTER TABLE credit_reservations
        DROP CONSTRAINT IF EXISTS fk_credit_reservations_owner_id_users
    """)
    op.create_foreign_key(
        "fk_credit_reservations_owner_id_users",
        "credit_reservations",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_credit_reservations_owner_id_users", "credit_reservations", type_="foreignkey")
