"""[파일] 과 [저장 공간] (plan/55 §4·§6-2).

목록은 서명한 주소를 내려 준다 — 화면이 주소를 만들지 않는다. 바이트는 ``/api/uploads/
{id}/raw`` 가, 작은 그림은 여기의 ``/thumb`` 가 낸다.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response
from sqlalchemy import func, or_, select

from memora.core.deps import DB, CurrentUser
from memora.core.errors import NotFound
from memora.core.security import verify_state
from memora.models import Agent, AgentFile, AgentFileChunk, KnowledgeDocument
from memora.services import files as FILES
from memora.services import objectstore

router = APIRouter(prefix="/api", tags=["files"])


def _tz(user) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(user, "timezone", None) or "Asia/Seoul")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


@router.get("/files")
async def list_files(user: CurrentUser, db: DB, agent_id: uuid.UUID | None = None, since: date | None = None,
                     until: date | None = None, source: str | None = None, kind: str | None = None, q: str = "",
                     sort: str = "recent", limit: int = 60, offset: int = 0):
    """거르기 한 줄: 기간 · 출처 · 종류 · 검색. ``sort=size`` 는 [여유 공간 확보] 가 쓴다."""
    tz = _tz(user)
    conds = [AgentFile.owner_id == user.id, AgentFile.deleted_at.is_(None)]
    if agent_id:
        conds.append(AgentFile.agent_id == agent_id)
    if since:
        conds.append(AgentFile.created_at >= datetime.combine(since, time.min, tz))
    if until:
        conds.append(AgentFile.created_at < datetime.combine(until + timedelta(days=1), time.min, tz))
    if source in ("owner", "visitor"):
        conds.append(AgentFile.scope == source)
    elif source in FILES.SOURCES:
        conds.append(AgentFile.source == source)
    if kind in FILES.KINDS:
        conds.append(AgentFile.kind == kind)
    if q.strip():
        like = f"%{q.strip()[:100]}%"
        # 본문 어디에 있어도 찾는다 (P4) — 앞 2,000자 밖의 말도.
        inside = select(AgentFileChunk.file_id).where(AgentFileChunk.owner_id == user.id, AgentFileChunk.text.ilike(like))
        conds.append(or_(AgentFile.filename.ilike(like), AgentFile.caption.ilike(like), AgentFile.preview.ilike(like),
                         AgentFile.id.in_(inside)))
    order = [AgentFile.size_bytes.desc(), AgentFile.created_at.desc()] if sort == "size" else [AgentFile.created_at.desc(), AgentFile.id.desc()]
    rows = (await db.execute(select(AgentFile).where(*conds).order_by(*order)
                             .limit(max(1, min(limit, 200))).offset(max(0, offset)))).scalars().all()
    total, total_bytes, unreadable = (await db.execute(select(
        func.count(), func.coalesce(func.sum(AgentFile.size_bytes), 0),
        func.count().filter(AgentFile.status == "unreadable")).where(*conds))).one()
    names = {a.id: a.name for a in (await db.execute(select(Agent).where(Agent.owner_id == user.id))).scalars().all()}
    return {"items": [FILES.out(f, agent_name=names.get(f.agent_id, "")) for f in rows], "total": int(total),
            "total_bytes": int(total_bytes), "unreadable": int(unreadable)}


@router.get("/files/{file_id}")
async def get_file(file_id: uuid.UUID, user: CurrentUser, db: DB):
    f = await FILES.get_owned(db, user.id, file_id)
    a = await db.get(Agent, f.agent_id) if f.agent_id else None
    out = FILES.out(f, agent_name=a.name if a else "")
    out["preview"] = (f.preview or "")[:FILES.PREVIEW_CHARS]
    out["error"] = f.error
    # 이미 지식에 올린 파일인가 — 같은 바이트의 지식 문서가 있으면 그렇다.
    kd = (await db.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.owner_id == user.id,
                                                              KnowledgeDocument.sha256 == f.sha256).limit(1))).scalar()
    out["knowledge_document_id"] = str(kd) if kd else None
    out["can_promote"] = FILES.can_promote(f)
    return out


@router.post("/files/{file_id}/to-knowledge", status_code=201)
async def to_knowledge(file_id: uuid.UUID, user: CurrentUser, db: DB):
    """[지식으로 올리기] (P4): 이 파일의 사본을 지식 저장소에. 지식은 모든 비서가 본다."""
    f = await FILES.get_owned(db, user.id, file_id)
    doc = await FILES.promote(db, user, f)
    await db.commit()
    return {"document_id": str(doc.id), "title": doc.title}


@router.get("/files/{file_id}/text")
async def file_text(file_id: uuid.UUID, user: CurrentUser, db: DB, offset: int = 0, limit: int = 20000):
    f = await FILES.get_owned(db, user.id, file_id)
    return await FILES.read_text(f, offset=offset, limit=limit)


@router.get("/files/{file_id}/thumb")
async def file_thumb(file_id: uuid.UUID, db: DB, t: str = ""):
    """목록·말풍선의 작은 그림. ``<img>`` 가 여는 길이라 서명으로 연다."""
    try:
        claim = verify_state(t)
    except Exception as e:  # noqa: BLE001
        raise NotFound("file not found") from e
    if claim.get("file") != str(file_id):
        raise NotFound("file not found")
    f = await db.get(AgentFile, file_id)
    if f is None or f.deleted_at is not None or not f.thumb_path:
        raise NotFound("file not found")
    return Response(await objectstore.get(f.thumb_path), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(file_id: uuid.UUID, user: CurrentUser, db: DB):
    f = await FILES.get_owned(db, user.id, file_id)
    await FILES.delete(db, f)
    await db.commit()
    return Response(status_code=204)


@router.post("/files/{file_id}/restore")
async def restore_file(file_id: uuid.UUID, user: CurrentUser, db: DB):
    """지운 지 30일이 안 된 파일을 되살린다 (plan/78)."""
    f = await FILES.get_owned(db, user.id, file_id, include_deleted=True)
    f = await FILES.restore(db, user, f)
    await db.commit()
    a = await db.get(Agent, f.agent_id) if f.agent_id else None
    return FILES.out(f, agent_name=a.name if a else "")


@router.get("/storage")
async def storage(user: CurrentUser, db: DB):
    return await FILES.usage(db, user)


@router.get("/cloud")
async def cloud(user: CurrentUser, db: DB):
    """[관리·설정 → 클라우드 관리] 한 장 (plan/78)."""
    from memora.services import gdrive as GD
    out = await FILES.cloud(db, user)
    out["drive"] = await GD.status(db, user.id)
    return out
