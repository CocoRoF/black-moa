"""Fill profiles from the names their accounts already had

Signup asks for a real name, a nickname and an email, but only the account row kept them —
the profile stayed empty, so the page that shows "what your secretary introduces you as"
opened blank and asked for all of it a second time. New accounts are seeded at signup; this
catches the ones created before that.

Only blank fields are filled, so an account that has since written its own profile is left
exactly as it is.

Revision ID: 0013_seed_profile_names
Revises: 0012_mail_handle
"""
from __future__ import annotations

from alembic import op

revision = "0013_seed_profile_names"
down_revision = "0012_mail_handle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Accounts that never had a profile row at all.
    op.execute("""
        INSERT INTO owner_profiles (owner_id, data, visibility, updated_at)
        SELECT u.id,
               jsonb_build_object(
                   'full_name', u.display_name,
                   'preferred_name', COALESCE(NULLIF(u.nickname, ''), u.display_name),
                   'contact', jsonb_build_object('email', u.email)
               ),
               '{}'::jsonb, now()
        FROM users u
        LEFT JOIN owner_profiles p ON p.owner_id = u.id
        WHERE p.owner_id IS NULL
    """)
    # Existing profiles: fill only what is missing.
    op.execute("""
        UPDATE owner_profiles p
        SET data = p.data
                 || CASE WHEN COALESCE(NULLIF(p.data ->> 'full_name', ''), '') = ''
                         THEN jsonb_build_object('full_name', u.display_name) ELSE '{}'::jsonb END
                 || CASE WHEN COALESCE(NULLIF(p.data ->> 'preferred_name', ''), '') = ''
                         THEN jsonb_build_object('preferred_name', COALESCE(NULLIF(u.nickname, ''), u.display_name))
                         ELSE '{}'::jsonb END
                 || CASE WHEN COALESCE(NULLIF(p.data -> 'contact' ->> 'email', ''), '') = ''
                         THEN jsonb_build_object('contact',
                                COALESCE(p.data -> 'contact', '{}'::jsonb) || jsonb_build_object('email', u.email))
                         ELSE '{}'::jsonb END,
            updated_at = now()
        FROM users u
        WHERE u.id = p.owner_id
          AND (COALESCE(NULLIF(p.data ->> 'full_name', ''), '') = ''
               OR COALESCE(NULLIF(p.data ->> 'preferred_name', ''), '') = ''
               OR COALESCE(NULLIF(p.data -> 'contact' ->> 'email', ''), '') = '')
    """)


def downgrade() -> None:
    """Nothing to undo: this only filled blanks, and which ones were blank is not recorded."""
