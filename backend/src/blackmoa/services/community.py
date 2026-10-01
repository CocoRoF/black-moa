"""Community service — the only door to the community_* tables.

Everything that could be raced by two pods is written as one statement: counters are
`SET c = c + 1`, likes are a unique insert whose row count decides the delta, and a view is
a deduplicating insert that increments only when it actually inserted. Nothing here does
read-modify-write on a shared number.
"""
from __future__ import annotations

import contextlib
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from blackmoa.data.jobs_taxonomy import INDUSTRY_INDEX, INDUSTRY_PARENT, JOB_INDEX, JOB_PARENT
from blackmoa.data.regions import REGION_INDEX, REGION_NAME, REGION_PARENT
from blackmoa.models import (
    CommunityBoard,
    CommunityComment,
    CommunityJob,
    CommunityPost,
    CommunityPostView,
    CommunityReaction,
    CommunityReport,
    User,
)
from blackmoa.services import profile as PF
from blackmoa.services import settings as S

MAX_TITLE = 200
MAX_BODY = 20_000
MAX_COMMENT = 5_000
POSTS_PER_HOUR = 10
COMMENTS_PER_HOUR = 60

# `icon` names a lucide glyph, not an emoji. Emoji render as a different typeface on every
# platform and sit badly next to the rail's line icons — a board list is chrome, not content.
DEFAULT_BOARDS = [
    ("worklife", "회사생활", "상사, 동료, 사내 정치. 어디에도 못 하는 이야기", "discussion", "briefcase", 10),
    ("career", "이직·커리어", "이직 고민, 연봉 협상, 커리어 전환", "discussion", "trending-up", 20),
    ("interview", "서류·면접", "이력서, 포트폴리오, 면접 후기", "discussion", "file-text", 30),
    ("dating", "연애", "직장인의 연애와 결혼", "discussion", "heart", 40),
    ("money", "재테크", "월급, 투자, 내집 마련", "discussion", "piggy-bank", 50),
    ("free", "자유주제", "무엇이든", "discussion", "message-circle", 60),
    ("jobs", "채용공고", "지금 열려 있는 자리", "jobs", "megaphone", 70),
]


async def migrate_board_icons(db: AsyncSession) -> int:
    """One-time: the seeded emoji become glyph names. Only touches boards still holding the
    emoji they were seeded with, so an operator's own choice is left alone."""
    emoji = {"worklife": "briefcase", "career": "trending-up", "interview": "file-text",
             "dating": "heart", "money": "piggy-bank", "free": "message-circle", "jobs": "megaphone"}
    n = 0
    for b in (await db.execute(select(CommunityBoard))).scalars().all():
        if b.icon and not b.icon.isascii() and b.slug in emoji:
            b.icon = emoji[b.slug]
            n += 1
    return n


async def seed_boards(db: AsyncSession) -> int:
    have = {b.slug for b in (await db.execute(select(CommunityBoard))).scalars()}
    added = 0
    for slug, name, desc, kind, icon, order in DEFAULT_BOARDS:
        if slug in have:
            continue
        db.add(CommunityBoard(slug=slug, name=name, description=desc, kind=kind, icon=icon, sort_order=order))
        added += 1
    return added


# ── identity ────────────────────────────────────────────────────────
@dataclass
class Author:
    id: str
    name: str
    job: str
    avatar_url: str | None
    is_me: bool
    #: 이 사람이 지금 광장에서 쓰는 이름 (plan/52). 화면에 서는 것은 늘 이것이다.
    #: 글에 적힌 이름(`meta.author_name`)은 쓴 그때의 기록일 뿐이다.
    square: str = ""


async def authors_for(db: AsyncSession, user_ids: set[uuid.UUID], *, me: uuid.UUID | None) -> dict[uuid.UUID, Author]:
    """Identity is read, never stored on the row: fixing your job title fixes it everywhere.

    What the job line says is the author's own call — `community.identity` on their profile
    is the same public/private decision their secretary obeys.
    """
    if not user_ids:
        return {}
    from blackmoa.services.companies import switch as CO

    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    # 기업 기능이 꺼져 있으면 소속은 줄에 없다 (plan/71).
    companies = await CO.enabled(db)
    out: dict[uuid.UUID, Author] = {}
    for u in users:
        prof = PF.view(await PF.get(db, u.id), companies)
        data = (prof.data or {}) if prof else {}
        mode = str(data.get("community_identity") or "job")
        name = (u.nickname or u.display_name or "").strip()
        job = ""
        if mode == "job":
            job = " · ".join(x for x in [str(data.get("title") or "").strip(), str(data.get("company") or "").strip()] if x)
        out[u.id] = Author(id=str(u.id), name=name or "익명", job=job, avatar_url=u.avatar_url,
                           is_me=me is not None and u.id == me, square=pen_for(u))
    return out


# ── boards ──────────────────────────────────────────────────────────
async def boards(db: AsyncSession, *, kind: str | None = None) -> list[CommunityBoard]:
    stmt = select(CommunityBoard).where(CommunityBoard.enabled.is_(True)).order_by(CommunityBoard.sort_order)
    if kind:
        stmt = stmt.where(CommunityBoard.kind == kind)
    return list((await db.execute(stmt)).scalars().all())


