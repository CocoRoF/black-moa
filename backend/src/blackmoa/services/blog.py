"""A person's own writing (plan/41 §4).

Two rules shape this service. A post lives at its author's own address, so slugs are
unique per author and nowhere else. And publishing does two things at once: the page goes
up, and the same words become material the author's secretary can answer from. Editing the
post edits both; taking it down takes down both.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import Conflict, NotFound, ValidationFailed
from blackmoa.core.security import sign_state
from blackmoa.models import BlogPost, PersonFollow, PostComment, PostReaction, User
from blackmoa.services import knowledge as K

MAX_TITLE = 200
MAX_BODY = 40_000
#: A note is what somebody types into 소식. It is read on a card, between two photos, on a
#: phone. Past a thousand characters it stops being a post and starts being an article, and
#: an article has a title and its own page (plan/42 §4).
MAX_NOTE_BODY = 1_000
#: 글에 붙는 범위. 저장된 값은 `friends` 이고, 뜻은 정본의 `known` 과 같다
#: (plan/48 §2). 이미 쓰인 글이 수천 개일 수 있어 값 자체는 옮기지 않고
#: `VIS.normalize` 가 읽을 때 옮긴다.
VISIBILITIES = ("public", "friends", "private")
KINDS = ("note", "article")
#: 댓글은 500자. 피드는 [사진 + 짧은 글]이고, 그 아래 달리는 말도 같은 크기다. 긴 글은
#: 광장에서 쓴다 (plan/42 §4·§14).
MAX_COMMENT = 500
#: A note shows its body, so its title is only ever an address and a heading for the
#: secretary's copy. One line is enough for both.
NOTE_TITLE = 60
MAX_IMAGES = 8
# 한 글에서 비서가 함께 보는 사진 수와, 본 것을 적어 두는 길이.
PHOTOS_PER_POST = 4
SEEN_MAX = 900
#: Naming a secretary asks it to read the post and answer, and every one of those is a
#: turn somebody pays for. Three is more than a post ever needs (plan/43 §6).
MAX_AGENT_MENTIONS = 3
#: Long enough that a page left open all morning still shows its photos, short enough
#: that a link copied out of the HTML stops working.
IMAGE_TTL_MIN = 720
#: Keep Hangul and word characters; a Korean title makes a Korean address, which is what
#: the author typed and what a reader recognises.
_KEEP = re.compile(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ\s-]+")
#: `@handle` in a caption. Handles are the addresses people already have (plan/41 §2), so
#: naming somebody is writing the address they already answer to.
_MENTION = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.-]{1,31})")


def slugify(title: str) -> str:
    s = _KEEP.sub("", (title or "").strip().lower())
    s = re.sub(r"[\s-]+", "-", s).strip("-")[:80]
    return s or secrets.token_hex(4)


async def agents_named(db: AsyncSession, body: str, *, picked: list[str] | None = None) -> list[tuple[str, Any, str]]:
    """The published secretaries this text names (plan/43 §6).

    Naming one is asking it to read the post and answer, so this is capped: the cap is not
    announced up front, because a rule nobody was going to break is noise. Somebody who
    reaches it is told then.
    """
    from blackmoa.models import Agent, ShareLink
    from blackmoa.services import agents as A

    out: list[tuple[str, Any, str]] = []
    seen: set[uuid.UUID] = set()
    text = body or ""
    for raw in (picked or [])[:20]:
        try:
            agent = await db.get(Agent, uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            continue
        if agent is None or agent.status != "active" or agent.id in seen:
            continue
        if f"@{agent.name}" not in text:
            continue
        link = (await db.execute(select(ShareLink).where(ShareLink.agent_id == agent.id, A.open_link())
                                 .order_by(ShareLink.created_at))).scalars().first()
        if link is None:
            continue
        if len(out) >= MAX_AGENT_MENTIONS:
            raise Conflict("too many secretaries named", code="too_many_agents")
        seen.add(agent.id)
        out.append((agent.name, agent, link.code))
    return out


async def mentioned(db: AsyncSession, body: str, *, by: User, picked: list[str] | None = None) -> list[tuple[str, User]]:
    """The people this text names, and the exact words that name them (plan/42 §11).

    A mention points at a **person**, not at a string. Somebody who has not claimed an
    address can still be named, because the picker hands over who was chosen and this only
    has to find the words that stand for them. Two ways in, and both are checked against
    the body so a name deleted after picking is not a mention any more:

      1. ids the picker sent — labelled by whichever of their address or their name the
         author actually left in the text;
      2. `@address` typed by hand, for anybody who has one.
    """
    from blackmoa.services.people import display_of

    found: list[tuple[str, User]] = []
    seen: set[uuid.UUID] = set()
    text = body or ""

    for raw in (picked or [])[:20]:
        try:
            who = await db.get(User, uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            continue
        if who is None or who.status != "active" or who.id == by.id or who.id in seen:
            continue
        # Longest first: an address and a display name can both be present.
        labels = sorted({x for x in (who.mail_handle, display_of(who), who.display_name, who.nickname) if x},
                        key=len, reverse=True)
        label = next((x for x in labels if f"@{x}" in text), "")
        if label:
            seen.add(who.id)
            found.append((label, who))

    for raw in _MENTION.findall(text)[:20]:
        low = raw.lower()
        who = (await db.execute(select(User).where(func.lower(User.mail_handle.cast(String)) == low,
                                                   User.status == "active"))).scalars().first()
        if who is not None and who.id != by.id and who.id not in seen:
            seen.add(who.id)
            found.append((raw, who))
    return found


def mention_out(label: str, who: User) -> dict[str, Any]:
    return {"id": str(who.id), "label": label, "handle": who.mail_handle or ""}


async def own_images(db: AsyncSession, user: User, ids: list[str]) -> list[str]:
    """Only this author's own uploads, and only images.

    An id in a request is a claim, not a fact: without this a post could carry somebody
    else's private upload by guessing at its id.
    """
    from blackmoa.models import Upload
    out: list[str] = []
    for raw in list(ids)[:MAX_IMAGES]:
        try:
            up = await db.get(Upload, uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            continue
        if up is not None and up.owner_id == user.id and (up.mime or "").startswith("image/"):
            out.append(str(up.id))
    return out


def image_urls(post: BlogPost) -> list[str]:
    """Addresses an <img> tag can fetch.

    A browser sends no Authorization header for an image, so each address carries its own
    short-lived signature naming the post it belongs to. Making the uploads public instead
    would put a friends-only photo one guessed id away from anyone.
    """
    return [f"/api/public/posts/images/{i}?t={sign_state({'post': str(post.id), 'up': i}, ttl_minutes=IMAGE_TTL_MIN)}"
            for i in (post.images or [])]


async def unique_slug(db: AsyncSession, owner_id: uuid.UUID, base: str, *, exclude: uuid.UUID | None = None) -> str:
    slug = base
    for n in range(2, 60):
        stmt = select(func.count()).select_from(BlogPost).where(BlogPost.owner_id == owner_id, BlogPost.slug == slug)
        if exclude is not None:
            stmt = stmt.where(BlogPost.id != exclude)
        if int((await db.execute(stmt)).scalar_one() or 0) == 0:
            return slug
        slug = f"{base}-{n}"
    return f"{base}-{secrets.token_hex(3)}"


def _clean(title: str, body: str, visibility: str, kind: str = "article", has_image: bool = False) -> tuple[str, str, str]:
    """A note is allowed to have no title; an article is not (plan/42 §4).

    Asking somebody typing one line into the box at the top of 소식 to name it first is
    the difference between a feed and a publishing tool, so a note takes its heading from
    its own first line instead.
    """
    title = " ".join((title or "").split())[:MAX_TITLE]
    body = (body or "").replace("\r\n", "\n").strip()[:MAX_NOTE_BODY if kind == "note" else MAX_BODY]
    if not body and not has_image:
        raise ValidationFailed("a post needs something in it", code="empty_body")
    if not title:
        if kind != "note":
            raise ValidationFailed("a post needs a title", code="empty_title")
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        # A photo with no words still needs an address and a heading for the secretary's
        # copy, so it gets the day it was posted rather than nothing.
        title = first[:NOTE_TITLE].rstrip() or datetime.now(UTC).strftime("%Y-%m-%d")
    if visibility not in VISIBILITIES:
        visibility = "public"
    return title, body, visibility


async def create(db: AsyncSession, user: User, *, title: str, body: str, visibility: str = "public",
                 publish: bool = True, kind: str = "article", images: list[str] | None = None,
                 mentions: list[str] | None = None) -> BlogPost:
    kind = kind if kind in KINDS else "article"
    pics = await own_images(db, user, images or [])
    title, body, visibility = _clean(title, body, visibility, kind, has_image=bool(pics))
    named = await mentioned(db, body, by=user, picked=mentions)
    bots = await agents_named(db, body, picked=mentions)
    post = BlogPost(owner_id=user.id, title=title, body=body, visibility=visibility, kind=kind, images=pics,
                    mentions=[mention_out(x, u) for x, u in named]
                             + [{"id": str(a.id), "label": lbl, "handle": "", "agent": True,
                                 "code": code} for lbl, a, code in bots],
                    slug=await unique_slug(db, user.id, slugify(title)),
                    status="published" if publish else "draft",
                    published_at=datetime.now(UTC) if publish else None)
    db.add(post)
    await db.flush()
    await sync_knowledge(db, user, post)
    if post.status == "published":
        await _look_at_photos(db, post)
        await _tell_mentioned(db, post, user, [u for _, u in named])
        await _ask_secretaries(db, post, [a for _, a, _c in bots])
    return post


async def _look_at_photos(db: AsyncSession, post: BlogPost) -> None:
    """사진이 붙은 글은 비서가 한 번 들여다보게 한다 (plan/45 §2).

    처음에는 **글이 한 줄도 없는 글만** 보게 해 두었다. 그건 틀렸다. "오늘 회식" 이라고
    적고 가게 사진을 올린 글에서, 적힌 말과 찍힌 것은 서로 다른 사실이다. 본문이 있다는
    이유로 사진을 건너뛰면 소식의 절반이 비서에게는 여전히 빈 종이다.

    한 글에 한 번뿐이다. 이미 본 글은 다시 보지 않는다.
    """
    from blackmoa.services import jobs as J

    if not (post.images or []) or (post.meta or {}).get("seen"):
        return
    await J.enqueue(db, "post.describe_photos", {"post_id": str(post.id)},
                    dedupe_key=f"seen:{post.id}", priority=5, owner_id=post.owner_id)


async def _ask_secretaries(db: AsyncSession, post: BlogPost, agents: list[Any]) -> None:
    """A named secretary reads the post and answers under it (plan/43 §6).

    Off the request: the answer is a turn of its own, paid for by whoever owns that
    secretary, and the person posting should not wait for it.
    """
    from blackmoa.services import jobs as J
    for agent in agents:
        await J.enqueue(db, "post.secretary_reply", {"post_id": str(post.id), "agent_id": str(agent.id)},
                        priority=4, owner_id=agent.owner_id)


async def _tell_mentioned(db: AsyncSession, post: BlogPost, author: User, people: list[User]) -> None:
    """Being named is worth hearing about, once, from whoever named you."""
    from blackmoa.services import inbox as IB
    for who in people:
        await IB.create(db, owner_id=who.id, agent_id=None, kind="post_mention", payload={
            "post_id": str(post.id), "slug": post.slug, "post_title": post.title,
            "excerpt": (post.body or "")[:160],
            "actor_name": (author.nickname or author.display_name or "").strip(),
            "actor_handle": author.mail_handle or "",
        })


async def get_owned(db: AsyncSession, user: User, post_id: uuid.UUID) -> BlogPost:
    post = await db.get(BlogPost, post_id)
    if post is None or post.owner_id != user.id:
        raise NotFound("post not found", code="post_not_found")
    return post


async def update(db: AsyncSession, user: User, post_id: uuid.UUID, *, title: str | None = None, body: str | None = None,
                 visibility: str | None = None, status: str | None = None,
                 images: list[str] | None = None, mentions: list[str] | None = None) -> BlogPost:
    post = await get_owned(db, user, post_id)
    if images is not None:
        post.images = await own_images(db, user, images)
    new_title, new_body, new_vis = _clean(title if title is not None else post.title,
                                          body if body is not None else post.body,
                                          visibility if visibility is not None else post.visibility,
                                          post.kind, has_image=bool(post.images))
    # The address only follows the title while nobody can have linked to it yet.
    if new_title != post.title and post.status == "draft":
        post.slug = await unique_slug(db, user.id, slugify(new_title), exclude=post.id)
    was = {str(m.get("id")) for m in (post.mentions or []) if isinstance(m, dict)}
    was_published = post.status == "published"
    # An edit that says nothing about who was named keeps the names it already had: a
    # patch that only changes the visibility is not the author deleting their mentions.
    # They are still checked against the new text, so a name taken out of the words stops
    # being a mention either way.
    picked = list(mentions) if mentions is not None else [x for x in was if x]
    named = await mentioned(db, new_body, by=user, picked=picked)
    bots = await agents_named(db, new_body, picked=picked)
    post.mentions = [mention_out(x, u) for x, u in named] + [
        {"id": str(a.id), "label": lbl, "handle": "", "agent": True, "code": code} for lbl, a, code in bots]
    post.title, post.body, post.visibility = new_title, new_body, new_vis
    if status in ("draft", "published") and status != post.status:
        post.status = status
        if status == "published" and post.published_at is None:
            post.published_at = datetime.now(UTC)
    post.updated_at = datetime.now(UTC)
    await db.flush()
    await sync_knowledge(db, user, post)
    # Only somebody newly named hears about it: editing a typo is not a second summons.
    # Putting a draft up is, though, since nobody was told the first time.
    if post.status == "published":
        await _look_at_photos(db, post)

        def fresh(i: str) -> bool:
            return not was_published or i not in was

        await _tell_mentioned(db, post, user, [u for _, u in named if fresh(str(u.id))])
        await _ask_secretaries(db, post, [a for _, a, _c in bots if fresh(str(a.id))])
    return post


async def remove(db: AsyncSession, user: User, post_id: uuid.UUID) -> None:
    post = await get_owned(db, user, post_id)
    await _drop_knowledge(db, user, post)
    await db.delete(post)


def _material(post: BlogPost) -> str:
    """비서가 읽을 이 글의 내용.

    적힌 말이 본문이고, 사진은 비서가 본 것을 한 줄로 붙인다. 사진만 올린 글도 그 날의
    기록이다. 눈이 없다고 없는 일이 되면 소식의 절반이 비서에게는 빈 종이다 (plan/45 §2).
    """
    said = (post.body or "").strip()
    seen = ((post.meta or {}).get("seen") or "").strip()
    if not seen:
        return said
    return f"{said}\n\n[사진] {seen}".strip() if said else f"[사진] {seen}"


async def describe_photos(db: AsyncSession, post_id: uuid.UUID) -> dict[str, Any]:
    """사진에 무엇이 있는지 주인의 비서가 한 줄로 적는다 (plan/45 §2).

    사진을 못 보는 채로 두면 사진만 올린 글은 비서에게 빈 종이다. 그래서 딱 한 번, 첫
    사진 한 장만, 한두 문장으로 적어 둔다. 이건 **재료**이지 기억이 아니다: 무엇을
    기억할지는 나중에 비서가 그 글을 들춰 볼 때 정해진다.
    """
    from blackmoa.models import Agent
    from blackmoa.pipeline.events import journals
    from blackmoa.pipeline.runner import TurnRequest, launch_turn, start_turn
    from blackmoa.services import conversations as CV
    from blackmoa.services import uploads as UP

    post = await db.get(BlogPost, post_id)
    if post is None or post.status != "published" or not (post.images or []):
        return {"skipped": "gone"}
    if (post.meta or {}).get("seen"):
        return {"skipped": "already"}
    owner = await db.get(User, post.owner_id)
    agent = (await db.execute(select(Agent).where(Agent.owner_id == post.owner_id, Agent.status == "active")
                              .order_by(Agent.created_at))).scalars().first()
    if owner is None or agent is None:
        return {"skipped": "no_secretary"}
    # 한 턴에 넉 장까지 함께 본다. 첫 장만 보면 남은 장은 없는 일이 되고, 다 보려고
    # 장마다 턴을 돌리면 글 하나에 크레딧이 네 배로 나간다.
    atts = await UP.attachments_from_ids(db, owner.id, list(post.images or [])[:PHOTOS_PER_POST])
    atts = [a for a in atts if a.get("data")]
    if not atts:
        return {"skipped": "unreadable"}

    many = len(atts) > 1
    asked = ("올린 사진이에요. " + ("사진들에 " if many else "") + "무엇이 찍혔는지 "
             + ("사진마다 한 문장씩" if many else "한두 문장으로만") + " 적어 주세요.\n"
             "보이는 것만 적고, 짐작하거나 평하지 마세요. 인사도 군더더기도 없이 문장만 남기세요.")
    conv = await CV.create(db, owner_id=owner.id, agent_id=agent.id, audience="owner",
                           title="사진 읽기", simulated=True)
    await db.flush()
    # 심부름은 턴도 심부름이다 (plan/50 §2). 대화에만 표시하고 턴에 안 붙이면, 증류가
    # 이 지시문을 "주인이 한 말" 로 읽어 기억으로 남긴다.
    turn = await start_turn(db, TurnRequest(owner=owner, agent=agent, conversation=conv, audience="owner",
                                            text=asked, attachments=atts, simulated=True))
    await db.commit()
    launch_turn(turn)
    j = journals.get(turn.id)
    if j is not None and j.task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(j.task), timeout=REPLY_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError):
            return {"skipped": "slow"}
    seen = ((j.answer if j else "") or "").strip()[:SEEN_MAX]
    if not seen:
        return {"skipped": "empty"}
    post = await db.get(BlogPost, post_id)
    if post is None:
        return {"skipped": "gone"}
    post.meta = {**(post.meta or {}), "seen": seen}
    await sync_knowledge(db, owner, post)
    return {"seen": seen}


async def sync_knowledge(db: AsyncSession, user: User, post: BlogPost) -> None:
    """Keep the secretary's copy in step with the page (plan/45 §2).

    **내 비서는 내가 쓴 글을 전부 알 수 있다.** 공개 범위는 *사람에게 어디까지 보이나* 이지
    *내 비서가 아느냐* 가 아니다. 인맥에게만 쓴 글이 가장 일기다운 글인데, 그것이 비서에게는
    없는 글이던 것이 이 서비스에서 가장 이상한 구멍이었다.

    외부인에게는 **글에 적힌 범위 그대로** 간다 — 사본에 딱지를 옮겨 붙이지 않고, 외부인 대화의
    지식 범위가 원본 글의 범위를 읽는다(services/outsider, plan/57). 피드 글은 프로필 페이지에
    실리는 것이라 [정보] 와 같은 층이어서, 비서의 [지식] 탭 정보 줄이 켜져 있을 때 그 글이 이
    사람에게 보이면 쓴다. 딱지를 사본에 복사하던 때는 둘이 어긋날 수 있었다 (plan/48 §1-2).

    발행되지 않은 글은 아직 글이 아니다. 적힌 말이 없는 글은 비서가 읽을 것이 없다.
    """
    said = bool((post.body or "").strip()) or bool((post.meta or {}).get("seen"))
    wanted = post.status == "published" and said
    if not wanted:
        await _drop_knowledge(db, user, post)
        return
    if post.knowledge_document_id is not None:
        doc = await db.get(K.KnowledgeDocument, post.knowledge_document_id)
        if doc is not None and doc.owner_id == user.id:
            doc.title = post.title[:255]
            body = _material(post)
            doc.meta = {**(doc.meta or {}), "body": body, "blog_post_id": str(post.id)}
            doc.text_preview = body[:2000]
            doc.size_bytes = len(body.encode())
            doc.status = "processing"
            from blackmoa.services import jobs as J
            await J.enqueue(db, "knowledge.index", {"document_id": str(doc.id)}, priority=3, owner_id=user.id)
            return
    doc = await K.create_text(db, user, kind="blog", title=post.title, body=_material(post))
    doc.meta = {**(doc.meta or {}), "blog_post_id": str(post.id)}
    post.knowledge_document_id = doc.id


async def _drop_knowledge(db: AsyncSession, user: User, post: BlogPost) -> None:
    if post.knowledge_document_id is None:
        return
    doc = await db.get(K.KnowledgeDocument, post.knowledge_document_id)
    post.knowledge_document_id = None
    if doc is not None and doc.owner_id == user.id:
        await K.delete_document(db, doc)


# ── reading ─────────────────────────────────────────────────────────
async def are_friends(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    """인맥: both of them connected to the other (plan/43).

    Nobody negotiates this. Two people each choosing the other is already the agreement a
    request and an acceptance were standing in for.
    """
    if a == b:
        return True
    rows = (await db.execute(select(PersonFollow.follower_id).where(
        or_((PersonFollow.follower_id == a) & (PersonFollow.target_id == b),
            (PersonFollow.follower_id == b) & (PersonFollow.target_id == a))))).scalars().all()
    return {a, b} <= set(rows)


async def visible_levels(db: AsyncSession, owner_id: uuid.UUID, viewer: User | None) -> tuple[str, ...]:
    """Which shelves this reader may take from."""
    if viewer is not None and viewer.id == owner_id:
        return VISIBILITIES
    if viewer is not None and await are_friends(db, owner_id, viewer.id):
        return ("public", "friends")
    return ("public",)


async def mine(db: AsyncSession, user: User, *, limit: int = 50) -> list[BlogPost]:
    return list((await db.execute(select(BlogPost).where(BlogPost.owner_id == user.id)
                                  .order_by(BlogPost.updated_at.desc()).limit(limit))).scalars().all())


async def published(db: AsyncSession, owner_id: uuid.UUID, viewer: User | None, *, limit: int = 20) -> list[BlogPost]:
    levels = await visible_levels(db, owner_id, viewer)
    return list((await db.execute(select(BlogPost).where(
        BlogPost.owner_id == owner_id, BlogPost.status == "published", BlogPost.visibility.in_(levels))
        .order_by(BlogPost.published_at.desc()).limit(limit))).scalars().all())


async def by_slug(db: AsyncSession, owner_id: uuid.UUID, slug: str, viewer: User | None) -> BlogPost:
    post = (await db.execute(select(BlogPost).where(BlogPost.owner_id == owner_id, BlogPost.slug == slug))).scalars().first()
    if post is None:
        raise NotFound("post not found", code="post_not_found")
    levels = await visible_levels(db, owner_id, viewer)
    if post.status != "published" or post.visibility not in levels:
        # A post somebody may not read is not announced as existing.
        raise NotFound("post not found", code="post_not_found")
    return post


def out(post: BlogPost, *, full: bool = False, ids: bool = False) -> dict[str, Any]:
    body = post.body or ""
    row: dict[str, Any] = {
        "id": str(post.id), "slug": post.slug, "title": post.title,
        "excerpt": " ".join(body.split())[:160],
        "visibility": post.visibility, "status": post.status, "kind": post.kind,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "updated_at": post.updated_at.isoformat() if post.updated_at else None,
        "view_count": post.view_count,
        "like_count": post.like_count, "comment_count": post.comment_count,
        "images": image_urls(post), "mentions": list(post.mentions or []),
    }
    # A note has no title of its own, so a card that draws one is drawing the first line
    # twice. Whoever renders it gets the body instead (plan/42 §4).
    if post.kind == "note" or full:
        row["body"] = body
    if ids:
        # The signed addresses above are for an <img> tag. Editing the post means handing
        # the same pictures back, and that takes the upload ids. Only the author ever needs
        # them, so only the author is given them.
        row["image_ids"] = [str(i) for i in (post.images or [])]
    return row


async def page_of_mine(db: AsyncSession, user: User, *, page: int = 1, per: int = 10) -> tuple[list[BlogPost], int]:
    """One page of my own writing, newest first, drafts included.

    Paged rather than endless: my blog is a shelf I go back to and look through, not a
    river I scroll. Somebody looking for the thing they wrote in March wants page three.
    """
    total = int((await db.execute(select(func.count()).select_from(BlogPost)
                                  .where(BlogPost.owner_id == user.id))).scalar_one() or 0)
    # In the order the dates on the cards read: when it went up, or when it was started if
    # it never did. Sorting by last-touched put an old post edited this morning above one
    # published yesterday, with the dates on screen saying otherwise.
    when = func.coalesce(BlogPost.published_at, BlogPost.created_at).desc()
    rows = (await db.execute(select(BlogPost).where(BlogPost.owner_id == user.id)
                             .order_by(when)
                             .offset(max(0, (page - 1) * per)).limit(per))).scalars().all()
    return list(rows), total


async def page_of_published(db: AsyncSession, owner_id: uuid.UUID, viewer: User | None, *,
                            page: int = 1, per: int = 12) -> tuple[list[BlogPost], int]:
    """One page of somebody's posts, filtered to what this reader may see."""
    levels = await visible_levels(db, owner_id, viewer)
    where = (BlogPost.owner_id == owner_id, BlogPost.status == "published", BlogPost.visibility.in_(levels))
    total = int((await db.execute(select(func.count()).select_from(BlogPost).where(*where))).scalar_one() or 0)
    rows = (await db.execute(select(BlogPost).where(*where).order_by(BlogPost.published_at.desc())
                             .offset(max(0, (page - 1) * per)).limit(per))).scalars().all()
    return list(rows), total


