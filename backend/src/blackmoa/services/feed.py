"""소식 — the one screen you open by reflex (plan/42).

Everything in it comes from somebody this person chose: connections, the people they
follow, and themselves, newest first. Nothing is ranked — choosing the person was the
ranking.

**The square is not in here.** It was, briefly, folded in at a ratio to keep a new
account's page from being empty. That made 소식 a second entrance to the community, and
the two rooms are entered for different reasons: the square is where you go for an answer,
소식 is where you come to see people you know. An empty page is answered with people to
follow, not with somebody else's writing (plan/42 §2).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.models import User
from blackmoa.services import blog as B

PAGE = 20
#: How many people to offer when there is nothing to read yet.
SUGGEST = 5


def _cursor(at: datetime | None) -> str:
    """Where to carry on from.

    Microseconds since the epoch rather than an ISO string — an ISO offset carries a `+`,
    which a URL turns into a space, and a cursor that silently parses back to nothing hands
    the reader the same page again.
    """
    return str(int(at.timestamp() * 1_000_000)) if at else ""


def _parse(cursor: str | None) -> datetime | None:
    raw = (cursor or "").strip()
    return datetime.fromtimestamp(int(raw) / 1_000_000, tz=UTC) if raw.isdigit() else None


def _item(post, author: User, why: str, liked: bool, *, full: bool = False, ids: bool = False) -> dict[str, Any]:
    # 집에서는 어디서나 그 사람이 스스로 고른 이름으로 부른다. 인맥·메신저·프로필이 모두
    # 그렇게 부르는데 소식만 계정의 본명을 찍고 있었다. 한 사람이 화면마다 다른 이름이면
    # 읽는 사람에게는 두 사람이다.
    from blackmoa.services.people import display_of
    # A card is a card. The whole post — a long article's body, the upload ids editing it
    # takes — comes from `one()` when the window opens, so a page of twenty cards is not a
    # page of twenty documents.
    return {"id": str(post.id), "why": why,
            "author": {"id": str(author.id), "name": display_of(author),
                       "handle": author.mail_handle or "", "avatar_url": author.avatar_url},
            "liked": liked, "at": post.published_at.isoformat() if post.published_at else None,
            "can_edit": why == "mine",
            **B.out(post, full=full, ids=ids)}


async def one(db: AsyncSession, me: User, post_id: uuid.UUID) -> dict[str, Any]:
    """A single post in the same shape as a card in 소식 (plan/42 §12).

    A post is read in the same window wherever it was pressed: 소식, my own blog, somebody's
    page. That is one component, so it is one shape, and it comes from one place rather than
    being assembled differently by each screen.
    """
    post = await B.readable(db, me, post_id)
    author = await db.get(User, post.owner_id)
    if author is None:
        from blackmoa.core.errors import NotFound
        raise NotFound("post not found", code="post_not_found")
    mine = post.owner_id == me.id
    why = "mine"
    if not mine:
        friend_ids, _followed = await B.reading_list(db, me)
        why = "friend" if post.owner_id in friend_ids else "following"
    liked = post.id in await B.liked_ids(db, me, [post.id])
    # Whole, always: this window is where the post is read. The upload ids are the one part
    # that is the author's business alone.
    return _item(post, author, why, liked, full=True, ids=mine)


async def page(db: AsyncSession, me: User, *, cursor: str | None = None, limit: int = PAGE) -> dict[str, Any]:
    """One screen of 소식, and where to carry on from."""
    before = _parse(cursor)
    posts = await B.feed(db, me, limit=limit, before=before)
    liked = await B.liked_ids(db, me, [p.id for p, _ in posts])
    friend_ids, followed = await B.reading_list(db, me)

    def why(owner_id: uuid.UUID) -> str:
        if owner_id == me.id:
            return "mine"
        return "friend" if owner_id in friend_ids else "following"

    items = [_item(p, u, why(p.owner_id), p.id in liked) for p, u in posts]

    # Nothing to read means nobody chosen yet, so the page offers people rather than
    # filling itself with writing from strangers.
    people: list[dict[str, Any]] = []
    if not items and before is None:
        from blackmoa.services import people as P
        people = (await P.suggestions(db, me, limit=SUGGEST))[:SUGGEST]

    last = posts[-1][0].published_at if posts else None
    return {"items": items, "cursor": _cursor(last) if len(posts) >= limit else None,
            "suggestions": people,
            "sources": {"friends": bool(friend_ids - {me.id}), "following": bool(followed)}}
