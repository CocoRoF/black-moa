"""The album becomes posts (plan/42 §9).

A photo somebody put in their album and a photo they put in a post were the same act with
two sets of rules: one had a caption but no address, no visibility of its own and nowhere
to reply. Every album photo is carried over as a post of its own — the caption becomes the
body, the album's visibility becomes the post's, and the day it was added becomes the day
it was published. Nothing is dropped.

Revision ID: 0048_album_into_posts
Revises: 0047_post_images
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0048_album_into_posts"
down_revision = "0047_post_images"
branch_labels = None
depends_on = None

_KEEP = re.compile(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ\s-]+")


def _slug(text: str) -> str:
    s = _KEEP.sub("", (text or "").strip().lower())
    s = re.sub(r"[\s-]+", "-", s).strip("-")[:80]
    return s or uuid.uuid4().hex[:8]


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT owner_id, data, visibility FROM owner_profiles "
        "WHERE data ? 'photos' AND jsonb_array_length(data->'photos') > 0")).mappings().all()
    for row in rows:
        data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"] or "{}")
        vis = row["visibility"] if isinstance(row["visibility"], dict) else json.loads(row["visibility"] or "{}")
        # An album was public or it was not. A post says the same thing with its own word.
        level = "public" if (vis.get("photos") or "private") == "public" else "private"
        taken = {s for (s,) in conn.execute(sa.text("SELECT slug FROM blog_posts WHERE owner_id = :o"),
                                            {"o": row["owner_id"]}).all()}
        for photo in data.get("photos") or []:
            upload_id = str(photo.get("id") or "").strip()
            if not upload_id:
                continue
            caption = (photo.get("caption") or "").strip()
            try:
                at = datetime.fromisoformat(str(photo.get("at"))) if photo.get("at") else datetime.now(UTC)
            except ValueError:
                at = datetime.now(UTC)
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            title = (caption[:60] or at.strftime("%Y-%m-%d")).strip()
            base = _slug(title)
            slug, n = base, 2
            while slug in taken:
                slug, n = f"{base}-{n}", n + 1
            taken.add(slug)
            conn.execute(sa.text("""
                INSERT INTO blog_posts (id, owner_id, slug, title, body, visibility, status, kind,
                                        published_at, images, view_count, like_count, comment_count,
                                        created_at, updated_at)
                VALUES (:id, :owner, :slug, :title, :body, :vis, 'published', 'note',
                        :at, CAST(:images AS jsonb), 0, 0, 0, :at, :at)
            """), {"id": str(uuid.uuid4()), "owner": row["owner_id"], "slug": slug, "title": title,
                   "body": caption, "vis": level, "at": at, "images": json.dumps([upload_id])})
    # Including the ones that held an empty album: `photos` is not a profile field any more,
    # and a key left behind is a field the next reader will wonder about.
    conn.execute(sa.text("UPDATE owner_profiles SET data = data - 'photos', "
                         "visibility = visibility - 'photos' WHERE data ? 'photos' OR visibility ? 'photos'"))


def downgrade() -> None:
    """One way. The posts stand on their own now and an album cannot hold their replies."""