# ── who reads whom ──────────────────────────────────────────────────

#: 같은 사람에게 이 시간 안에 이만큼 닿았으면, 그 사람에게는 더 보낼 수 없다 (plan/43).
#: 전체 한도가 아니라 상대별이다. 연결을 몇 명과 맺든 그건 그 사람의 사정이고, 문제는
#: 한 사람에게 반복해서 닿는 일이다. 연결할 때마다 그 사람 인박스에 한 줄이 남으므로,
#: 끊었다 잇기를 되풀이하면 그 줄이 계속 쌓인다.
REACH_WINDOW_MIN = 10
REACH_PER_TARGET = 10


async def _reached_too_often(db: AsyncSession, me: User, target_id: uuid.UUID) -> bool:
    """이 상대에게 최근에 몇 번 닿았나.

    인박스에 남은 줄을 센다. 실제로 그 사람에게 간 것만 세어지고, 껐다 켜도 기억이
    사라지지 않는다. 이미 연결된 상대를 다시 눌러도 줄은 생기지 않으니 세지 않는다.
    """
    from blackmoa.models import InboxItem

    since = datetime.now(UTC) - timedelta(minutes=REACH_WINDOW_MIN)
    n = (await db.execute(select(func.count()).select_from(InboxItem).where(
        InboxItem.owner_id == target_id, InboxItem.kind == "person_follow",
        InboxItem.created_at >= since,
        InboxItem.payload["actor_id"].astext == str(me.id)))).scalar_one()
    return int(n or 0) >= REACH_PER_TARGET


