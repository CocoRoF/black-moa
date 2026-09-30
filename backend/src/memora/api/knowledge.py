from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from memora.core.deps import DB, CurrentUser
from memora.core.errors import NotFound
from memora.models import KnowledgeChunk, KnowledgeDocument, KnowledgeFaq
from memora.providers.embedding import embedding_available
from memora.services import files as FILES
from memora.services import jobs as J
from memora.services import knowledge as K
from memora.services import plans as P
from memora.services import uploads as U

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def doc_out(d) -> dict:
    return {"id": str(d.id), "kind": d.kind, "title": d.title, "filename": d.filename,
            "mime": d.mime, "size_bytes": d.size_bytes, "source_url": d.source_url, "status": d.status, "error": d.error,
            "chunk_count": d.chunk_count, "embedding_model": d.embedding_model,
            "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat() if d.updated_at else None}


@router.get("/documents")
async def list_docs(user: CurrentUser, db: DB, kind: str | None = None, status: str | None = None):
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.owner_id == user.id).order_by(KnowledgeDocument.created_at.desc())
    if kind:
        stmt = stmt.where(KnowledgeDocument.kind == kind)
    if status:
        stmt = stmt.where(KnowledgeDocument.status == status)
    rows = (await db.execute(stmt.limit(500))).scalars().all()
    plan = await P.plan_for_user(db, user)
    return {"semantic_search": await embedding_available(db), "items": [doc_out(d) for d in rows], "usage_bytes": await FILES.used_bytes(db, user.id), "max_mb": plan.max_storage_mb}



@router.post("/documents", status_code=202)
async def create_doc(user: CurrentUser, db: DB, file: UploadFile | None = File(None), kind: str = Form("file"), title: str = Form(""),
                     body: str = Form(""), url: str = Form("")):
    if kind == "file":
        if file is None:
            from memora.core.errors import ValidationFailed
            raise ValidationFailed("file required")
        data = await U.read_capped(file, U.DOC_MAX)
        d = await K.create_file(db, user, filename=file.filename or "file", mime=file.content_type or "", data=data, title=title or None)
    else:
        d = await K.create_text(db, user, kind=kind, title=title, body=body, url=url or None)
    await db.commit()
    return doc_out(d)


@router.get("/documents/{doc_id}")
async def get_doc(doc_id: uuid.UUID, user: CurrentUser, db: DB):
    d = await K.get_owned(db, user.id, doc_id)
    return {**doc_out(d), "text_preview": d.text_preview}


class DocPatch(BaseModel):
    title: str | None = None


@router.patch("/documents/{doc_id}")
async def patch_doc(doc_id: uuid.UUID, body: DocPatch, user: CurrentUser, db: DB):
    d = await K.get_owned(db, user.id, doc_id)
    if body.title:
        d.title = body.title[:255]
    await db.commit()
    return doc_out(d)


@router.delete("/documents/{doc_id}")
async def delete_doc(doc_id: uuid.UUID, user: CurrentUser, db: DB):
    d = await K.get_owned(db, user.id, doc_id)
    await K.delete_document(db, d)
    await db.commit()
    return {"ok": True}


@router.get("/documents/{doc_id}/chunks")
async def chunks(doc_id: uuid.UUID, user: CurrentUser, db: DB, offset: int = 0, limit: int = 50):
    d = await K.get_owned(db, user.id, doc_id)
    rows = (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == d.id).order_by(KnowledgeChunk.ordinal).offset(offset).limit(limit))).scalars().all()
    return {"items": [{"ordinal": c.ordinal, "heading": c.heading, "page": c.page, "tokens": c.tokens, "text": c.text} for c in rows], "total": d.chunk_count}


@router.post("/documents/{doc_id}/reindex", status_code=202)
async def reindex(doc_id: uuid.UUID, user: CurrentUser, db: DB):
    d = await K.get_owned(db, user.id, doc_id)
    d.status = "processing"
    await J.enqueue(db, "knowledge.index", {"document_id": str(d.id)}, priority=3, owner_id=user.id)
    await db.commit()
    return doc_out(d)


@router.get("/search")
async def search(q: str, user: CurrentUser, db: DB, k: int = 6):
    """주인이 제 지식을 찾는다 — 전부. 외부인에게 무엇을 쓸지는 비서의 [지식] 탭이 정한다 (plan/57)."""
    return {"items": await K.search(db, user.id, q, k=min(k, 12))}


class FaqIn(BaseModel):
    question: str
    answer: str


@router.get("/faqs")
async def list_faqs(user: CurrentUser, db: DB):
    rows = (await db.execute(select(KnowledgeFaq).where(KnowledgeFaq.owner_id == user.id).order_by(KnowledgeFaq.created_at.desc()))).scalars().all()
    return {"items": [{"id": str(f.id), "question": f.question, "answer": f.answer,
                       "source": f.source} for f in rows]}


@router.post("/faqs", status_code=201)
async def create_faq(body: FaqIn, user: CurrentUser, db: DB):
    f = await K.upsert_faq(db, user.id, question=body.question, answer=body.answer)
    await db.commit()
    return {"id": str(f.id)}


@router.patch("/faqs/{faq_id}")
async def patch_faq(faq_id: uuid.UUID, body: FaqIn, user: CurrentUser, db: DB):
    f = await K.upsert_faq(db, user.id, question=body.question, answer=body.answer, faq_id=faq_id)
    await db.commit()
    return {"id": str(f.id)}


@router.delete("/faqs/{faq_id}")
async def delete_faq(faq_id: uuid.UUID, user: CurrentUser, db: DB):
    f = await db.get(KnowledgeFaq, faq_id)
    if f is None or f.owner_id != user.id:
        raise NotFound("faq not found")
    await db.delete(f)
    await db.commit()
    return {"ok": True}


@router.post("/faqs/import")
async def import_faqs(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    text = (await U.read_capped(file, U.TEXT_MAX)).decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    n = 0
    for row in reader:
        if len(row) < 2 or not row[0].strip() or row[0].strip().lower() in ("question", "질문"):
            continue
        await K.upsert_faq(db, user.id, question=row[0].strip(), answer=row[1].strip(), source="import")
        n += 1
        if n >= 500:
            break
    await db.commit()
    return {"imported": n}