async def board_activity(db: AsyncSession) -> dict[str, dict[str, Any]]:
    """Per board: how many posts, how many distinct people took part, and when it last moved.

    "Took part" counts anyone who wrote a post or a comment there, each person once even if
    they did both — it answers "is anyone here", which a post count alone does not.
    """
    posts = (await db.execute(
        select(CommunityPost.board_id, func.count(CommunityPost.id), func.max(CommunityPost.created_at))
        .where(CommunityPost.status == "published").group_by(CommunityPost.board_id))).all()
    writers = (await db.execute(
        select(CommunityPost.board_id, CommunityPost.author_id)
        .where(CommunityPost.status == "published").distinct())).all()
    talkers = (await db.execute(
        select(CommunityPost.board_id, CommunityComment.author_id)
        .join(CommunityPost, CommunityComment.post_id == CommunityPost.id)
        .where(CommunityComment.status == "published", CommunityPost.status == "published").distinct())).all()

    people: dict[uuid.UUID, set[uuid.UUID]] = {}
    for board_id, author_id in [*writers, *talkers]:
        people.setdefault(board_id, set()).add(author_id)
    out: dict[str, dict[str, Any]] = {}
    for board_id, count, last in posts:
        out[str(board_id)] = {"posts": count, "people": len(people.get(board_id, ())),
                              "last_post_at": last.isoformat() if last else None}
    return out


async def board_by_slug(db: AsyncSession, slug: str) -> CommunityBoard:
    b = (await db.execute(select(CommunityBoard).where(CommunityBoard.slug == slug))).scalars().first()
    if b is None or not b.enabled:
        raise NotFound("board not found", code="board_not_found")
    return b


# ── posts ───────────────────────────────────────────────────────────
async def _rate_guard(db: AsyncSession, author_id: uuid.UUID, table: Any, limit: int, label: str) -> None:
    """Counted in the database, so the limit is the same however many pods are serving."""
    since = datetime.now(UTC) - timedelta(hours=1)
    n = (await db.execute(select(func.count()).select_from(table)
                          .where(table.author_id == author_id, table.created_at >= since))).scalar() or 0
    if n >= limit:
        raise Forbidden(f"too many {label} in the last hour", code="community_rate_limited")


async def require_write_access(db: AsyncSession, user: User) -> None:
    """Posting and commenting need a verified address.

    Reading is open to every account; writing is where an unreachable author becomes a
    moderation problem. Per-board policies were a knob nobody needed — one rule, stated
    once, is easier to trust than seven boards with different answers.
    """
    if user.role == "admin" or user.email_verified_at is not None:
        return
    if not await S.get(db, "community.require_verified_email"):
        return
    raise Forbidden("verify your email to post", code="community_needs_verified_email")


MAX_IMAGES = 6