async def follow(db: AsyncSession, me: User, target_id: uuid.UUID) -> bool:
    """Connect to somebody. One-sided and immediate: nobody is asked (plan/43).

    This is the whole relationship model. Both people doing it is what 인맥 means, and that
    is derived rather than negotiated — there is no request sitting in a tab.
    """
    if target_id == me.id:
        raise ValidationFailed("you already read yourself", code="follow_self")
    target = await db.get(User, target_id)
    if target is None or target.status != "active":
        raise NotFound("account not found", code="account_not_found")
    if await follows(db, me.id, target_id):
        return False
    if await _reached_too_often(db, me, target_id):
        raise Conflict("이 분에게는 잠시 후에 다시 시도해 주세요.", code="reached_too_often")
    db.add(PersonFollow(follower_id=me.id, target_id=target_id))
    await db.flush()
    from blackmoa.services import people as P
    await P.materialize_connection(db, me, target)
    from blackmoa.services import inbox as I
    mutual = await follows(db, target_id, me.id)
    # Quiet but not silent: somebody choosing to read you is news about you, and it says
    # whether that made the two of you 인맥 so the reply is one tap or none.
    await I.create(db, owner_id=target_id, agent_id=None, kind="person_follow", urgency=1,
                   payload={"actor_name": P.display_of(me), "actor_id": str(me.id),
                            "mutual": mutual, "link_kind": "follow", "text": ""})
    return True


