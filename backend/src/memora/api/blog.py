"""A person's own writing (plan/41 §4): the author's side."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from memora.core.deps import DB, CurrentUser
from memora.core.ratelimit import limiter
from memora.models import BlogPost
from memora.services import blog as B
from memora.services import people as P

router = APIRouter(prefix="/api/blog", tags=["blog"])
feed_router = APIRouter(prefix="/api/feed", tags=["feed"])

# ── how fast a person can be (plan/42 §14) ───────────────────────────
#
# Not a courtesy limit: a ceiling nothing human reaches. Nobody writes six posts in a
# minute; somebody reading a thread really can leave a reply every three seconds, and
# tapping hearts down a feed is faster still. The three budgets are separate because they
# cost different things and abusing them looks different.
POSTS_PER_MIN = 6
POSTS_PER_HOUR = 60
COMMENTS_PER_MIN = 20
COMMENTS_PER_HOUR = 300
TAPS_PER_MIN = 60


def _budget(user, what: str, limit: int, per: int) -> None:
    limiter.check(f"house:{what}:{user.id}", limit, per)


@feed_router.get("")
async def read_feed(user: CurrentUser, db: DB, cursor: str | None = None, limit: int = 20):
    """One screen of 소식: the people I chose, with the square folded in (plan/42 §2)."""
    from memora.services import feed as F

    return await F.page(db, user, cursor=cursor, limit=max(1, min(limit, 50)))


@feed_router.get("/posts/{post_id}")
async def read_one(post_id: uuid.UUID, user: CurrentUser, db: DB):
    """One post in the shape a card in 소식 has, wherever it was pressed (plan/42 §12)."""
    from memora.services import feed as F

    return await F.one(db, user, post_id)


@router.get("")
async def list_mine(user: CurrentUser, db: DB, page: int = 1, limit: int = 10):
    """My own writing, drafts included, in the shape 소식 draws.

    My blog and 소식 show the same thing, so they are the same card. Two things differ: a
    draft is on this list and only I can see it, and this shelf turns pages rather than
    running on forever, because I come here to find something I wrote.
    """
    per = max(1, min(limit, 30))
    page = max(1, page)
    posts, total = await B.page_of_mine(db, user, page=page, per=per)
    me = {"id": str(user.id), "name": P.display_of(user),
          "handle": user.mail_handle or "", "avatar_url": user.avatar_url}
    liked = await B.liked_ids(db, user, [p.id for p in posts])
    return {"items": [{**B.out(p), "author": me, "why": "mine", "can_edit": True,
                       "liked": p.id in liked,
                       "at": p.published_at.isoformat() if p.published_at else None}
                      for p in posts],
            "page": page, "pages": max(1, -(-total // per)), "total": total}


class PostIn(BaseModel):
    #: A note takes its heading from its own first line, so the box at the top of 소식
    #: never has to ask for one (plan/42 §4).
    title: str = Field(default="", max_length=B.MAX_TITLE)
    body: str = Field(max_length=B.MAX_BODY)
    visibility: str = "public"
    publish: bool = True
    kind: str = "article"
    images: list[str] = Field(default_factory=list, max_length=B.MAX_IMAGES)
    #: Who the picker chose. A mention points at a person, so somebody with no address of
    #: their own can still be named (plan/42 §11).
    mentions: list[str] = Field(default_factory=list, max_length=20)


@router.post("", status_code=201)
async def create(body: PostIn, user: CurrentUser, db: DB):
    _budget(user, "post", POSTS_PER_MIN, 60)
    _budget(user, "post-hr", POSTS_PER_HOUR, 3600)
    post = await B.create(db, user, title=body.title, body=body.body, visibility=body.visibility,
                          publish=body.publish, kind=body.kind, images=body.images, mentions=body.mentions)
    await db.commit()
    return B.out(post, full=True)


@router.get("/{post_id}")
async def read(post_id: uuid.UUID, user: CurrentUser, db: DB):
    return B.out(await B.get_owned(db, user, post_id), full=True)


class PostPatch(BaseModel):
    title: str | None = Field(default=None, max_length=B.MAX_TITLE)
    body: str | None = Field(default=None, max_length=B.MAX_BODY)
    visibility: str | None = None
    status: str | None = None
    images: list[str] | None = Field(default=None, max_length=B.MAX_IMAGES)
    mentions: list[str] | None = Field(default=None, max_length=20)


@router.patch("/{post_id}")
async def update(post_id: uuid.UUID, body: PostPatch, user: CurrentUser, db: DB):
    _budget(user, "post", POSTS_PER_MIN, 60)
    post = await B.update(db, user, post_id, title=body.title, body=body.body,
                          visibility=body.visibility, status=body.status, images=body.images, mentions=body.mentions)
    await db.commit()
    return B.out(post, full=True)


@router.delete("/{post_id}")
async def remove(post_id: uuid.UUID, user: CurrentUser, db: DB):
    await B.remove(db, user, post_id)
    await db.commit()
    return {"ok": True}


# ── what readers do with a post (plan/42 §5) ─────────────────────────


class LikeIn(BaseModel):
    on: bool = True


@router.post("/{post_id}/like")
async def like(post_id: uuid.UUID, body: LikeIn, user: CurrentUser, db: DB):
    _budget(user, "tap", TAPS_PER_MIN, 60)
    out = await B.like(db, user, post_id, on=body.on)
    await db.commit()
    return out


class CommentIn(BaseModel):
    body: str = Field(max_length=B.MAX_COMMENT)
    #: The comment this answers. A reply to a reply joins that thread (plan/42 §5).
    parent_id: uuid.UUID | None = None


def _comment_out(c, author, bot=None, *, viewer=None, post_owner_id=None) -> dict:
    """Signed by whoever wrote it. A secretary's answer is the secretary's (plan/43 §6).

    Whether this reader may remove it is said here rather than guessed from the byline: a
    secretary's comment is signed by the secretary and deleted by its owner, so the two are
    not the same question.
    """
    who = ({"id": str(bot.id), "name": bot.name, "handle": "", "avatar_url": bot.avatar_url, "agent": True}
           if bot is not None
           else {"id": str(author.id), "name": P.display_of(author),
                 "handle": author.mail_handle or "", "avatar_url": author.avatar_url})
    mine = viewer is not None and (c.author_id == viewer.id or post_owner_id == viewer.id)
    return {"id": str(c.id), "body": c.body, "created_at": c.created_at.isoformat(),
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "author": who, "can_delete": bool(mine)}


@router.get("/{post_id}/comments")
async def list_comments(post_id: uuid.UUID, user: CurrentUser, db: DB, limit: int = 200):
    rows = await B.comments(db, user, post_id, limit=max(1, min(limit, 200)))
    post = await db.get(BlogPost, post_id)
    return {"items": [_comment_out(c, u, bot, viewer=user, post_owner_id=post.owner_id if post else None)
                      for c, u, bot in rows]}


@router.post("/{post_id}/comments", status_code=201)
async def add_comment(post_id: uuid.UUID, body: CommentIn, user: CurrentUser, db: DB):
    _budget(user, "comment", COMMENTS_PER_MIN, 60)
    _budget(user, "comment-hr", COMMENTS_PER_HOUR, 3600)
    row = await B.comment(db, user, post_id, body=body.body, parent_id=body.parent_id)
    await db.commit()
    return _comment_out(row, user, viewer=user)


@router.delete("/{post_id}/comments/{comment_id}")
async def drop_comment(post_id: uuid.UUID, comment_id: uuid.UUID, user: CurrentUser, db: DB):
    gone = await B.remove_comment(db, user, comment_id)
    await db.commit()
    return {"ok": True, "removed": gone}