async def _own_images(db: AsyncSession, user: User, ids: list[str]) -> list[str]:
    """Only this author's own uploads, and only images.

    An id from the request is a claim, not a fact: without this check a post could embed
    somebody else's private upload by guessing its id.
    """
    from blackmoa.models import Upload
    out: list[str] = []
    for raw in ids[:MAX_IMAGES]:
        try:
            up = await db.get(Upload, uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            continue
        if up is not None and up.owner_id == user.id and (up.mime or "").startswith("image/"):
            out.append(str(up.id))
    return out


MAX_PEN_NAME = 30


def _clean_pen_name(name: str | None) -> str:
    return " ".join((name or "").split())[:MAX_PEN_NAME]


#: 필명을 안 정한 사람에게 지어 주는 이름의 재료. 광장에서 흔히 쓰는 말투다.
_PEN_HEAD = ("퇴근하고싶은", "야근중인", "이직준비하는", "커피마시는", "월요일싫은",
             "코드짜는", "회의많은", "점심고민하는", "주말기다리는", "출근길의")
_PEN_TAIL = ("직장인", "개발자", "기획자", "디자이너", "사람", "팀원", "선배", "후배")


def pen_name_for(user_id: uuid.UUID) -> str:
    """이 사람의 광장 이름. **같은 사람은 늘 같은 이름이다.**

    광장은 익명이지만 무명은 아니다. 글마다 이름이 달라지면 대화가 이어지지 않고,
    답글이 누구에게 하는 말인지 알 수 없다. 계정 id 에서 뽑으므로 같은 사람은 늘
    같은 이름이 되고, 그 이름에서 계정으로 거꾸로 갈 길은 없다 (plan/51).
    """
    h = int.from_bytes(hashlib.sha256(str(user_id).encode()).digest()[:8], "big")
    return f"{_PEN_HEAD[h % len(_PEN_HEAD)]} {_PEN_TAIL[(h // len(_PEN_HEAD)) % len(_PEN_TAIL)]}"


#: 이름을 바꿀 수 있는 간격 (plan/52).
#:
#: 익명 게시판에서 이름은 그 사람 자체다. 오늘 쓴 글과 어제 쓴 글이 같은 사람의
#: 것인지 읽는 사람이 알 수 있어야 대화가 된다. 매일 바꿀 수 있으면 이름이 아니라
#: 가면이 되고, 하고 싶은 말만 하고 이름을 바꿔 도망갈 수 있다.
NAME_CHANGE_DAYS = 7


def name_wait_days(user: User, now: datetime | None = None) -> int:
    """이름을 바꾸려면 며칠 더 기다려야 하나. 0이면 지금 바꿀 수 있다."""
    at = getattr(user, "community_name_at", None)
    if at is None:
        return 0
    left = timedelta(days=NAME_CHANGE_DAYS) - ((now or datetime.now(UTC)) - at)
    return max(0, -(-int(left.total_seconds()) // 86400))


async def set_community_name(db: AsyncSession, user: User, name: str) -> User:
    """광장 이름을 정한다 (plan/52).

    처음 정하는 것은 바꾸는 것이 아니다. 가입하자마자 한 주를 기다리게 할 이유가 없다.
    """
    want = _clean_pen_name(name)
    if len(want) < 2:
        raise ValidationFailed("이름은 두 글자 이상이어야 해요.", code="name_too_short")
    had = (user.community_name or "").strip()
    if want.lower() == had.lower():
        return user
    if had and (wait := name_wait_days(user)):
        raise Conflict(f"{wait}일 뒤에 바꿀 수 있어요.", code="name_change_too_soon", detail={"days": wait})
    # 같은 이름 둘은 익명 게시판에서 서로를 사칭하는 것과 같다.
    clash = (await db.execute(select(User).where(User.community_name == want, User.id != user.id))).scalars().first()
    if clash is not None:
        raise Conflict("이미 누가 쓰고 있는 이름이에요.", code="name_taken")
    user.community_name = want
    # 처음 정한 것은 시계를 돌리지 않는다.
    if had:
        user.community_name_at = datetime.now(UTC)
    return user


def pen_for(user: User) -> str:
    """이 사람이 광장에서 쓰는 이름.

    계정에 정해 둔 것 하나다. 글마다 적게 두면 같은 사람이 여러 이름으로 흩어지고,
    남의 실명을 적어 넣는 길도 열린다 (plan/52).

    정해 둔 것이 없을 때의 지어 준 이름은 **보여 주기 위한 마지막 수단일 뿐**이다.
    광장에서 입을 여는 사람은 `ensure_square_name` 이 먼저 이름을 받아 적는다.
    """
    return (getattr(user, "community_name", None) or "").strip() or pen_name_for(user.id)


async def ensure_square_name(db: AsyncSession, user: User) -> str:
    """광장에서 입을 열기 전에 이름을 하나 받아 둔다 (plan/52).

    지어 주는 이름은 계정 id 의 해시에서 뽑는데, 그 경우의 수는 80가지다. 열한
    명에서 이미 부딪혔다 — 고른 이름 하나와 지어 준 이름 하나가 같은 이름이 됐다.
    **익명 게시판에서 같은 이름 둘은 서로를 사칭하는 것과 같고**, 계산해서 보여
    주기만 하는 이름은 plan/52 가 세워 둔 세 겹(유일 제약·name_taken·이관 루프)을
    모두 비켜 간다. 세는 자리에 없는 이름은 아무도 막을 수 없다.

    그래서 계산하지 않고 **적어 둔다.** 부딪히면 뒤에 숫자를 붙이는 것은 0066 이
    기존 이름을 이식할 때 한 것과 같다. 스스로 고른 이름이 아니므로 시계는 돌리지
    않는다 — 마음에 안 들면 그 자리에서 한 번 바꿀 수 있어야 한다.
    """
    have = (user.community_name or "").strip()
    if have:
        return have
    base = pen_name_for(user.id)
    name, i = base, 2
    while (await db.execute(select(User.id).where(User.community_name == name))).first() is not None:
        name = f"{base}{i}"
        i += 1
    user.community_name = name
    await db.flush()
    return name


#: Boards people write posts on. `jobs` takes postings through its own path.
WRITABLE_KINDS = ("discussion",)


#: 광장은 **익명 커뮤니티**다. 비서는 여기를 보지 않는다 (plan/51).
#:
#: 예전에는 실명으로 쓴 글만 비서의 재료로 들였다. 그 다리를 없앤다. 익명이라는
#: 말은 "그 글이 나와 이어지지 않는다" 는 뜻이고, 내 비서가 그 글을 알고 있으면
#: 언젠가 어떤 말끝에서 두 이름이 만난다. 설정으로 막는 것이 아니라 길을 내지 않는다.
#:
#: 내 글이 비서에게 가는 길은 [피드] 하나다. 거기는 실명이고 내 집이다 (plan/41).
async def create_post(db: AsyncSession, *, author: User, board_slug: str, title: str, body: str,
                      client_token: str | None = None, images: list[str] | None = None) -> CommunityPost:
    board = await board_by_slug(db, board_slug)
    if board.kind not in WRITABLE_KINDS:
        raise ValidationFailed("this board does not take posts", code="board_not_writable")
    await require_write_access(db, author)
    # 광장에 설 이름이 없으면 쓸 수 없다 (plan/52). 여기서 막고 화면이 정하러
    # 보낸다. 이름 없이 쓰게 두면 그 자리에서 무엇이든 지어내야 한다.
    if not (author.community_name or "").strip():
        raise ValidationFailed("광장에서 쓸 이름을 먼저 정해 주세요.", code="community_name_required")
    title, body = title.strip(), body.strip()
    if not title or not body:
        raise ValidationFailed("title and body are required", code="post_incomplete")
    if len(title) > MAX_TITLE or len(body) > MAX_BODY:
        raise ValidationFailed("too long", code="post_too_long")
    if client_token:
        dup = (await db.execute(select(CommunityPost).where(CommunityPost.author_id == author.id,
                                                            CommunityPost.client_token == client_token))).scalars().first()
        if dup is not None:      # the same submit arriving twice is one post
            return dup
    await _rate_guard(db, author.id, CommunityPost, POSTS_PER_HOUR, "posts")
    post = CommunityPost(board_id=board.id, author_id=author.id, title=title, body=body, client_token=client_token,
                         meta={"images": await _own_images(db, author, images or []),
                               "author_name": pen_for(author)})
    db.add(post)
    await db.execute(update(CommunityBoard).where(CommunityBoard.id == board.id)
                     .values(post_count=CommunityBoard.post_count + 1))
    await db.flush()
    return post


async def get_post(db: AsyncSession, post_id: uuid.UUID, *, include_hidden: bool = False) -> CommunityPost:
    p = await db.get(CommunityPost, post_id)
    if p is None or (p.status != "published" and not include_hidden):
        raise NotFound("post not found", code="post_not_found")
    return p


async def update_post(db: AsyncSession, *, post: CommunityPost, user: User, title: str | None,
                      body: str | None, version: int | None, images: list[str] | None = None) -> CommunityPost:
    if post.author_id != user.id and user.role != "admin":
        raise Forbidden("not your post", code="not_your_post")
    if version is not None and version != post.version:
        raise Conflict("this post changed while you were editing", code="post_version_conflict")
    if title is not None:
        post.title = title.strip()[:MAX_TITLE] or post.title
    if body is not None:
        post.body = body.strip()[:MAX_BODY] or post.body
    if images is not None:
        post.meta = {**(post.meta or {}), "images": await _own_images(db, user, images)}
    post.version += 1
    post.edited_at = datetime.now(UTC)
    return post


async def delete_post(db: AsyncSession, *, post: CommunityPost, user: User) -> None:
    if post.author_id != user.id and user.role != "admin":
        raise Forbidden("not your post", code="not_your_post")
    # Soft: the comment thread under it belongs to other people.
    post.status = "deleted"
    await db.execute(update(CommunityBoard).where(CommunityBoard.id == post.board_id)
                     .values(post_count=func.greatest(CommunityBoard.post_count - 1, 0)))


async def list_posts(db: AsyncSession, *, board: CommunityBoard | None, sort: str = "new",
                     limit: int = 20, cursor: str | None = None, author_id: uuid.UUID | None = None,
                     q: str | None = None, include_pen: bool = False) -> tuple[list[CommunityPost], str | None]:
    stmt = select(CommunityPost).where(CommunityPost.status == "published")
    if board is not None:
        stmt = stmt.where(CommunityPost.board_id == board.id)
    if author_id is not None:
        stmt = stmt.where(CommunityPost.author_id == author_id)
        if not include_pen:
            # Asking "what has this person written" must not answer with the posts they
            # deliberately signed with another name (plan/41 §1). Only they see those.
            # The key is always present and empty when there is no pen name, so the test is
            # on the value.
            stmt = stmt.where(func.coalesce(CommunityPost.meta["author_name"].astext, "") == "")
    if q:
        # Three legs, like the knowledge base: full-text for words the tokenizer knows,
        # trigram for Korean it does not, ILIKE for the literal substring someone typed.
        needle = q.strip()
        like = f"%{needle}%"
        stmt = stmt.where(
            text("(search @@ plainto_tsquery('simple', :needle)"
                 " OR title % :needle OR body % :needle"
                 " OR title ILIKE :like OR body ILIKE :like)")
        ).params(needle=needle, like=like)
    if sort == "hot":
        stmt = stmt.order_by(CommunityPost.hot_score.desc(), CommunityPost.created_at.desc())
    elif sort == "top":
        stmt = stmt.order_by(CommunityPost.like_count.desc(), CommunityPost.created_at.desc())
    else:
        stmt = stmt.order_by(CommunityPost.created_at.desc())
    if cursor and sort == "new":
        try:
            stmt = stmt.where(CommunityPost.created_at < datetime.fromisoformat(cursor))
        except ValueError:
            pass
    rows = list((await db.execute(stmt.limit(limit + 1))).scalars().all())
    nxt = rows[limit - 1].created_at.isoformat() if len(rows) > limit and sort == "new" else None
    return rows[:limit], nxt


async def register_view(db: AsyncSession, post: CommunityPost, viewer_key: str) -> None:
    """Counts a reader once a day. The increment rides on the insert actually happening, so
    a popular post is not one row every reader has to queue behind."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    res = await db.execute(pg_insert(CommunityPostView.__table__)
                           .values(id=uuid.uuid4(), post_id=post.id, viewer_key=viewer_key[:64], day=day)
                           .on_conflict_do_nothing(constraint="uq_community_post_view"))
    if res.rowcount:
        await db.execute(update(CommunityPost).where(CommunityPost.id == post.id)
                         .values(view_count=CommunityPost.view_count + 1))


# ── comments ────────────────────────────────────────────────────────
async def _notify(db: AsyncSession, *, to_user_id: uuid.UUID, actor: User, kind: str,
                  post: CommunityPost, comment: CommunityComment) -> None:
    """A reply is worth telling someone about — unless they are replying to themselves.

    **광장 이름으로 알린다** (plan/51 §2). 글과 댓글에서 실명을 걷어내고도 알림이
    실명을 들고 나가면 익명은 없는 것과 같다: 내 글에 달린 댓글 하나로 그 사람의
    계정 이름을 알게 된다. 인박스도 토스트도 이 payload 하나를 읽으므로 여기서
    막으면 두 곳이 함께 고쳐진다.
    """
    if to_user_id == actor.id:
        return
    from blackmoa.services import inbox as I
    await I.create(db, owner_id=to_user_id, agent_id=None, kind=kind, payload={
        "post_id": str(post.id), "post_title": post.title,
        "comment_id": str(comment.id), "excerpt": comment.body[:160],
        "actor_name": pen_for(actor),
    })


async def add_comment(db: AsyncSession, *, post: CommunityPost, author: User, body: str,
                      parent_id: uuid.UUID | None) -> CommunityComment:
    await require_write_access(db, author)
    # 댓글도 광장에 서는 것이다. 글과 달리 이름을 정하러 보내지는 않지만(답글 하나에
    # 다른 화면으로 보내는 것은 대화를 끊는다), 이름은 여기서 받아 적는다.
    await ensure_square_name(db, author)
    body = body.strip()
    if not body:
        raise ValidationFailed("empty comment", code="comment_empty")
    if len(body) > MAX_COMMENT:
        raise ValidationFailed("too long", code="comment_too_long")
    await _rate_guard(db, author.id, CommunityComment, COMMENTS_PER_HOUR, "comments")
    depth = 0
    if parent_id is not None:
        parent = await db.get(CommunityComment, parent_id)
        if parent is None or parent.post_id != post.id:
            raise NotFound("parent comment not found", code="comment_not_found")
        depth = min(parent.depth + 1, 2)     # two levels is a conversation; deeper is a maze
    c = CommunityComment(post_id=post.id, author_id=author.id, parent_id=parent_id, body=body, depth=depth)
    db.add(c)
    await db.execute(update(CommunityPost).where(CommunityPost.id == post.id)
                     .values(comment_count=CommunityPost.comment_count + 1))
    await db.flush()
    if parent_id is not None:
        parent = await db.get(CommunityComment, parent_id)
        if parent is not None:
            await _notify(db, to_user_id=parent.author_id, actor=author, kind="community_reply", post=post, comment=c)
        if parent is None or parent.author_id != post.author_id:
            await _notify(db, to_user_id=post.author_id, actor=author, kind="community_comment", post=post, comment=c)
    else:
        await _notify(db, to_user_id=post.author_id, actor=author, kind="community_comment", post=post, comment=c)
    return c


async def comments_for(db: AsyncSession, post: CommunityPost, *, sort: str = "new") -> list[CommunityComment]:
    order = CommunityComment.like_count.desc() if sort == "top" else CommunityComment.created_at.asc()
    stmt = select(CommunityComment).where(CommunityComment.post_id == post.id).order_by(order)
    return list((await db.execute(stmt)).scalars().all())


async def edit_comment(db: AsyncSession, *, comment: CommunityComment, user: User, body: str) -> CommunityComment:
    if comment.author_id != user.id and user.role != "admin":
        raise Forbidden("not your comment", code="not_your_comment")
    comment.body = body.strip()[:MAX_COMMENT] or comment.body
    comment.version += 1
    return comment


async def delete_comment(db: AsyncSession, *, comment: CommunityComment, user: User) -> None:
    if comment.author_id != user.id and user.role != "admin":
        raise Forbidden("not your comment", code="not_your_comment")
    comment.status = "deleted"
    comment.body = ""
    await db.execute(update(CommunityPost).where(CommunityPost.id == comment.post_id)
                     .values(comment_count=func.greatest(CommunityPost.comment_count - 1, 0)))


# ── reactions ───────────────────────────────────────────────────────
async def toggle_like(db: AsyncSession, *, target_type: str, target_id: uuid.UUID, user: User) -> tuple[bool, int]:
    """Returns (liked_now, delta). The unique constraint decides the outcome, not a prior
    SELECT — two taps racing each other cannot both count."""
    table = CommunityPost if target_type == "post" else CommunityComment
    res = await db.execute(pg_insert(CommunityReaction.__table__)
                           .values(id=uuid.uuid4(), target_type=target_type, target_id=target_id,
                                   user_id=user.id, kind="like")
                           .on_conflict_do_nothing(constraint="uq_community_reaction"))
    if res.rowcount:
        await db.execute(update(table).where(table.id == target_id).values(like_count=table.like_count + 1))
        return True, 1
    await db.execute(delete(CommunityReaction).where(CommunityReaction.target_type == target_type,
                                                     CommunityReaction.target_id == target_id,
                                                     CommunityReaction.user_id == user.id,
                                                     CommunityReaction.kind == "like"))
    await db.execute(update(table).where(table.id == target_id)
                     .values(like_count=func.greatest(table.like_count - 1, 0)))
    return False, -1


async def liked_ids(db: AsyncSession, *, target_type: str, ids: list[uuid.UUID], user_id: uuid.UUID | None) -> set[uuid.UUID]:
    if not ids or user_id is None:
        return set()
    rows = await db.execute(select(CommunityReaction.target_id)
                            .where(CommunityReaction.target_type == target_type,
                                   CommunityReaction.user_id == user_id,
                                   CommunityReaction.target_id.in_(ids)))
    return {r[0] for r in rows}


async def report(db: AsyncSession, *, target_type: str, target_id: uuid.UUID, user: User,
                 reason: str, detail: str = "") -> None:
    db.add(CommunityReport(target_type=target_type, target_id=target_id, reporter_id=user.id,
                           reason=reason[:40], detail=detail[:2000]))


# ── ranking ─────────────────────────────────────────────────────────
async def recompute_hot(db: AsyncSession, *, window_hours: int = 72) -> int:
    """Ranking is a background write, not a per-request sort.

    Score = engagement over a decaying age, the classic shape: a good post fades, a great
    one stays up longer. The weights are settings because the right balance depends on how
    a community actually behaves, and that is not knowable in advance. Recomputed for the
    recent window only, which is all a feed shows.
    """
    res = await db.execute(text("""
        UPDATE community_posts SET hot_score =
            (like_count * :w_like + comment_count * :w_comment + LEAST(view_count, 500) * :w_view + 1)
            / POWER(EXTRACT(EPOCH FROM (now() - created_at)) / 3600.0 + 2, :gravity)
        WHERE status = 'published' AND created_at > now() - make_interval(hours => :h)
    """), {"h": window_hours,
           "w_like": float(await S.get(db, "community.rank_like_weight") or 3.0),
           "w_comment": float(await S.get(db, "community.rank_comment_weight") or 2.0),
           "w_view": float(await S.get(db, "community.rank_view_weight") or 0.1),
           "gravity": float(await S.get(db, "community.rank_gravity") or 1.5)})
    return res.rowcount or 0


# ── jobs ────────────────────────────────────────────────────────────
JOBS_PER_DAY = 5


async def list_jobs(db: AsyncSession, *, limit: int = 30, company_id=None, **filters) -> list[CommunityJob]:
    from sqlalchemy.orm import selectinload

    stmt = _job_filters(select(CommunityJob).where(CommunityJob.status == "open"), **filters)
    if company_id is not None:
        stmt = stmt.where(CommunityJob.company_id == company_id)
    # Eager, because the alternative is one query per posting to render the employer card.
    stmt = stmt.options(selectinload(CommunityJob.company_obj))
    stmt = stmt.order_by(CommunityJob.created_at.desc()).limit(min(limit, 50))
    return list((await db.execute(stmt)).scalars().all())


def _job_filters(stmt, *, q: str | None = None, regions: list[str] | None = None,
                 jobs: list[str] | None = None, industries: list[str] | None = None,
                 employment_types: list[str] | None = None, max_experience: int | None = None,
                 min_salary: int | None = None, max_salary: int | None = None,
                 remote_only: bool = False, tags: list[str] | None = None):
    """Every dimension narrows; several values inside one dimension widen it.

    Written once so a facet count can never disagree with the list it promises.
    """
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(CommunityJob.title.ilike(like) | CommunityJob.company.ilike(like)
                          | CommunityJob.description.ilike(like))
    # Picking a parent means everything under it, so the code list is expanded before it is
    # matched — a search for 서울특별시 has to find a posting filed under 강남구.
    stmt = _any_code(stmt, CommunityJob.region_codes, regions, REGION_INDEX)
    stmt = _any_code(stmt, CommunityJob.job_codes, jobs, JOB_INDEX)
    stmt = _any_code(stmt, CommunityJob.industry_codes, industries, INDUSTRY_INDEX)
    if employment_types:
        picked = [x for x in employment_types if x]
        if picked:
            stmt = stmt.where(CommunityJob.employment_type.in_(picked))
    if remote_only:
        stmt = stmt.where(CommunityJob.remote.is_(True))
    if max_experience is not None:
        # "3년차인데 지원할 수 있나" — a listing asking for more than you have is noise.
        stmt = stmt.where(CommunityJob.experience_min <= max_experience)
    if min_salary is not None:
        # A listing that names no pay cannot promise a floor, so it drops out rather than
        # counting as a maybe. The ceiling decides: an 8,000-9,000 range clears 8,500.
        top = func.coalesce(CommunityJob.salary_max, CommunityJob.salary_min)
        stmt = stmt.where(top.isnot(None)).where(top >= min_salary)
    if max_salary is not None:
        floor = func.coalesce(CommunityJob.salary_min, CommunityJob.salary_max)
        stmt = stmt.where(floor.isnot(None)).where(floor <= max_salary)
    if tags:
        picked = [x for x in tags if x]
        if picked:
            stmt = stmt.where(or_(*[CommunityJob.tags.contains(cast([x], JSONB)) for x in picked]))
    return stmt


def _any_code(stmt, column, picked: list[str] | None, index: dict[str, list[str]]):
    """Match a posting that carries any of the picked codes, or any code beneath them."""
    if not picked:
        return stmt
    wanted: set[str] = set()
    for code in picked:
        if not code:
            continue
        wanted.update(index.get(code) or [code])
    if not wanted:
        return stmt
    return stmt.where(or_(*[column.contains(cast([c], JSONB)) for c in sorted(wanted)]))


async def job_facets(db: AsyncSession) -> dict[str, Any]:
    """How many open postings each code would leave, counted up the tree.

    A posting filed under 강남구 also counts towards 서울특별시: a parent that showed 0 while
    its children showed 12 would read as a dead end that is not one.
    """
    rows = list((await db.execute(select(CommunityJob).where(CommunityJob.status == "open"))).scalars().all())
    regions: dict[str, int] = {}
    families: dict[str, int] = {}
    industries: dict[str, int] = {}
    types: dict[str, int] = {}
    tags: dict[str, int] = {}
    remote = 0

    def roll(bucket: dict[str, int], codes: list[str], parents: dict[str, str]) -> None:
        # Each posting counts once per code, however many of its children matched.
        seen: set[str] = set()
        for code in codes or []:
            node = str(code)
            while node and node not in seen:
                seen.add(node)
                node = parents.get(node, "")
        for code in seen:
            bucket[code] = bucket.get(code, 0) + 1

    for j in rows:
        roll(regions, j.region_codes or [], REGION_PARENT)
        roll(families, j.job_codes or [], JOB_PARENT)
        roll(industries, j.industry_codes or [], INDUSTRY_PARENT)
        kind = j.employment_type or "fulltime"
        types[kind] = types.get(kind, 0) + 1
        if j.remote:
            remote += 1
        for x in (j.tags or []):
            name = str(x).strip()
            if name:
                tags[name] = tags.get(name, 0) + 1

    def ranked(d: dict[str, int]) -> list[dict[str, Any]]:
        return [{"value": k, "count": v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {"total": len(rows), "remote": remote,
            "region": regions, "job": families, "industry": industries, "type": types,
            "tags": ranked(tags)[:60]}


async def create_job(db: AsyncSession, *, user: User, data: dict[str, Any]) -> CommunityJob:
    # A posting names its employer as free text. When that text unambiguously matches one
    # company in the directory, link it so the reader gets the employer's details — and
    # only when it is unambiguous, because attaching a posting to the wrong company is
    # worse than leaving it unlinked (plan/33 §5).
    from blackmoa.services.companies.query import match_by_name

    if data.get("company_id"):
        from blackmoa.models import Company

        picked = await db.get(Company, data["company_id"])
        data = {**data, "company_id": picked.id if (picked is not None and not picked.hidden) else None}
    if not data.get("company_id") and data.get("company"):
        hit = await match_by_name(db, data["company"])
        if hit is not None:
            data = {**data, "company_id": hit.id}
    title = str(data.get("title") or "").strip()
    company = str(data.get("company") or "").strip()
    if not title or not company:
        raise ValidationFailed("title and company are required", code="job_incomplete")
    since = datetime.now(UTC) - timedelta(days=1)
    n = (await db.execute(select(func.count()).select_from(CommunityJob)
                          .where(CommunityJob.posted_by == user.id, CommunityJob.created_at >= since))).scalar() or 0
    if n >= JOBS_PER_DAY:
        raise Forbidden("too many postings today", code="community_rate_limited")
    regions = _known_codes(data.get("region_codes"), REGION_INDEX, cap=5)
    job = CommunityJob(
        title=title[:160], company=company[:120],
        # The display line follows the codes when the poster picked them, so a listing can
        # never show one place and be filed under another.
        location=(region_label(regions) or str(data.get("location") or ""))[:120],
        employment_type=str(data.get("employment_type") or "fulltime")[:24],
        experience_min=max(0, int(data.get("experience_min") or 0)),
        salary_min=data.get("salary_min"), salary_max=data.get("salary_max"),
        tags=[str(x)[:24] for x in (data.get("tags") or [])][:8],
        region_codes=regions,
        job_codes=_known_codes(data.get("job_codes"), JOB_INDEX, cap=5),
        industry_codes=_known_codes(data.get("industry_codes"), INDUSTRY_INDEX, cap=3),
        remote=bool(data.get("remote")),
        description=str(data.get("description") or "")[:MAX_BODY],
        apply_url=str(data.get("apply_url") or "")[:2000], posted_by=user.id,
        # Set either by the poster picking from name completion or derived above from an
        # unambiguous name. The constructor lists its fields explicitly, so a value that is
        # not named here is silently dropped — which is what happened to this one.
        company_id=data.get("company_id"))
    db.add(job)
    await db.flush()
    if job.company_id:
        from blackmoa.models import Company
        from blackmoa.services.companies import reviews as RV

        employer = await db.get(Company, job.company_id)
        if employer is not None:
            await RV.notify_followers(db, employer, kind="company_job", exclude=user.id,
                                      payload={"job_id": str(job.id), "title": job.title, "location": job.location,
                                               "salary_min": job.salary_min, "salary_max": job.salary_max})
    return job


def _known_codes(raw: Any, index: dict[str, list[str]], *, cap: int) -> list[str]:
    """Keep only codes the taxonomy actually defines.

    A posting filed under a code nobody can pick is invisible to every filter, which is a
    worse outcome than dropping the unknown value on the way in.
    """
    out: list[str] = []
    for x in (raw or []):
        code = str(x).strip()
        if code in index and code not in out:
            out.append(code)
    return out[:cap]


def region_label(codes: list[str]) -> str:
    """The human line for picked regions: "서울 강남구" or "서울 강남구 외 2곳"."""
    if not codes:
        return ""
    names = [REGION_NAME.get(c, "") for c in codes]
    names = [n for n in names if n]
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}곳"


async def close_job(db: AsyncSession, *, job: CommunityJob, user: User) -> None:
    if job.posted_by != user.id and user.role != "admin":
        raise Forbidden("not your posting", code="not_your_job")
    job.status = "closed"


# ── administration ──────────────────────────────────────────────────
async def boards_all(db: AsyncSession) -> list[CommunityBoard]:
    """Every board, disabled ones included — the console has to see what it turned off."""
    return list((await db.execute(select(CommunityBoard).order_by(CommunityBoard.sort_order))).scalars().all())


async def admin_create_board(db: AsyncSession, *, slug: str, name: str, description: str = "",
                             kind: str = "discussion", icon: str = "", sort_order: int = 100) -> CommunityBoard:
    slug = slug.strip().lower()
    if not slug or not name.strip():
        raise ValidationFailed("slug and name are required", code="board_incomplete")
    if (await db.execute(select(CommunityBoard).where(CommunityBoard.slug == slug))).scalars().first():
        raise Conflict("that slug is taken", code="board_slug_taken")
    b = CommunityBoard(slug=slug[:48], name=name.strip()[:60], description=description[:400],
                       kind=kind if kind in ("discussion", "jobs") else "discussion",
                       icon=icon[:24], sort_order=sort_order)
    db.add(b)
    await db.flush()
    return b


async def admin_update_board(db: AsyncSession, board_id: uuid.UUID, patch: dict[str, Any]) -> CommunityBoard:
    b = await db.get(CommunityBoard, board_id)
    if b is None:
        raise NotFound("board not found", code="board_not_found")
    for field in ("name", "description", "icon"):
        if field in patch and patch[field] is not None:
            setattr(b, field, str(patch[field])[:400])
    if "sort_order" in patch and patch["sort_order"] is not None:
        b.sort_order = int(patch["sort_order"])
    if "enabled" in patch and patch["enabled"] is not None:
        # Disabling hides a board from the rail; its posts stay, so it can be turned back on.
        b.enabled = bool(patch["enabled"])
    return b


async def admin_posts(db: AsyncSession, *, status: str = "published", limit: int = 50) -> list[dict[str, Any]]:
    rows = list((await db.execute(select(CommunityPost).where(CommunityPost.status == status)
                                  .order_by(CommunityPost.created_at.desc()).limit(min(limit, 200)))).scalars().all())
    authors = await authors_for(db, {p.author_id for p in rows}, me=None)
    board_names = {b.id: b.name for b in await boards_all(db)}
    # 관리 화면도 광장 이름으로 본다 (plan/51 §2). 신고 처리 화면은 이미 글쓴이가
    # 누구인지 없이 돌아간다 — 내리고 지우는 것은 글에 하는 일이지 사람에게 하는
    # 일이 아니다. 계정에 손대야 할 일은 사용자 관리에서, 그 자리에서 한다.
    return [{"id": str(p.id), "title": p.title, "excerpt": p.body[:120], "board": board_names.get(p.board_id, ""),
             "author": authors.get(p.author_id).square if authors.get(p.author_id) else "",
             "status": p.status, "like_count": p.like_count, "comment_count": p.comment_count,
             "created_at": p.created_at.isoformat()} for p in rows]


async def admin_set_post_status(db: AsyncSession, post_id: uuid.UUID, status: str) -> None:
    if status not in ("published", "hidden", "deleted"):
        raise ValidationFailed("bad status", code="bad_status")
    p = await db.get(CommunityPost, post_id)
    if p is None:
        raise NotFound("post not found", code="post_not_found")
    p.status = status


async def admin_reports(db: AsyncSession, *, status: str = "open") -> list[dict[str, Any]]:
    rows = list((await db.execute(select(CommunityReport).where(CommunityReport.status == status)
                                  .order_by(CommunityReport.created_at.desc()).limit(200))).scalars().all())
    out: list[dict[str, Any]] = []
    for r in rows:
        target: dict[str, Any] = {"kind": r.target_type, "id": str(r.target_id), "gone": True}
        if r.target_type == "post":
            p = await db.get(CommunityPost, r.target_id)
            if p is not None:
                target = {"kind": "post", "id": str(p.id), "title": p.title, "excerpt": p.body[:160],
                          "status": p.status, "gone": False}
        elif r.target_type == "review":
            from blackmoa.models import CompanyReview
            rv = await db.get(CompanyReview, r.target_id)
            if rv is not None:
                target = {"kind": "review", "id": str(rv.id), "company_id": str(rv.company_id), "title": rv.title,
                          "excerpt": (rv.pros + " / " + rv.cons)[:160], "status": rv.status, "gone": False}
        else:
            c = await db.get(CommunityComment, r.target_id)
            if c is not None:
                target = {"kind": "comment", "id": str(c.id), "post_id": str(c.post_id),
                          "excerpt": c.body[:160], "status": c.status, "gone": False}
        out.append({"id": str(r.id), "reason": r.reason, "detail": r.detail,
                    "created_at": r.created_at.isoformat(), "target": target})
    return out


async def admin_resolve_report(db: AsyncSession, report_id: uuid.UUID, *, action: str, admin_id: uuid.UUID) -> None:
    """`hide` takes the content down as well; `dismiss` only closes the report.

    Both close it — an untouched queue is a queue nobody reads.
    """
    r = await db.get(CommunityReport, report_id)
    if r is None:
        raise NotFound("report not found", code="report_not_found")
    if action == "hide":
        if r.target_type == "post":
            p = await db.get(CommunityPost, r.target_id)
            if p is not None:
                p.status = "hidden"
        elif r.target_type == "review":
            from blackmoa.services.companies import reviews as RV
            with contextlib.suppress(NotFound):
                await RV.set_status(db, r.target_id, "hidden")
        else:
            c = await db.get(CommunityComment, r.target_id)
            if c is not None:
                c.status = "hidden"
    r.status = "resolved" if action == "hide" else "dismissed"


# ── what to read next ───────────────────────────────────────────────
# Which board a job title suggests. Crude on purpose: a wrong guess costs an ordering, and
# the feed still shows everything.
JOB_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("개발", "엔지니어", "engineer", "developer", "프로그래", "데이터", "ai", "ml"), "career"),
    (("디자", "design"), "career"),
    (("영업", "세일즈", "sales", "마케", "marketing"), "worklife"),
    (("인사", "hr", "채용", "리크루", "recruit"), "interview"),
    (("재무", "회계", "financ", "투자"), "money"),
]


async def suggested_boards(db: AsyncSession, user: User) -> list[str]:
    prof = await PF.shown(db, user.id)
    data = (prof.data or {}) if prof else {}
    blob = " ".join(str(data.get(k) or "") for k in ("title", "company", "bio", "extra")).lower()
    hits = [slug for words, slug in JOB_HINTS if any(w in blob for w in words)]
    return list(dict.fromkeys(hits)) or ["worklife", "career"]


async def profile_readiness(db: AsyncSession, user: User) -> dict[str, Any]:
    """Whether this member has told us enough to be worth a job line — the nudge that turns
    an anonymous reader into someone others recognise."""
    prof = await PF.get(db, user.id)
    data = (prof.data or {}) if prof else {}
    has_name = bool((user.nickname or data.get("preferred_name") or data.get("full_name") or "").strip())
    has_job = bool(str(data.get("title") or "").strip())
    return {"has_name": has_name, "has_job": has_job, "complete": has_name and has_job}


async def feed_for_me(db: AsyncSession, user: User, *, limit: int = 20) -> list[CommunityPost]:
    """Hot, but with the boards this person's own profile points at first."""
    slugs = await suggested_boards(db, user)
    ids = [b.id for b in await boards(db) if b.slug in slugs]
    rows: list[CommunityPost] = []
    if ids:
        rows = list((await db.execute(
            select(CommunityPost).where(CommunityPost.status == "published", CommunityPost.board_id.in_(ids))
            .order_by(CommunityPost.hot_score.desc(), CommunityPost.created_at.desc()).limit(limit))).scalars().all())
    if len(rows) < limit:
        seen = {p.id for p in rows}
        more = list((await db.execute(
            select(CommunityPost).where(CommunityPost.status == "published")
            .order_by(CommunityPost.hot_score.desc(), CommunityPost.created_at.desc())
            .limit(limit * 2))).scalars().all())
        rows += [p for p in more if p.id not in seen][: limit - len(rows)]
    return rows
