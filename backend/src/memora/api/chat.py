"""Owner chat: conversations, messages, turns (SSE), resume, cancel, simulator, STT/TTS."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from memora.core import pools
from memora.core.deps import DB, CurrentUser, release_db
from memora.core.errors import NotFound, ValidationFailed
from memora.models import ToolSpan, Turn
from memora.pipeline.events import journals, replay_persisted, stream_journal
from memora.pipeline.runner import TurnRequest, cancel_turn, launch_turn, start_turn
from memora.pipeline.runtime import runtimes
from memora.services import agents as AG
from memora.services import conversations as CV
from memora.services import credits as CR
from memora.services import feedback as FB
from memora.services import settings as S
from memora.services import uploads as U
from memora.services import voice as VOICE
from memora.services.uploads import attachments_from_ids, with_urls

router = APIRouter(prefix="/api", tags=["chat"])


def conv_out(c) -> dict:
    return {"id": str(c.id), "agent_id": str(c.agent_id), "audience": c.audience, "visitor_id": str(c.visitor_id) if c.visitor_id else None,
            "title": c.title, "status": c.status, "summary": c.summary, "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            "message_count": c.message_count, "unread_owner": c.unread_owner, "created_at": c.created_at.isoformat(),
            "kind": getattr(c, "kind", "human") or "human", "relay_id": str(c.relay_id) if getattr(c, "relay_id", None) else None}


def msg_out(m, marks: dict[str, dict] | None = None, turn_states: dict[str, str] | None = None) -> dict:
    out = {"id": str(m.id), "role": m.role, "content": m.content, "attachments": with_urls(m.attachments), "cards": m.cards or [],
           "turn_id": str(m.turn_id) if m.turn_id else None, "created_at": m.created_at.isoformat()}
    # 멈춘 답(중지·다른 화면에서 새로 물음)과 받지 못한 답은 어느 화면에서 열어도 그렇게 보인다(plan/69).
    if turn_states and m.turn_id and (ts := turn_states.get(str(m.turn_id))):
        out["turn_status"] = ts
    if marks and m.turn_id and (mark := marks.get(str(m.turn_id))):
        out["feedback"] = mark
    return out


@router.get("/agents/{agent_id}/conversations")
async def list_conversations(agent_id: uuid.UUID, user: CurrentUser, db: DB, audience: str | None = None, kind: str | None = None, limit: int = 50):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    rows = await CV.list_for_agent(db, user.id, a.id, audience=audience, kind=kind if kind in ("human", "agent") else None, limit=min(limit, 200))
    return {"items": [conv_out(c) for c in rows]}


class ConvCreate(BaseModel):
    title: str = ""


@router.post("/agents/{agent_id}/conversations", status_code=201)
async def create_conversation(agent_id: uuid.UUID, body: ConvCreate, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id)
    c = await CV.create(db, owner_id=user.id, agent_id=a.id, audience="owner", title=body.title)
    await announce_conversation(db, user.id, c, "created")
    await db.commit()
    return conv_out(c)


async def announce_conversation(db, owner_id: uuid.UUID, c, change: str) -> None:
    """대화가 생겼다·바뀌었다·지워졌다 — 주인의 다른 화면의 대화 목록이 바로 따라온다(plan/69)."""
    from memora.core import bus

    await bus.publish(db, owner_id=owner_id, kind="conversation",
                      data={"change": change, "conversation_id": str(c.id), "agent_id": str(c.agent_id), "audience": c.audience})


@router.get("/agents/{agent_id}/conversations/{cid}")
async def get_conversation(agent_id: uuid.UUID, cid: uuid.UUID, user: CurrentUser, db: DB):
    c = await CV.get_owned(db, user.id, cid, agent_id)
    if c.unread_owner:
        await CV.mark_read(db, c.id)
        await db.commit()
    return conv_out(c)


class ConvPatch(BaseModel):
    title: str | None = None
    status: str | None = None


@router.patch("/agents/{agent_id}/conversations/{cid}")
async def patch_conversation(agent_id: uuid.UUID, cid: uuid.UUID, body: ConvPatch, user: CurrentUser, db: DB):
    c = await CV.get_owned(db, user.id, cid, agent_id)
    if body.title is not None:
        c.title = body.title[:160]
    if body.status in ("active", "archived"):
        c.status = body.status
    await announce_conversation(db, user.id, c, "updated")
    await db.commit()
    return conv_out(c)


@router.delete("/agents/{agent_id}/conversations/{cid}")
async def delete_conversation(agent_id: uuid.UUID, cid: uuid.UUID, user: CurrentUser, db: DB):
    c = await CV.get_owned(db, user.id, cid, agent_id)
    await runtimes.drop_conversation(agent_id, cid)
    await announce_conversation(db, user.id, c, "deleted")
    await db.delete(c)
    await db.commit()
    return {"ok": True}


@router.get("/agents/{agent_id}/conversations/{cid}/messages")
async def list_messages(agent_id: uuid.UUID, cid: uuid.UUID, user: CurrentUser, db: DB, before: uuid.UUID | None = None, limit: int = 50):
    c = await CV.get_owned(db, user.id, cid, agent_id)
    rows = await CV.messages(db, c.id, before=before, limit=min(limit, 200))
    # What the owner already corrected stays visible on the answer they corrected,
    # so they do not tell the secretary the same thing twice.
    marks = await FB.for_turns(db, user.id, [m.turn_id for m in rows if m.turn_id])
    return {"items": [msg_out(m, marks, await turn_states(db, rows)) for m in rows]}


async def turn_states(db, rows) -> dict[str, str]:
    """이 메시지들을 만든 턴 가운데 끝까지 가지 못한 것: cancelled · superseded · failed · running."""
    ids = {m.turn_id for m in rows if m.turn_id}
    if not ids:
        return {}
    res = (await db.execute(select(Turn.id, Turn.status, Turn.error_code).where(Turn.id.in_(ids)))).all()
    out: dict[str, str] = {}
    for tid, status, code in res:
        if status == "cancelled":
            out[str(tid)] = "superseded" if code == "superseded" else "cancelled"
        elif status in ("failed", "running", "pending"):
            out[str(tid)] = "running" if status == "pending" else status
    return out


class TurnIn(BaseModel):
    text: str = Field(default="", max_length=20000)
    attachments: list[dict] = Field(default_factory=list, max_length=8)   # 옛 클라이언트용, 읽지 않는다
    upload_ids: list[uuid.UUID] = Field(default_factory=list, max_length=8)
    client_turn_id: str | None = Field(default=None, max_length=64)
    simulate_visitor: bool = False


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def turn_stream(turn: Turn, after: int = 0, *, visitor: bool = False, request: Request | None = None) -> StreamingResponse:
    """Live journal when present, otherwise the persisted replay (idempotent re-POST / late resume)."""
    j = journals.get(turn.id)
    inner = stream_journal(j, after, visitor=visitor) if j is not None else replay_persisted(turn.id, after, running=(turn.status == "running"), visitor=visitor)

    async def gen():
        # The turn's own work is done; what follows is waiting for a model. Holding a
        # database connection through that is how thirty conversations take the whole pool.
        if request is not None:
            await release_db(request)
        async for chunk in inner:
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"X-Turn-Id": str(turn.id), **SSE_HEADERS})


@router.post("/agents/{agent_id}/conversations/{cid}/turns")
async def post_turn(agent_id: uuid.UUID, cid: uuid.UUID, body: TurnIn, user: CurrentUser, db: DB, request: Request):
    a = await AG.get_owned(db, user.id, agent_id)
    c = await CV.get_owned(db, user.id, cid, agent_id)
    # 첨부는 올린 파일의 id 로만 받는다. 요청에 실린 메타데이터(이름·종류·글)를 그대로
    # 믿으면 없는 파일이 대화에 남고, 모델에게는 사용자가 쓰지 않은 "첨부 글"이 간다.
    atts = await attachments_from_ids(db, user.id, body.upload_ids) if body.upload_ids else []
    audience = "visitor" if (body.simulate_visitor or c.simulated) else "owner"
    req = TurnRequest(owner=user, agent=a, conversation=c, audience=audience, text=body.text, attachments=atts,
                      client_turn_id=body.client_turn_id, simulated=(audience == "visitor"))
    turn = await start_turn(db, req)
    await db.commit()
    launch_turn(turn)
    return turn_stream(turn, 0, request=request)


@router.post("/agents/{agent_id}/simulate", status_code=201)
async def create_simulation(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id)
    c = await CV.create(db, owner_id=user.id, agent_id=a.id, audience="visitor", title="방문자 시뮬레이션", simulated=True)
    await db.commit()
    return conv_out(c)


@router.get("/agents/{agent_id}/turns/{turn_id}/events")
async def resume_turn(agent_id: uuid.UUID, turn_id: uuid.UUID, user: CurrentUser, db: DB, request: Request, after: int = 0):
    t = await db.get(Turn, turn_id)
    if t is None or t.owner_id != user.id or t.agent_id != agent_id:
        raise NotFound("turn not found", code="turn_not_found")
    return turn_stream(t, after, request=request)


@router.post("/agents/{agent_id}/turns/{turn_id}/cancel", status_code=202)
async def cancel(agent_id: uuid.UUID, turn_id: uuid.UUID, user: CurrentUser, db: DB):
    t = await db.get(Turn, turn_id)
    if t is None or t.owner_id != user.id:
        raise NotFound("turn not found", code="turn_not_found")
    return {"cancelled": await stop_turn(db, t)}


@router.post("/agents/{agent_id}/conversations/{cid}/cancel", status_code=202)
async def cancel_active(agent_id: uuid.UUID, cid: uuid.UUID, user: CurrentUser, db: DB):
    """[그만]: 이 대화에서 지금 흐르는 답을 멈춘다 — 어느 화면이 시작했든(plan/69).

    턴 번호를 몰라도 된다. 답이 막 시작돼 번호가 아직 오지 않은 순간에 누른 [그만] 도, 다른 화면이 시작한
    답을 여기서 누른 [그만] 도 같은 곳에 닿는다."""
    await CV.get_owned(db, user.id, cid, agent_id)
    t = (await db.execute(select(Turn).where(Turn.conversation_id == cid, Turn.status.in_(("pending", "running")))
                          .order_by(Turn.started_at.desc()))).scalars().first()
    if t is None:
        return {"cancelled": False, "turn_id": None}
    return {"cancelled": await stop_turn(db, t), "turn_id": str(t.id)}


async def stop_turn(db, t: Turn) -> bool:
    """멈춘다. 이 프로세스가 돌리는 턴이면 작업을 끊고(정리는 턴이 한다), 아무도 돌리지 않는 턴(재시작으로 주인을
    잃었다)이면 여기서 멈춘 것으로 적고 알린다 — 멈추지 않는 [그만] 이 없게."""
    if await cancel_turn(t.id):
        return True
    if t.status not in ("pending", "running"):
        return False
    from datetime import UTC, datetime

    from memora.pipeline.runner import announce_turn

    t.status = "cancelled"
    t.error_code = "cancelled"
    t.ended_at = datetime.now(UTC)
    await CR.release_turn(db, t.id)
    await announce_turn(db, owner_id=t.owner_id, phase="end", turn_id=t.id, conversation_id=t.conversation_id,
                        agent_id=t.agent_id, audience=t.audience, status="cancelled", reason="cancelled")
    await db.commit()
    return True


@router.get("/agents/{agent_id}/conversations/{cid}/active-turn")
async def active_turn(agent_id: uuid.UUID, cid: uuid.UUID, user: CurrentUser, db: DB):
    await CV.get_owned(db, user.id, cid, agent_id)
    t = await CV.active_turn(db, cid)
    if t is None:
        return None
    j = journals.get(t.id)
    return {"turn_id": str(t.id), "seq": j.seq if j else 0, "started_at": t.started_at.isoformat()}


class FeedbackIn(BaseModel):
    verdict: str
    note: str = ""


@router.post("/agents/{agent_id}/turns/{turn_id}/feedback")
async def turn_feedback(agent_id: uuid.UUID, turn_id: uuid.UUID, body: FeedbackIn, user: CurrentUser, db: DB):
    """Say an answer was wrong, and what was actually the case (plan/41 §8).

    The correction becomes something the secretary answers from, so this is a teaching
    loop rather than a complaint box.
    """

    out = await FB.mark(db, user, turn_id, verdict=body.verdict, note=body.note)
    await db.commit()
    return out


@router.get("/agents/{agent_id}/turns/{turn_id}")
async def get_turn(agent_id: uuid.UUID, turn_id: uuid.UUID, user: CurrentUser, db: DB):
    t = await db.get(Turn, turn_id)
    if t is None or t.owner_id != user.id:
        raise NotFound("turn not found", code="turn_not_found")
    spans = (await db.execute(select(ToolSpan).where(ToolSpan.turn_id == t.id).order_by(ToolSpan.started_at))).scalars().all()
    return {"id": str(t.id), "status": t.status, "provider": t.provider, "model_id": t.model_id, "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens, "cache_read_tokens": t.cache_read_tokens, "credits": float(t.credits or 0),
            "duration_ms": t.duration_ms, "ttft_ms": t.ttft_ms, "error_code": t.error_code, "tool_call_count": t.tool_call_count,
            "redactions": t.redactions, "injection_suspect": t.injection_suspect, "started_at": t.started_at.isoformat(),
            "spans": [{"name": s.name, "input": s.input, "output_preview": s.output_preview, "is_error": s.is_error, "duration_ms": s.duration_ms} for s in spans]}


@router.post("/agents/{agent_id}/stt")
async def stt(agent_id: uuid.UUID, user: CurrentUser, db: DB, file: UploadFile = File(...), language: str = Form("")):
    from memora.providers.stt import get_stt
    await VOICE.require(db, "stt")
    await AG.get_owned(db, user.id, agent_id)
    data = await U.read_capped(file, U.AUDIO_MAX)
    if len(data) > 25 * 1024 * 1024:
        raise ValidationFailed("audio too large")
    prov = await get_stt(db)
    tr = await prov.transcribe(data, file.content_type or "audio/webm", language or None)
    minutes = max(0.1, (tr.duration_s or len(data) / 32000) / 60)
    await CR.charge_usage(db, owner_id=user.id, kind="stt", credits=float(await S.get(db, "stt.credit_per_minute")) * minutes,
                          provider=prov.provider, units=minutes, agent_id=agent_id)
    await db.commit()
    return {"text": tr.text, "language": tr.language}


class TtsIn(BaseModel):
    text: str
    voice: str | None = None
    speed: float = 1.0


@router.post("/agents/{agent_id}/tts")
async def tts(agent_id: uuid.UUID, body: TtsIn, user: CurrentUser, db: DB):
    from memora.providers.tts import cache_path, get_tts
    await VOICE.require(db, "tts")
    a = await AG.get_owned(db, user.id, agent_id)
    text = body.text.strip()[:4000]
    if not text:
        raise ValidationFailed("empty text")
    prov = await get_tts(db)
    voice = body.voice or (a.voice or {}).get("tts_voice") or await S.get(db, "tts.default_voice")
    p = cache_path(text, voice, prov.model)
    if not await pools.to_thread("misc", p.exists):
        chunks = [c async for c in prov.synthesize(text, voice, body.speed)]
        await pools.to_thread("misc", p.write_bytes, b"".join(chunks))
        await CR.charge_usage(db, owner_id=user.id, kind="tts", credits=float(await S.get(db, "tts.credit_per_1k_chars")) * len(text) / 1000,
                              provider=prov.provider, units=len(text), agent_id=agent_id)
        await db.commit()
    data = await pools.to_thread("misc", p.read_bytes)
    return StreamingResponse(iter([data]), media_type="audio/mpeg")
