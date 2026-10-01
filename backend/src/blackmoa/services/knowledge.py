"""Knowledge documents: ingest → chunk → embed (worker) → hybrid search (plan/09)."""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.config import get_settings
from blackmoa.core.errors import NotFound, ValidationFailed
from blackmoa.core.logging import get_logger
from blackmoa.core.pools import run_blocking
from blackmoa.models import KnowledgeChunk, KnowledgeDocument, KnowledgeFaq, User
from blackmoa.providers.embedding import EmbeddingUnavailable, get_embedding_provider, pad
from blackmoa.services import jobs as J
from blackmoa.services import objectstore
from blackmoa.services.chunking import chunk_text
from blackmoa.services.extract import extract
from blackmoa.services.outsider import EVERYTHING, Scope

MAX_FILE = 25 * 1024 * 1024
ALLOWED_EXT = (".pdf", ".docx", ".pptx", ".xlsx", ".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm")
FAQ_THRESHOLD = 0.82  # cosine similarity on the question embedding


async def usage_bytes(db: AsyncSession, owner_id: uuid.UUID) -> int:
    return int((await db.execute(select(func.coalesce(func.sum(KnowledgeDocument.size_bytes), 0)).where(
        KnowledgeDocument.owner_id == owner_id))).scalar_one())


async def create_file(db: AsyncSession, owner: User, *, filename: str, mime: str, data: bytes,
                      title: str | None = None) -> KnowledgeDocument:
    if len(data) > MAX_FILE:
        raise ValidationFailed("file too large", code="file_too_large")
    if not filename.lower().endswith(ALLOWED_EXT):
        raise ValidationFailed("unsupported file type", code="unsupported_type")
    # 지식과 파일이 한 한도를 나눠 쓴다 (plan/55 결정 1).
    from blackmoa.services import files as FILES
    await FILES.ensure_room(db, owner, len(data))
    import unicodedata
    filename = unicodedata.normalize("NFC", os.path.basename(filename).replace("\x00", ""))[:255] or "file"
    doc = KnowledgeDocument(owner_id=owner.id, kind="file", title=(title or filename)[:255],
                            filename=filename, mime=mime[:128], size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            status="processing")
    db.add(doc)
    await db.flush()
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    key = f"{owner.id}/knowledge/{doc.id}{ext}"
    doc.storage_path = await objectstore.put(key, data, doc.mime or "application/octet-stream",
                                             local_path=get_settings().upload_root / key)
    await J.enqueue(db, "knowledge.index", {"document_id": str(doc.id)}, priority=3, owner_id=owner.id)
    return doc


async def create_text(db: AsyncSession, owner: User, *, kind: str, title: str, body: str = "",
                      url: str | None = None) -> KnowledgeDocument:
    # "blog" is a note whose source is a published post (plan/41 §4): indexing already
    # falls through to meta.body for anything that is not a file or a url.
    #
    # "community" is gone. 광장 글은 비서의 재료가 아니다 — 익명이라는 말은 그 글이
    # 나와 이어지지 않는다는 뜻이고, 설정으로 막는 것이 아니라 **길을 내지 않는다**
    # (plan/51 §2). 다리를 지우고 문을 남겨 두면 다음 사람이 그리로 들어온다.
    if kind not in ("note", "url", "blog"):
        raise ValidationFailed("bad kind")
    if kind in ("note", "blog") and not body.strip():
        raise ValidationFailed("empty note")
    doc = KnowledgeDocument(owner_id=owner.id, kind=kind, title=title[:255] or (url or "note")[:255],
                            source_url=url, size_bytes=len(body.encode()), status="processing",
                            text_preview=body[:2000], meta={"body": body} if kind in ("note", "blog") else {})
    db.add(doc)
    await db.flush()
    await J.enqueue(db, "knowledge.index", {"document_id": str(doc.id)}, priority=3, owner_id=owner.id)
    return doc


async def get_owned(db: AsyncSession, owner_id: uuid.UUID, doc_id: uuid.UUID) -> KnowledgeDocument:
    d = await db.get(KnowledgeDocument, doc_id)
    if d is None or d.owner_id != owner_id:
        raise NotFound("document not found", code="document_not_found")
    return d


async def delete_document(db: AsyncSession, doc: KnowledgeDocument) -> None:
    if doc.storage_path:
        await objectstore.delete(doc.storage_path)
    await db.delete(doc)



log = get_logger("blackmoa.knowledge")