async def unfollow(db: AsyncSession, me: User, target_id: uuid.UUID) -> None:
    row = (await db.execute(select(PersonFollow).where(PersonFollow.follower_id == me.id,
                                                       PersonFollow.target_id == target_id))).scalars().first()
    if row is not None:
        await db.delete(row)
        await db.flush()
    target = await db.get(User, target_id)
    if target is not None:
        from blackmoa.services import people as P
        await P.materialize_connection(db, me, target)


async def follows(db: AsyncSession, follower_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    return (await db.execute(select(PersonFollow.id).where(PersonFollow.follower_id == follower_id,
                                                           PersonFollow.target_id == target_id))).first() is not None


async def follow_counts(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    following = (await db.execute(select(func.count()).select_from(PersonFollow)
                                  .where(PersonFollow.follower_id == user_id))).scalar_one()
    followers = (await db.execute(select(func.count()).select_from(PersonFollow)
                                  .where(PersonFollow.target_id == user_id))).scalar_one()
    return {"following": int(following or 0), "followers": int(followers or 0)}


async def reading_list(db: AsyncSession, me: User) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Whose writing reaches my feed: the people I connected with, and the people I follow."""
    out = set((await db.execute(select(PersonFollow.target_id).where(PersonFollow.follower_id == me.id))).scalars().all())
    back = set((await db.execute(select(PersonFollow.follower_id).where(PersonFollow.target_id == me.id))).scalars().all())
    # 인맥 is the overlap; the rest of what I connected to is somebody I read one way.
    return out & back, out - back


async def feed(db: AsyncSession, me: User, *, limit: int = 30, before: datetime | None = None) -> list[tuple[BlogPost, User]]:
    """Posts from people this person actually knows or chose to read (plan/41 §5).

    A connection's posts for friends are in; a followed stranger's are not, because
    following is not being let in. This is the house lane only; the square arrives
    through `page()` below, kept to a ratio so it cannot bury the people.
    """
    friend_ids, followed = await reading_list(db, me)
    # My own writing belongs in my own feed: a page I never see is a page I stop using.
    friend_ids = set(friend_ids) | {me.id}
    reach = or_(
        (BlogPost.owner_id.in_(friend_ids) & BlogPost.visibility.in_(("public", "friends"))) if friend_ids else false(),
        (BlogPost.owner_id.in_(followed) & (BlogPost.visibility == "public")) if followed else false(),
    )
    # A suspended account goes quiet everywhere. Its page already 404s, so leaving its
    # posts in other people's 소식 would be the one place it still speaks.
    stmt = (select(BlogPost, User).join(User, User.id == BlogPost.owner_id)
            .where(BlogPost.status == "published", User.status == "active", reach)
            .order_by(BlogPost.published_at.desc()).limit(limit))
    if before is not None:
        stmt = stmt.where(BlogPost.published_at < before)
    return [(p, u) for p, u in (await db.execute(stmt)).all()]


# ── reacting and replying (plan/42 §5) ───────────────────────────────
#
# The house keeps its own tables. Sharing the community's would put a pen name and a real
# name in the same rows, which is the one thing plan/41 §1 says cannot happen.


async def readable(db: AsyncSession, me: User, post_id: uuid.UUID) -> BlogPost:
    """The post, if this person is allowed to see it at all.

    The author is allowed their own draft: their blog lists it, so pressing it has to open
    it. For everybody else an unpublished post is not announced as existing.
    """
    post = await db.get(BlogPost, post_id)
    if post is None:
        raise NotFound("post not found", code="post_not_found")
    if post.owner_id == me.id:
        return post
    if post.status != "published" or post.visibility not in await visible_levels(db, post.owner_id, me):
        raise NotFound("post not found", code="post_not_found")
    # A suspended account goes quiet everywhere. 소식 already drops its posts; an address
    # must not be the one place it still speaks.
    author = await db.get(User, post.owner_id)
    if author is None or author.status != "active":
        raise NotFound("post not found", code="post_not_found")
    return post


async def like(db: AsyncSession, me: User, post_id: uuid.UUID, *, on: bool) -> dict[str, Any]:
    post = await readable(db, me, post_id)
    row = (await db.execute(select(PostReaction).where(PostReaction.post_id == post.id,
                                                       PostReaction.user_id == me.id))).scalars().first()
    if on and row is None:
        db.add(PostReaction(post_id=post.id, user_id=me.id))
        post.like_count += 1
    elif not on and row is not None:
        await db.delete(row)
        post.like_count = max(0, post.like_count - 1)
    await db.flush()
    return {"liked": on, "like_count": post.like_count}


async def comment(db: AsyncSession, me: User, post_id: uuid.UUID, *, body: str,
                  parent_id: uuid.UUID | None = None,
                  as_agent: uuid.UUID | None = None) -> PostComment:
    """A reply under a post, or under one of its replies (plan/42 §5).

    `as_agent` signs it with that secretary (plan/43 §6). Answering a reply joins the thread
    it is already in: the parent is always a root comment, so the column never gets a third
    step and a long argument stays readable on a phone.
    """
    post = await readable(db, me, post_id)
    text = (body or "").replace("\r\n", "\n").strip()[:MAX_COMMENT]
    if not text:
        raise ValidationFailed("write something first", code="empty_comment")
    parent: PostComment | None = None
    if parent_id is not None:
        parent = await db.get(PostComment, parent_id)
        if parent is None or parent.post_id != post.id:
            raise NotFound("comment not found", code="comment_not_found")
        # Answering a reply answers the thread, not the reply.
        if parent.parent_id is not None:
            parent = await db.get(PostComment, parent.parent_id)
        if parent is None:
            raise NotFound("comment not found", code="comment_not_found")
    row = PostComment(post_id=post.id, author_id=me.id, agent_id=as_agent, body=text,
                      parent_id=parent.id if parent is not None else None)
    db.add(row)
    post.comment_count += 1
    await db.flush()

    from blackmoa.services import inbox as IB
    from blackmoa.services.people import display_of as _who
    said_by = _who(me)
    if as_agent is not None:
        from blackmoa.models import Agent
        bot = await db.get(Agent, as_agent)
        if bot is not None:
            said_by = bot.name
    told: set[uuid.UUID] = {me.id}
    # No `agent_id` on the card: that field means one of *my* secretaries, and this one
    # belongs to whoever it was named by. The name on the card is enough to say who spoke.
    card = {"post_id": str(post.id), "slug": post.slug, "post_title": post.title,
            "comment_id": str(row.id), "excerpt": text[:160], "actor_name": said_by}
    if parent is not None and parent.author_id not in told:
        # Whoever is being answered hears about it, even on somebody else's post.
        told.add(parent.author_id)
        await IB.create(db, owner_id=parent.author_id, agent_id=None, kind="post_reply", payload=card)
    if post.owner_id not in told:
        await IB.create(db, owner_id=post.owner_id, agent_id=None, kind="post_comment", payload=card)
    return row


async def comments(db: AsyncSession, me: User, post_id: uuid.UUID, *,
                   limit: int = 200) -> list[tuple[PostComment, User, Any]]:
    """The whole conversation under a post, oldest first, replies included.

    Flat on purpose: each row says which comment it answers and whoever draws it decides how
    to indent. One query keeps a thread from arriving in pieces.

    Past the cap it is the **newest** that are kept. A thread that outgrows the window
    should lose its beginning, not its present: the other way round the author's own reply
    from a minute ago is the thing that disappears.
    """
    from blackmoa.models import Agent

    post = await readable(db, me, post_id)
    rows = list(reversed((await db.execute(
        select(PostComment, User).join(User, User.id == PostComment.author_id)
        .where(PostComment.post_id == post.id)
        .order_by(PostComment.created_at.desc()).limit(limit))).all()))
    ids = {c.agent_id for c, _ in rows if c.agent_id}
    bots = {}
    if ids:
        bots = {a.id: a for a in (await db.execute(select(Agent).where(Agent.id.in_(ids)))).scalars().all()}
    return [(c, u, bots.get(c.agent_id) if c.agent_id else None) for c, u in rows]


async def remove_comment(db: AsyncSession, me: User, comment_id: uuid.UUID) -> int:
    """Your own comment, or any comment under your own post.

    Removing something that was answered takes the answers with it: a reply with nothing
    above it is a sentence addressed to a hole. Returns how many rows went.
    """
    row = await db.get(PostComment, comment_id)
    if row is None:
        raise NotFound("comment not found", code="comment_not_found")
    post = await db.get(BlogPost, row.post_id)
    if row.author_id != me.id and (post is None or post.owner_id != me.id):
        raise NotFound("comment not found", code="comment_not_found")
    gone = 1
    if row.parent_id is None:
        kids = (await db.execute(select(PostComment).where(PostComment.parent_id == row.id))).scalars().all()
        for k in kids:
            await db.delete(k)
        gone += len(kids)
    if post is not None:
        post.comment_count = max(0, post.comment_count - gone)
    await db.delete(row)
    return gone


async def liked_ids(db: AsyncSession, me: User, post_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not post_ids:
        return set()
    rows = (await db.execute(select(PostReaction.post_id).where(PostReaction.user_id == me.id,
                                                                PostReaction.post_id.in_(post_ids)))).scalars().all()
    return set(rows)


# ── a secretary answering a post it was named in (plan/43 §6) ────────

#: Enough of the post for an answer to be about it, and not so much that a long article
#: turns one caption into a document.
REPLY_BODY = 4000
#: Long enough for a real answer, short enough that a stuck provider is not a stuck job.
REPLY_TIMEOUT_S = 120


async def secretary_reply(db: AsyncSession, post_id: uuid.UUID, agent_id: uuid.UUID) -> dict[str, Any]:
    """Read the post, say something under it, as that secretary.

    Runs where turns run. The turn is the owner's, because somebody pays for it and their
    secretary keeps the conversation. The comment is the secretary's: its name and face are
    on it, and the owner is only who may take it down.
    """
    from blackmoa.models import Agent
    from blackmoa.pipeline.events import journals
    from blackmoa.pipeline.runner import TurnRequest, launch_turn, start_turn
    from blackmoa.services import conversations as CV

    post = await db.get(BlogPost, post_id)
    agent = await db.get(Agent, agent_id)
    if post is None or agent is None or agent.status != "active" or post.status != "published":
        return {"skipped": "gone"}
    owner = await db.get(User, agent.owner_id)
    author = await db.get(User, post.owner_id)
    if owner is None or author is None:
        return {"skipped": "gone"}
    # A secretary answers a post once. A job that is retried after the answer was already
    # written would otherwise put the same secretary under the post twice.
    if (await db.execute(select(PostComment.id).where(PostComment.post_id == post.id,
                                                      PostComment.agent_id == agent.id))).first():
        return {"skipped": "answered"}
    if post.visibility not in await visible_levels(db, post.owner_id, owner):
        return {"skipped": "not_readable"}

    from blackmoa.services import people as P

    # What the post actually is, said plainly. A secretary handed an empty block answers
    # that the post is empty, and a photo with three words under it is exactly that: the
    # whole post. It cannot see the picture, so it is told there is one instead of
    # concluding there is nothing.
    shot = len(post.images or [])
    what = f"사진 {shot}장" if shot else ""
    body = (post.body or "").strip()
    asked = (
        f"{P.display_of(author)}님이 올린 글에서 나를 불렀어요. 댓글로 한두 문장 답해 주세요.\n"
        f"짧은 소식 글이에요. {what + '에 ' if what else ''}적힌 말이 전부이고, 그게 정상이에요.\n"
        f"글이 짧다고 지적하거나 내용을 더 달라고 되묻지 마세요. 있는 것만 보고 답하세요.\n"
        f"인사나 군더더기 없이, 도움이 되는 말 한두 문장만 남기세요.\n\n"
        f"--- 글 ---\n"
        + (f"[{what}]\n" if what else "")
        + f"{body[:REPLY_BODY] if body else '(적힌 말 없이 사진만 올렸어요)'}\n--- 끝 ---"
    )
    conv = await CV.create(db, owner_id=owner.id, agent_id=agent.id, audience="owner",
                           title=f"{P.display_of(author)}님의 글", simulated=True)
    await db.flush()
    # 심부름은 턴도 심부름이다 (plan/50 §2).
    turn = await start_turn(db, TurnRequest(owner=owner, agent=agent, conversation=conv,
                                            audience="owner", text=asked, simulated=True))
    await db.commit()
    launch_turn(turn)
    j = journals.get(turn.id)
    if j is not None and j.task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(j.task), timeout=REPLY_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError):
            return {"skipped": "slow"}
    said = ((j.answer if j else "") or "").strip()
    if not said:
        return {"skipped": "no_answer"}
    await comment(db, owner, post.id, body=said[:MAX_COMMENT], as_agent=agent.id)
    return {"commented": True}
