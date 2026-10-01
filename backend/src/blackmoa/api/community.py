"""Community API. Reading needs an account; writing is limited to your own posts."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import NotFound, ValidationFailed
from blackmoa.core.ratelimit import limiter
from blackmoa.core.security import sign_state, verify_state
from blackmoa.data.jobs_taxonomy import EMPLOYMENT_TYPES, INDUSTRIES, JOB_FAMILIES, JOB_NAME
from blackmoa.data.regions import REGIONS
from blackmoa.models import CommunityComment, CommunityJob, CommunityPost, User
from blackmoa.services import community as C
from blackmoa.services import settings as S
from blackmoa.services.companies import switch as CO

router = APIRouter(prefix="/api/community", tags=["community"])


def _board_out(b, activity: dict | None = None) -> dict:
    a = (activity or {}).get(str(b.id), {})
    return {"id": str(b.id), "slug": b.slug, "name": b.name, "description": b.description,
            "kind": b.kind, "icon": b.icon, "post_count": b.post_count,
            "write_policy": getattr(b, "write_policy", "all"),
            # What the board header says instead of a tagline: how busy this place is.
            "people_count": a.get("people", 0), "last_post_at": a.get("last_post_at")}


def _author_out(a) -> dict | None:
    if a is None:
        return None
    return {"id": a.id, "name": a.name, "job": a.job, "avatar_url": a.avatar_url, "is_me": a.is_me}


def _square_out(a, *, fallback: str = "") -> dict | None:
    """광장에 서는 글쓴이 (plan/51·52).

    이름은 **그 사람이 지금 쓰는 이름**이고, 계정 id 도 얼굴도 직함도 나가지 않는다.
    `is_me` 만 남긴다: 내 글을 고치고 지우는 것은 내 일이고, 그 값은 나 자신에게만
    참이라 남에게 무엇도 알려 주지 않는다.

    계정이 사라진 글은 그때 적어 둔 이름으로 선다.
    """
    if a is None:
        return {"id": "", "name": fallback or "익명", "job": "", "avatar_url": None,
                "is_me": False, "pen_name": True} if fallback else None
    return {"id": "", "name": getattr(a, "square", "") or fallback or a.name, "job": "",
            "avatar_url": None, "is_me": a.is_me, "pen_name": True}


def _post_out(p, *, board, author, liked: bool, body: bool = False) -> dict:
    shown = _square_out(author, fallback=((p.meta or {}).get("author_name") or "").strip())
    out = {"id": str(p.id), "title": p.title,
           "board": {"slug": board.slug, "name": board.name, "icon": board.icon} if board else None,
           "author": shown,
           "comment_count": p.comment_count, "like_count": p.like_count, "view_count": p.view_count,
           "liked": liked, "created_at": p.created_at.isoformat(),
           "edited_at": p.edited_at.isoformat() if p.edited_at else None, "version": p.version}
    out["body" if body else "excerpt"] = p.body if body else p.body[:160]
    # A browser fetches <img src> with no Authorization header, so an authenticated route
    # is a broken image every time. Each URL carries its own short-lived signature instead —
    # unguessable, expiring, and bound to this post.
    out["images"] = [f"/api/community/images/{i}?t={sign_state({'post': str(p.id), 'up': i}, ttl_minutes=720)}"
                     for i in ((p.meta or {}).get("images") or [])]
    return out


# ── request budgets (plan/32 §7) ─────────────────────────────────────
#
# The last layer of the allocation: a scraper must not be able to take the backend's
# request throughput from everyone else. The numbers come from the traffic record rather
# than from taste — over a day the busiest real caller averaged well under one request a
# minute, so these leave roughly two orders of magnitude of headroom and will only ever be
# met by something that is not a person reading a board.
#
# Per account, not per IP: community is signed-in only, and an account is the thing being
# fair between. Reads and writes are separate budgets because they cost differently and
# abusing them looks different.
READS_PER_MIN = 120
WRITES_PER_MIN = 10


def _budget(user: User, what: str, limit: int) -> None:
    limiter.check(f"comm:{what}:{user.id}", limit, 60)


def _read_budget(user: User) -> None:
    _budget(user, "read", READS_PER_MIN)


def _write_budget(user: User) -> None:
    _budget(user, "write", WRITES_PER_MIN)


@router.get("/boards")
async def list_boards(user: CurrentUser, db: DB, kind: str | None = None):
    _read_budget(user)
    activity = await C.board_activity(db)
    return {"items": [_board_out(b, activity) for b in await C.boards(db, kind=kind)]}


@router.get("/me")
async def community_me(user: CurrentUser, db: DB):
    """What the feed needs to know about the reader: whether they are recognisable yet, and
    which boards their own profile points at."""
    can_write = user.role == "admin" or user.email_verified_at is not None \
        or not await S.get(db, "community.require_verified_email")
    return {"readiness": await C.profile_readiness(db, user),
            "suggested_boards": await C.suggested_boards(db, user), "can_write": can_write}


@router.get("/posts")
async def list_posts(user: CurrentUser, db: DB, board: str | None = None, sort: str = "new",
                     limit: int = 20, cursor: str | None = None, mine: bool = False, q: str | None = None,
                     author: uuid.UUID | None = None):
    _read_budget(user)
    # `author` is what a person's profile page asks for. Only published posts come back,
    # and a post signed with a pen name is not among them unless the asker is its author:
    # answering "what has this person written" with a name they chose to hide behind would
    # undo the hiding (plan/41 §1).
    if sort == "for_me" and not board and not mine and not q and author is None:
        rows, nxt = await C.feed_for_me(db, user, limit=min(limit, 50)), None
    else:
        b = await C.board_by_slug(db, board) if board else None
        who = user.id if mine else author
        rows, nxt = await C.list_posts(db, board=b, sort=sort, limit=min(limit, 50), cursor=cursor,
                                       author_id=who, q=q, include_pen=who is not None and who == user.id)
    boards = {x.id: x for x in await C.boards(db)}
    authors = await C.authors_for(db, {p.author_id for p in rows}, me=user.id)
    liked = await C.liked_ids(db, target_type="post", ids=[p.id for p in rows], user_id=user.id)
    return {"items": [_post_out(p, board=boards.get(p.board_id), author=authors.get(p.author_id),
                                liked=p.id in liked) for p in rows], "next_cursor": nxt}


class PostIn(BaseModel):
    board: str
    title: str = Field(max_length=C.MAX_TITLE)
    body: str = Field(max_length=C.MAX_BODY)
    client_token: str | None = Field(default=None, max_length=64)
    images: list[str] = Field(default_factory=list, max_length=C.MAX_IMAGES)


@router.post("/posts", status_code=201)
async def create_post(body: PostIn, user: CurrentUser, db: DB):
    _write_budget(user)
    p = await C.create_post(db, author=user, board_slug=body.board, title=body.title, body=body.body,
                            client_token=body.client_token, images=body.images)
    await db.commit()
    return {"id": str(p.id)}


@router.get("/posts/{post_id}")
async def read_post(post_id: uuid.UUID, user: CurrentUser, db: DB):
    _read_budget(user)
    p = await C.get_post(db, post_id)
    await C.register_view(db, p, str(user.id))
    boards = {x.id: x for x in await C.boards(db)}
    authors = await C.authors_for(db, {p.author_id}, me=user.id)
    liked = await C.liked_ids(db, target_type="post", ids=[p.id], user_id=user.id)
    await db.commit()
    return _post_out(p, board=boards.get(p.board_id), author=authors.get(p.author_id), liked=p.id in liked, body=True)


class PostPatch(BaseModel):
    title: str | None = Field(default=None, max_length=C.MAX_TITLE)
    body: str | None = Field(default=None, max_length=C.MAX_BODY)
    version: int | None = None
    images: list[str] | None = None


@router.patch("/posts/{post_id}")
async def edit_post(post_id: uuid.UUID, body: PostPatch, user: CurrentUser, db: DB):
    _write_budget(user)
    p = await C.get_post(db, post_id)
    await C.update_post(db, post=p, user=user, title=body.title, body=body.body, version=body.version,
                        images=body.images)
    await db.commit()
    return {"id": str(p.id), "version": p.version}


@router.delete("/posts/{post_id}")
async def remove_post(post_id: uuid.UUID, user: CurrentUser, db: DB):
    _write_budget(user)
    p = await C.get_post(db, post_id)
    await C.delete_post(db, post=p, user=user)
    await db.commit()
    return {"ok": True}


@router.get("/images/{upload_id}")
async def post_image(upload_id: uuid.UUID, db: DB, t: str = ""):
    """Serve an image a published post points at.

    Signed rather than session-authenticated: an <img> tag cannot send a bearer token, and
    the alternative — making every upload public — would expose private files. The
    signature names the post it was issued for and expires on its own.
    """
    from fastapi.responses import Response

    from blackmoa.models import Upload
    from blackmoa.services import objectstore
    try:
        claim = verify_state(t)
    except Exception as e:  # noqa: BLE001
        raise NotFound("image not found", code="image_not_found") from e
    if claim.get("up") != str(upload_id):
        raise NotFound("image not found", code="image_not_found")
    p = await C.get_post(db, uuid.UUID(str(claim.get("post"))))
    if str(upload_id) not in ((p.meta or {}).get("images") or []):
        raise NotFound("image not found", code="image_not_found")
    up = await db.get(Upload, upload_id)
    if up is None:
        raise NotFound("image not found", code="image_not_found")
    return Response(await objectstore.get(up.storage_path), media_type=up.mime,
                    headers={"Cache-Control": "private, max-age=3600"})


def _comment_out(c, author, liked: bool) -> dict:
    """광장의 댓글. **쓴 사람이 누구든 익명이다** (plan/51).

    예전에는 글쓴이만 제 이름을 지켰고 나머지는 실명으로 나왔다. 익명 게시판에서
    그건 가장 큰 구멍이다: 남의 글에 댓글 한 줄만 달면 내 실명이 광장에 걸린다.
    """
    shown = _square_out(author)
    return {"id": str(c.id), "parent_id": str(c.parent_id) if c.parent_id else None, "depth": c.depth,
            "body": "" if c.status == "deleted" else c.body, "deleted": c.status == "deleted",
            "like_count": c.like_count, "liked": liked, "created_at": c.created_at.isoformat(),
            "author": shown}


@router.get("/posts/{post_id}/comments")
async def list_comments(post_id: uuid.UUID, user: CurrentUser, db: DB, sort: str = "new"):
    _read_budget(user)
    p = await C.get_post(db, post_id)
    rows = await C.comments_for(db, p, sort=sort)
    authors = await C.authors_for(db, {c.author_id for c in rows}, me=user.id)
    liked = await C.liked_ids(db, target_type="comment", ids=[c.id for c in rows], user_id=user.id)
    return {"items": [_comment_out(c, authors.get(c.author_id), c.id in liked)
                      for c in rows]}


class CommentIn(BaseModel):
    body: str = Field(max_length=C.MAX_COMMENT)
    parent_id: uuid.UUID | None = None


@router.post("/posts/{post_id}/comments", status_code=201)
async def create_comment(post_id: uuid.UUID, body: CommentIn, user: CurrentUser, db: DB):
    _write_budget(user)
    p = await C.get_post(db, post_id)
    c = await C.add_comment(db, post=p, author=user, body=body.body, parent_id=body.parent_id)
    await db.commit()
    return {"id": str(c.id)}


class CommentPatch(BaseModel):
    body: str = Field(max_length=C.MAX_COMMENT)


@router.patch("/comments/{comment_id}")
async def edit_comment(comment_id: uuid.UUID, body: CommentPatch, user: CurrentUser, db: DB):
    _write_budget(user)
    c = await db.get(CommunityComment, comment_id)
    if c is None or c.status == "deleted":
        raise NotFound("comment not found", code="comment_not_found")
    await C.edit_comment(db, comment=c, user=user, body=body.body)
    await db.commit()
    return {"ok": True}


@router.delete("/comments/{comment_id}")
async def remove_comment(comment_id: uuid.UUID, user: CurrentUser, db: DB):
    _write_budget(user)
    c = await db.get(CommunityComment, comment_id)
    if c is None:
        raise NotFound("comment not found", code="comment_not_found")
    await C.delete_comment(db, comment=c, user=user)
    await db.commit()
    return {"ok": True}


@router.post("/{target_type}/{target_id}/like")
async def like(target_type: str, target_id: uuid.UUID, user: CurrentUser, db: DB):
    _write_budget(user)
    if target_type not in ("posts", "comments"):
        raise ValidationFailed("bad target", code="bad_target")
    kind = "post" if target_type == "posts" else "comment"
    model = CommunityPost if kind == "post" else CommunityComment
    row = await db.get(model, target_id)
    if row is None:
        raise NotFound("not found", code="not_found")
    liked, _ = await C.toggle_like(db, target_type=kind, target_id=target_id, user=user)
    await db.commit()
    await db.refresh(row)
    return {"liked": liked, "like_count": row.like_count}


class ReportIn(BaseModel):
    reason: str = Field(max_length=40)
    detail: str = Field(default="", max_length=2000)


@router.post("/{target_type}/{target_id}/report", status_code=201)
async def report_target(target_type: str, target_id: uuid.UUID, body: ReportIn, user: CurrentUser, db: DB):
    _write_budget(user)
    if target_type not in ("posts", "comments"):
        raise ValidationFailed("bad target", code="bad_target")
    await C.report(db, target_type="post" if target_type == "posts" else "comment",
                   target_id=target_id, user=user, reason=body.reason, detail=body.detail)
    await db.commit()
    return {"ok": True}


# ── jobs ────────────────────────────────────────────────────────────
def _job_out(j, *, mine: bool) -> dict:
    return {"id": str(j.id), "title": j.title, "company": j.company, "location": j.location,
            "employment_type": j.employment_type, "experience_min": j.experience_min,
            "salary_min": j.salary_min, "salary_max": j.salary_max, "tags": j.tags or [],
            "region_codes": j.region_codes or [], "job_codes": j.job_codes or [],
            "industry_codes": j.industry_codes or [], "remote": bool(j.remote),
            "job_labels": [JOB_NAME.get(c, c) for c in (j.job_codes or [])],
            "description": j.description, "apply_url": j.apply_url, "status": j.status,
            "created_at": j.created_at.isoformat(), "is_mine": mine,
            # The real company, when the posting is linked to one (plan/33 §5). The
            # free-text `company` above stays whatever the poster typed.
            "company_info": _company_brief(getattr(j, "company_obj", None))}


def _company_brief(c) -> dict | None:
    """What a reader wants to know about the employer without leaving the posting."""
    if c is None or c.hidden:
        return None
    return {"id": str(c.id), "name": c.name, "market": c.market, "stock_code": c.stock_code,
            "industry_text": c.industry_text, "region_text": c.region_text,
            "homepage": c.homepage, "ceo": c.ceo, "status": c.status,
            "employees": c.employees, "rating": round(c.rating or 0, 1), "review_count": c.review_count,
            "listed_on": c.listed_on.isoformat() if c.listed_on else None}


# 채용공고는 기업정보와 함께 켜지고 꺼진다 (plan/71). 분류표(/jobs/taxonomy)는 프로필도 쓰므로 열어 둔다.
JOBS_GATE = [Depends(CO.gate)]


@router.get("/jobs", dependencies=JOBS_GATE)
async def list_jobs(user: CurrentUser, db: DB, q: str | None = None, region: str | None = None,
                    job: str | None = None, industry: str | None = None, employment_type: str | None = None,
                    max_experience: int | None = None, min_salary: int | None = None,
                    max_salary: int | None = None, remote: bool = False, tag: str | None = None,
                    limit: int = 30):
    _read_budget(user)
    """A filter panel sends several values per dimension, comma-joined."""
    def split(v: str | None) -> list[str]:
        return [x.strip() for x in (v or "").split(",") if x.strip()]

    rows = await C.list_jobs(db, q=q, regions=split(region), jobs=split(job), industries=split(industry),
                             employment_types=split(employment_type), max_experience=max_experience,
                             min_salary=min_salary, max_salary=max_salary, remote_only=remote,
                             tags=split(tag), limit=limit)
    return {"items": [_job_out(j, mine=j.posted_by == user.id) for j in rows]}


# The company directory and its reviews live in blackmoa.api.companies (plan/33 §5, plan/40).


@router.get("/jobs/taxonomy")
async def job_taxonomy(user: CurrentUser):
    """The one source both the filter panel and the posting form read.

    Shipped whole rather than searched over the wire: it is a few tens of kilobytes that
    never changes between deploys, and a picker that waits on the network to open a
    second column is worse than one that does not.
    """
    return {"regions": REGIONS, "jobs": JOB_FAMILIES, "industries": INDUSTRIES,
            "employment_types": EMPLOYMENT_TYPES}


@router.get("/jobs/facets", dependencies=JOBS_GATE)
async def job_facets(user: CurrentUser, db: DB):
    """How many open postings each code would leave — counted up the tree, so a province
    reports what its districts hold."""
    return await C.job_facets(db)


class JobIn(BaseModel):
    title: str = Field(max_length=160)
    company: str = Field(max_length=120)
    location: str = Field(default="", max_length=120)
    region_codes: list[str] = Field(default_factory=list)
    job_codes: list[str] = Field(default_factory=list)
    industry_codes: list[str] = Field(default_factory=list)
    remote: bool = False
    employment_type: str = Field(default="fulltime", max_length=24)
    experience_min: int = 0
    salary_min: int | None = None
    salary_max: int | None = None
    tags: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=C.MAX_BODY)
    apply_url: str = Field(default="", max_length=2000)
    # Optional: the poster picked a real company from name completion. Unverified input,
    # so the service checks it exists and is visible before linking.
    company_id: uuid.UUID | None = None


@router.post("/jobs", status_code=201, dependencies=JOBS_GATE)
async def create_job(body: JobIn, user: CurrentUser, db: DB):
    j = await C.create_job(db, user=user, data=body.model_dump())
    await db.commit()
    return {"id": str(j.id)}


@router.post("/jobs/{job_id}/close", dependencies=JOBS_GATE)
async def close_job(job_id: uuid.UUID, user: CurrentUser, db: DB):
    j = await db.get(CommunityJob, job_id)
    if j is None:
        raise NotFound("job not found", code="job_not_found")
    await C.close_job(db, job=j, user=user)
    await db.commit()
    return {"ok": True}