def _extract_file(path: str, mime: str, filename: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read()
    return extract(data, mime, filename).text


async def _mark_failed(doc_id: uuid.UUID, error: str) -> None:
    """Persist a failure in its own transaction: the worker rolls the job transaction back on raise."""
    from blackmoa.db.session import session_scope
    async with session_scope() as db2:
        d = await db2.get(KnowledgeDocument, doc_id)
        if d is not None:
            d.status, d.error = "failed", error[:500]


async def index_document(db: AsyncSession, doc_id: uuid.UUID) -> dict[str, Any]:
    """Worker handler body. Extract → chunk → embed → store.
    Permanent failures (no text, unsupported, too many chunks, file missing) end the job with status=failed;
    transient ones (embedding key missing / provider down) persist status=failed and re-raise so the job retries."""
    doc = await db.get(KnowledgeDocument, doc_id)
    if doc is None:
        return {"skipped": "missing"}
    try:
        if doc.kind == "file":
            # The extractors take a path. Object storage has no path, so a remote object is
            # materialised for the length of the extraction and thrown away.
            src = doc.storage_path or ""
            tmp = None
            if src.startswith(objectstore.S3_PREFIX):
                import tempfile
                blob = await objectstore.get(src)
                fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(doc.filename or "")[1])

                def _spill(fd: int = fd, blob: bytes = blob) -> None:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(blob)

                # A fifty-megabyte write is not free: on the loop it stalls the worker's
                # other three jobs for as long as the disk takes.
                await run_blocking("docs", _spill, label="materialise")
                src = tmp
            try:
                full = await run_blocking("docs", lambda: _extract_file(src, doc.mime or "", doc.filename or ""),
                                          label=f"extract:{doc.mime or doc.kind}")
            finally:
                if tmp:
                    with contextlib.suppress(OSError):
                        os.remove(tmp)
        elif doc.kind == "url":
            from blackmoa.services.webfetch import fetch_text
            full = await fetch_text(doc.source_url or "")
        else:
            full = (doc.meta or {}).get("body", "")
        chunks = await run_blocking("docs", lambda: chunk_text(full), label="chunk")
        if not chunks:
            raise ValueError("no_text")
    except (ValueError, OSError, LookupError) as e:
        doc.status, doc.error = "failed", str(e)[:500] or e.__class__.__name__
        return {"failed": doc.error}
    # No embedding key is not a failure: search runs three legs (vector ∪ tsvector ∪ trigram)
    # and the two lexical ones need no vector at all. Indexing without vectors keeps the
    # document answerable today; /admin/embedding re-indexes it once a key exists. Failing
    # the whole document instead made every upload on a key-less install unusable.
    emb = None
    vectors: list[list[float] | None] = [None] * len(chunks)
    try:
        emb = await get_embedding_provider(db)
        vectors = list(await emb.embed([c.text for c in chunks]))
    except EmbeddingUnavailable:
        log.warning("indexing without embeddings", doc=str(doc.id), reason="no embedding key configured")
    except Exception as e:  # noqa: BLE001
        await _mark_failed(doc.id, f"embedding_failed: {str(e)[:200]}")
        raise
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    for c, v in zip(chunks, vectors, strict=True):
        db.add(KnowledgeChunk(document_id=doc.id, owner_id=doc.owner_id, ordinal=c.ordinal, text=c.text,
                              tokens=c.tokens, heading=c.heading, page=c.page, embedding=pad(v) if v is not None else None))
    doc.chunk_count = len(chunks)
    doc.status = "ready"
    doc.error = None
    doc.embedding_model = f"{emb.provider}/{emb.model}" if emb is not None else ""
    doc.text_preview = full[:2000]
    doc.updated_at = datetime.now(UTC)
    return {"chunks": len(chunks)}


async def embed_query(db: AsyncSession, q: str) -> list[float] | None:
    """None → callers fall back to keyword search (missing key, provider outage, network error)."""
    try:
        emb = await get_embedding_provider(db)
        return pad((await emb.embed([q]))[0])
    except Exception:  # noqa: BLE001
        return None


async def search(db: AsyncSession, owner_id: uuid.UUID, query: str, *, k: int = 6, scope: Scope | None = EVERYTHING,
                 qvec: list[float] | None = None) -> list[dict[str, Any]]:
    """Hybrid: vector top-20 ∪ tsvector top-20 → RRF.

    무엇을 뒤질지는 ``scope`` 하나가 가른다 (plan/57). 나와의 대화면 전부, 외부인과의
    대화면 그 비서의 [지식] 탭에서 고른 문서·FAQ 만. ``None`` 이면 외부인에게 지식을
    쓰지 않는 비서다 — 아무것도 찾지 않는다.
    """
    if scope is None:
        return []
    # 문서를 한 비서에만 묶던 조건은 없다 (plan/50 §2). 지식은 [내 정보] 이고, 나와의
    # 대화에서는 모든 비서가 전부 본다. 외부인에게 무엇을 쓸지는 그 비서가 고른다.
    doc_clause = "" if scope.all else " AND d.id IN :docs"
    params: dict[str, Any] = {"o": owner_id, "q": query}
    if not scope.all:
        params["docs"] = list(scope.ids)
    run_docs = scope.all or bool(scope.ids)

    def _sql(body: str):
        stmt = text(body)
        return stmt.bindparams(bindparam("docs", expanding=True)) if not scope.all else stmt
    ranks: dict[uuid.UUID, float] = {}
    rows: dict[uuid.UUID, Any] = {}
    if qvec is None:
        qvec = await embed_query(db, query)
    if qvec is not None and run_docs:
        params["v"] = str(qvec)
        vrows = (await db.execute(_sql(f"""
            SELECT c.id, c.document_id, c.text, c.heading, c.page, d.title, 1 - (c.embedding <=> CAST(:v AS vector)) AS score
            FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.owner_id = :o AND d.status = 'ready' AND c.embedding IS NOT NULL{doc_clause}
            ORDER BY c.embedding <=> CAST(:v AS vector) LIMIT 20"""), params)).mappings().all()
        for i, r in enumerate(vrows):
            if r["score"] < 0.15:
                continue
            ranks[r["id"]] = ranks.get(r["id"], 0) + 1 / (60 + i)
            rows[r["id"]] = r
    trows = (await db.execute(_sql(f"""
        SELECT c.id, c.document_id, c.text, c.heading, c.page, d.title,
               ts_rank(c.tsv, plainto_tsquery('simple', :q)) AS score
        FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
        WHERE c.owner_id = :o AND d.status = 'ready' AND c.tsv @@ plainto_tsquery('simple', :q){doc_clause}
        ORDER BY score DESC LIMIT 20"""), params)).mappings().all() if run_docs else []
    for i, r in enumerate(trows):
        ranks[r["id"]] = ranks.get(r["id"], 0) + 1 / (60 + i)
        rows.setdefault(r["id"], r)
    # Korean-friendly substring/trigram leg (agglutinative suffixes defeat 'simple' tokenization)
    terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= 2][:5]
    if terms and run_docs:
        like_clause = " OR ".join(f"c.text ILIKE :t{i}" for i in range(len(terms)))
        lparams = {**params, **{f"t{i}": f"%{t}%" for i, t in enumerate(terms)}}
        lrows = (await db.execute(_sql(f"""
            SELECT c.id, c.document_id, c.text, c.heading, c.page, d.title, similarity(c.text, :q) AS score
            FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.owner_id = :o AND d.status = 'ready' AND ({like_clause}){doc_clause}
            ORDER BY score DESC, length(c.text) ASC LIMIT 20"""), lparams)).mappings().all()
        for i, r in enumerate(lrows):
            ranks[r["id"]] = ranks.get(r["id"], 0) + 1 / (60 + i)
            rows.setdefault(r["id"], r)
    ordered = sorted(ranks.items(), key=lambda kv: kv[1], reverse=True)[:k]
    out = []
    for cid, sc in ordered:
        r = rows[cid]
        out.append({"chunk_id": str(cid), "document_id": str(r["document_id"]), "title": r["title"],
                    "heading": r["heading"], "page": r["page"], "text": r["text"][:1200], "score": round(sc * 60, 3)})
    # FAQ exact-ish matches on top
    faqs = await search_faqs(db, owner_id, query, scope=scope, qvec=qvec)
    return faqs + out


async def search_faqs(db: AsyncSession, owner_id: uuid.UUID, query: str, *, scope: Scope | None = EVERYTHING,
                      qvec: list[float] | None, k: int = 2) -> list[dict[str, Any]]:
    if scope is None or (not scope.all and not scope.faq_ids):
        return []
    crit = [KnowledgeFaq.owner_id == owner_id]
    if not scope.all:
        crit.append(KnowledgeFaq.id.in_(list(scope.faq_ids)))
    if qvec is not None:
        # ONE query: rows + similarity; threshold in Python on the top-k (plan/09: cosine ≥ FAQ_THRESHOLD → answer on top)
        dist = KnowledgeFaq.embedding.cosine_distance(qvec)
        stmt = select(KnowledgeFaq, (1 - dist).label("sim")).where(*crit, KnowledgeFaq.embedding.isnot(None)).order_by(dist).limit(k)
        rows = (await db.execute(stmt)).all()
        return [{"faq_id": str(f.id), "title": "FAQ", "heading": f.question, "page": None, "text": f.answer[:1200],
                 "score": round(float(s), 3), "faq": True} for f, s in rows if s is not None and float(s) >= FAQ_THRESHOLD]
    # Keyword fallback (no embedding provider). Matching the whole sentence as one LIKE
    # pattern never fires in practice — "어떤 결제사를 지원하나요?" does not occur inside
    # "지원하는 결제사가 어디인가요?". Score by how many of the query's content words appear
    # in the question or the answer instead, and rank by that.
    tokens = faq_tokens(query)
    if not tokens:
        return []
    rows = (await db.execute(select(KnowledgeFaq).where(*crit).limit(200))).scalars().all()
    scored: list[tuple[int, KnowledgeFaq]] = []
    for f in rows:
        hay = f"{f.question} {f.answer}".lower()
        hits = sum(1 for t in tokens if t in hay)
        if hits:
            scored.append((hits, f))
    scored.sort(key=lambda x: (-x[0], len(x[1].question)))
    out = []
    for hits, f in scored[:k]:
        # Keyword evidence is weaker than a semantic match: stay below FAQ_THRESHOLD so the
        # caller treats it as a candidate, not as the answer.
        out.append({"faq_id": str(f.id), "title": "FAQ", "heading": f.question, "page": None,
                    "text": f.answer[:1200], "score": round(min(0.8, 0.45 + 0.12 * hits), 3), "faq": True})
    return out



# Korean attaches particles to nouns, so "결제사를" and "결제사가" have to reduce to the same
# stem before a keyword match can work at all.
_PARTICLES = ("으로서", "으로써", "에서는", "에게는", "이라고", "라고", "에서", "에게", "부터", "까지",
              "하고", "이랑", "으로", "이나", "인가요", "인가", "나요", "까요", "은", "는", "이", "가",
              "을", "를", "에", "의", "와", "과", "도", "만", "로", "요")
_STOPWORDS = {"어떤", "무엇", "뭐", "누구", "언제", "어디", "어떻게", "얼마", "왜", "그리고", "하는", "있나",
              "있나요", "있어요", "해주세요", "알려", "알려주세요", "지원", "무슨", "what", "which", "who",
              "when", "where", "how", "the", "and", "for", "you", "your", "are", "is", "do", "does"}


def faq_tokens(query: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[^\w가-힣]+", (query or "").lower()):
        if len(raw) < 2:
            continue
        tok = raw
        for p in _PARTICLES:
            if tok.endswith(p) and len(tok) > len(p) + 1:
                tok = tok[: -len(p)]
                break
        if len(tok) >= 2 and tok not in _STOPWORDS:
            out.append(tok)
    return out[:8]


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def read_document(db: AsyncSession, owner_id: uuid.UUID, doc_id: uuid.UUID, *, scope: Scope | None = EVERYTHING,
                        page: int | None = None, heading: str | None = None, max_chars: int = 8000) -> dict[str, Any]:
    doc = await db.get(KnowledgeDocument, doc_id)
    # 고르지 않은 문서는 없는 문서와 똑같이 답한다 — "있지만 못 보여 준다" 도 정보다.
    if doc is None or doc.owner_id != owner_id or scope is None or not scope.has(doc.id):
        raise NotFound("document not found", code="document_not_found")
    stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.ordinal)
    if page is not None:
        stmt = stmt.where(KnowledgeChunk.page == page)
    if heading:
        stmt = stmt.where(KnowledgeChunk.heading.ilike(f"%{heading}%"))
    chunks = (await db.execute(stmt.limit(40))).scalars().all()
    body = "\n\n".join(c.text for c in chunks)
    if not body and doc.kind == "note" and page is None and not heading:
        body = (doc.meta or {}).get("body", "") or doc.text_preview or ""  # not indexed yet: serve the source text
    body = body[:max_chars]
    return {"document_id": str(doc.id), "title": doc.title, "kind": doc.kind, "status": doc.status, "text": body,
            "truncated": len(body) >= max_chars, "chunk_count": doc.chunk_count}


async def upsert_faq(db: AsyncSession, owner_id: uuid.UUID, *, question: str, answer: str,
                     faq_id: uuid.UUID | None = None, source: str = "manual") -> KnowledgeFaq:
    if faq_id:
        f = await db.get(KnowledgeFaq, faq_id)
        if f is None or f.owner_id != owner_id:
            raise NotFound("faq not found")
        f.question, f.answer = question[:2000], answer[:8000]
    else:
        f = KnowledgeFaq(owner_id=owner_id, question=question[:2000], answer=answer[:8000], source=source)
        db.add(f)
    try:
        emb = await get_embedding_provider(db)
        f.embedding = pad((await emb.embed([question]))[0])
    except EmbeddingUnavailable:
        f.embedding = None
    await db.flush()
    return f
