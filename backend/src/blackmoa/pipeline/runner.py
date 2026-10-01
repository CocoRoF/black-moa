"""SecretaryRunner — THE single execution path for every turn (plan/07 §턴 실행)."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from blackmoa.core import llm_manager as LLM
from blackmoa.core.errors import BlackMoaError, PaymentRequired
from blackmoa.core.logging import get_logger
from blackmoa.core.ratelimit import limiter
from blackmoa.db.session import session_scope
from blackmoa.models import Agent, Conversation, Fact, ShareLink, ToolSpan, Turn, User, Visitor
from blackmoa.pipeline import base_prompt as BP
from blackmoa.pipeline.budget import CLAMP_NOTICE_KO, fit_input
from blackmoa.pipeline.events import TurnJournal, journals
from blackmoa.pipeline.guard import StreamRedactor, claims_to_be_owner, injection_suspect, redact_response
from blackmoa.pipeline.runtime import AgentRuntime, runtimes
from blackmoa.providers.errors import classify, retryable, user_message
from blackmoa.services import catalog as CAT
from blackmoa.services import credits as CR
from blackmoa.services import jobs as J
from blackmoa.services import knowledge as K
from blackmoa.services import network as N
from blackmoa.services import plans as P
from blackmoa.services import profile as PF
from blackmoa.services import relationship as REL
from blackmoa.services import relay as RELAY
from blackmoa.services.conversations import add_message

log = get_logger("blackmoa.runner")
TOOL_LABELS = {
    "memory_search": "기억을 찾는 중", "memory_remember": "기억을 저장하는 중", "knowledge_search": "자료를 찾는 중",
    "network_search": "인맥을 찾는 중", "email_search": "메일을 찾는 중", "calendar_list": "일정을 확인하는 중",
    "calendar_availability": "가능한 시간을 확인하는 중", "leave_message": "메시지를 전달하는 중",
    "meeting_propose": "미팅 요청을 전달하는 중", "web_search": "웹을 검색하는 중", "web_fetch": "페이지를 읽는 중",
    "facts_search": "사실을 확인하는 중", "network_propose": "인맥 제안을 만드는 중", "profile_update": "프로필을 수정하는 중",
}


#: 방문자 화면은 도구 이름을 받지 않는다(events._visitor_projection). 그래서 영어로 보는 사람에게 줄 이름표도 여기서 붙인다.
TOOL_LABELS_EN = {
    "calendar_availability": "Checking available times", "meeting_propose": "Sending the meeting request",
    "leave_message": "Passing on your message", "notify_owner": "Letting the owner know", "visitor_identify": "Noting who you are",
    "knowledge_search": "Looking through reference material", "knowledge_read": "Reading reference material",
    "memory_search": "Checking memory", "memory_read": "Checking memory", "facts_search": "Checking facts",
    "files_list": "Looking through files", "file_read": "Reading a file", "file_view": "Looking at a file", "file_share": "Sharing a file",
    "web_search": "Searching the web", "web_fetch": "Reading a page", "now": "Checking the time",
    "network_search": "Looking up people", "network_person": "Looking up a person", "network_propose": "Preparing a connection suggestion",
    "relay_close": "Closing the conversation", "calendar_list": "Checking the schedule",
}


def tool_label_en(name: str) -> str:
    return TOOL_LABELS_EN.get(name.removeprefix("mcp__blackmoa__"), "Checking")


def tool_label(name: str) -> str:
    """사람에게 보일 한 줄. 도구가 제 이름표(``label_template``)를 들고 있으면 그것이 먼저다 —
    예전에는 이 표에 없는 도구가 모두 "확인하는 중" 이었다."""
    bare = name.removeprefix("mcp__blackmoa__")
    from blackmoa.pipeline.tools import all_tools
    cls = all_tools().get(bare)
    return (getattr(cls, "label_template", "") if cls else "") or TOOL_LABELS.get(bare, "확인하는 중")


class TurnRequest:
    def __init__(self, *, owner: User, agent: Agent, conversation: Conversation, audience: str, text: str,
                 attachments: list[dict[str, Any]] | None = None, visitor: Visitor | None = None,
                 share_link: ShareLink | None = None, client_turn_id: str | None = None, simulated: bool = False):
        self.owner, self.agent, self.conversation, self.audience = owner, agent, conversation, audience
        self.text, self.attachments, self.visitor, self.share_link = text, attachments or [], visitor, share_link
        self.client_turn_id, self.simulated = client_turn_id, simulated


async def start_turn(db, req: TurnRequest) -> Turn:
    """Create and reserve a turn transactionally. Execution starts only after commit via ``launch_turn``."""
    # Serialize all turn creation for one conversation. This makes the read-side
    # idempotency check and active-turn replacement atomic across API workers.
    conv = (await db.execute(select(Conversation).where(Conversation.id == req.conversation.id).with_for_update())).scalars().first()
    if conv is None or conv.owner_id != req.owner.id or conv.agent_id != req.agent.id:
        raise BlackMoaError("conversation not found", code="conversation_not_found", status=404)
    req.conversation = conv
    if req.client_turn_id:
        existing = (await db.execute(select(Turn).where(Turn.conversation_id == conv.id,
                                                         Turn.client_turn_id == req.client_turn_id))).scalars().first()
        if existing:
            return existing
    if req.agent.status != "active":
        raise BlackMoaError("agent not active", code="agent_not_active", status=409)
    if req.audience == "owner":
        limiter.check(f"turn:owner:{req.owner.id}", 20, 60)
    else:
        from blackmoa.services.agents import DEFAULT_VISITOR_SETTINGS as _VD
        rate = int((req.agent.visitor_settings or {}).get("rate_per_minute", _VD["rate_per_minute"]) or 0)
        # The owner's visitor simulator runs the visitor path with no visitor row, so rate
        # limit the owner instead of dereferencing None (that crashed every simulated turn).
        if rate > 0:      # 0 은 주인이 고른 "제한 없음" 이다 (plan/53)
            limiter.check(f"turn:visitor:{req.visitor.id}" if req.visitor else f"turn:sim:{req.owner.id}", rate, 60)
        if req.share_link:
            limiter.check(f"turn:link:{req.share_link.id}", 120, 60)
    text = (req.text or "").strip()
    if not text and not req.attachments:
        raise BlackMoaError("empty message", code="empty_message", status=422)
    max_len = 8000 if req.audience == "owner" else 2000
    text = text[:max_len]

    # Insert as pending so the one-running-turn unique index is never transiently
    # violated while the previous turn is still being replaced.
    turn = Turn(conversation_id=conv.id, owner_id=req.owner.id, agent_id=req.agent.id, audience=req.audience,
                client_turn_id=req.client_turn_id, status="pending", provider=req.agent.provider, model_id=req.agent.model_id,
                user_text=text, started_at=datetime.now(UTC), simulated=bool(req.simulated),
                injection_suspect=(req.audience == "visitor" and injection_suspect(text)))
    db.add(turn)
    await db.flush()
    # What this secretary may spend is set on the secretary (plan/34); the account's
    # balance still bounds all of it.
    from blackmoa.services.agents import DEFAULT_VISITOR_SETTINGS as _VDEF
    visitor_cap = int((req.agent.visitor_settings or {}).get("turns_per_day", _VDEF["turns_per_day"]) or 0)
    reservation = await CR.reserve_turn(db, owner_id=req.owner.id, turn_id=turn.id, agent_id=req.agent.id,
                                        turn_cap=max(1, int(req.agent.turn_cost_cap_credits or 50)),
                                        daily_cap=int(req.agent.daily_credit_cap or 0),
                                        monthly_cap=int(req.agent.monthly_credit_cap or 0),
                                        audience=req.audience,
                                        visitor_turn_cap=visitor_cap if (req.audience == "visitor" and visitor_cap) else None)

    active = (await db.execute(select(Turn).where(Turn.conversation_id == conv.id, Turn.status == "running",
                                                   Turn.id != turn.id).with_for_update())).scalars().first()
    previous_turn_id = active.id if active else None
    if active:
        active.status = "cancelled"
        active.error_code = active.error_code or "superseded"
        active.ended_at = datetime.now(UTC)
    turn.status = "running"

    meta_atts = [{k: v for k, v in a.items() if k not in ("data", "text")} for a in req.attachments if isinstance(a, dict)]
    msg = await add_message(db, conv, role="user", content=text, turn_id=turn.id, attachments=meta_atts)
    if meta_atts and not req.simulated:
        # 들어온 자료는 그 비서의 [파일] 에 쌓인다 (plan/55). 파일 id 를 첨부에 적어 두면
        # 비서는 "나중에 다시 열 수 있는 파일" 로 알고, 말풍선은 [파일] 의 그 파일로 이어진다.
        from blackmoa.services import files as FILES
        recorded = await FILES.record_message(db, conv, msg.id, meta_atts)
        by_upload = {str(f.upload_id): str(f.id) for f in recorded}
        for a in [*req.attachments, *meta_atts]:
            if isinstance(a, dict) and (fid := by_upload.get(str(a.get("upload_id")))):
                a["file_id"] = fid
        # 제자리에서 고친 JSON 은 SQLAlchemy 가 바뀐 줄 모른다 — 알려 줘야 저장된다.
        from sqlalchemy.orm.attributes import flag_modified
        msg.attachments = [dict(a) for a in meta_atts]
        flag_modified(msg, "attachments")
    req.text = text
    # 이 대화에 턴이 시작됐다 — 주인의 다른 화면(다른 탭, PC 앱)이 곧바로 따라 붙는다(plan/69).
    # 받는 쪽은 이 번호로 이어 받기(/turns/{id}/events)를 열고, 방금 들어간 사용자의 말은 다시 읽는다.
    await announce_turn(db, owner_id=req.owner.id, phase="start", turn_id=turn.id, conversation_id=conv.id,
                        agent_id=req.agent.id, audience=req.audience, client_turn_id=req.client_turn_id,
                        superseded=previous_turn_id)
    ids = {"turn_id": turn.id, "owner_id": req.owner.id, "agent_id": req.agent.id, "conversation_id": conv.id,
           "visitor_id": req.visitor.id if req.visitor else None, "share_link_id": req.share_link.id if req.share_link else None,
           "audience": req.audience, "text": text, "attachments": req.attachments, "simulated": req.simulated,
           "reserved_credits": float(reservation.amount), "previous_turn_id": previous_turn_id}
    # SQLAlchemy models permit non-mapped transient attributes. Keeping the
    # launch payload on the returned object ensures a failed commit cannot start
    # provider work or cancel an already-running turn.
    turn._blackmoa_launch_ids = ids
    return turn


async def announce_turn(db, *, owner_id: uuid.UUID, phase: str, turn_id: uuid.UUID, conversation_id: uuid.UUID,
                        agent_id: uuid.UUID, audience: str, **extra: Any) -> None:
    """A turn started or ended, told to every screen the owner has open (plan/69).

    Only ids and a status: the words are fetched, not carried, so the event stays small and
    a client that missed it still reaches the truth on its next read."""
    from blackmoa.core import bus

    data = {"phase": phase, "turn_id": str(turn_id), "conversation_id": str(conversation_id), "agent_id": str(agent_id),
            "audience": audience}
    for k, v in extra.items():
        if v is not None:
            data[k] = str(v) if isinstance(v, uuid.UUID) else v
    await bus.publish(db, owner_id=owner_id, kind="turn", data=data)


def launch_turn(turn: Turn) -> None:
    """Start provider work after the caller has successfully committed start_turn()."""
    ids = getattr(turn, "_blackmoa_launch_ids", None)
    if not ids:
        return  # idempotent replay of an existing turn
    previous = ids.get("previous_turn_id")
    if previous:
        old = journals.get(previous)
        if old and old.task and not old.task.done():
            old.task.cancel()
    j = journals.get(turn.id) or journals.create(turn.id)
    if j.task is None or j.task.done():
        j.task = asyncio.create_task(_run(ids, j), name=f"turn-{turn.id}")
    with contextlib.suppress(Exception):
        delattr(turn, "_blackmoa_launch_ids")


async def cancel_turn(turn_id: uuid.UUID) -> bool:
    j = journals.get(turn_id)
    if j and j.task and not j.task.done():
        j.task.cancel()
        return True
    return False


async def _run(ids: dict[str, Any], j: TurnJournal) -> None:
    turn_id: uuid.UUID = ids["turn_id"]
    t0 = time.monotonic()
    rt: AgentRuntime | None = None
    status = "failed"
    error_code: str | None = None
    error_msg: str | None = None
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0}
    usage_before: Any = None
    call_id: str | None = None
    ttft_ms: int | None = None
    tool_calls = 0
    fell_back = False
    cat = None
    #: 세션이 닫힌 뒤에도 읽어야 하는 값은 **문자열로 들고 나온다.**
    #:
    #: 세션 안에서 만든 ORM 행을 밖에서 읽으면, 그 세션이 되돌려졌을 때(=turn 이
    #: 실패했을 때) 속성이 만료돼 DetachedInstanceError 가 난다. 하필 그 자리가
    #: 실패를 기록하는 자리라, **진짜 원인이 이 오류에 덮여 사라졌다** — 금고 폴더
    #: 권한 문제가 "알 수 없음" 으로 보이던 일이 그렇게 났다.
    model_ref: tuple[str, str] | None = None
    # 이 턴이 밀어낸 앞 턴이 스스로 정리(대화 기록 고치기·저장)를 마칠 때까지 기다린다(plan/69). 둘은 같은 런타임과
    # 대화 상태를 쓴다 — 겹쳐 돌면 새 턴이 실패하거나, 앞 턴의 정리가 새 턴의 말을 기록에서 지웠다.
    prev = ids.get("previous_turn_id")
    if prev:
        pj = journals.get(prev)
        if pj is not None and pj.task is not None and not pj.task.done():
            with contextlib.suppress(Exception):
                await asyncio.wait({pj.task}, timeout=15)
    try:
        async with session_scope() as db:
            owner = await db.get(User, ids["owner_id"])
            agent = await db.get(Agent, ids["agent_id"])
            conv = await db.get(Conversation, ids["conversation_id"])
            visitor = await db.get(Visitor, ids["visitor_id"]) if ids["visitor_id"] else None
            if owner is None or agent is None or conv is None:
                raise BlackMoaError("turn resources disappeared", code="turn_resources_missing", status=409)
            plan = await P.plan_for_user(db, owner)
            # The plan, not just the catalog: an owner moved to a smaller plan keeps an
            # agent pinned to a model they may no longer use, and the turn has to land
            # somewhere they may.
            cat, fell_back = await CAT.resolve_for_plan(db, plan, agent.provider, agent.model_id)
            if cat is None:
                raise BlackMoaError("no model available", code="no_model_available", status=503)
            model_ref = (cat.provider, cat.model_id)
            if fell_back:
                agent.provider, agent.model_id = cat.provider, cat.model_id
                await J.enqueue(db, "notify.evaluate", {"event": "agent_model_fallback", "owner_id": str(owner.id), "agent_id": str(agent.id),
                                                        "payload": {"agent_name": agent.name, "text": f"{cat.display_name} 으로 변경"}},
                                dedupe_key=f"fallback:{agent.id}:{datetime.now(UTC):%Y%m%d}")
            rt = await runtimes.get_or_create(db, owner=owner, agent=agent, audience=ids["audience"], conversation=conv, cat=cat,
                                              plan=plan, visitor=visitor, turn_credit_cap=float(ids["reserved_credits"]))
            j.emit("turn.start", {"turn_id": str(turn_id), "conversation_id": str(conv.id), "model": cat.model_id, "provider": cat.provider})
            if fell_back:
                j.emit("notice", {"kind": "model_fallback", "message": f"설정한 모델을 쓸 수 없어 {cat.display_name} 으로 답합니다."})
            await _prepare_context(db, rt, owner, agent, visitor, turn_id, ids["text"], j)
        redactor = rt.ctx.stream_redactor
        # Every turn is recorded against the capacity it uses — provider, model and the
        # pooled account it is pinned to — so the LLM dashboard can say where load is
        # coming from rather than only that the machine is busy.
        call_id = LLM.manager.begin(provider=model_ref[0], model=model_ref[1], kind="turn",
                                    owner_id=str(ids["owner_id"]), agent_id=str(ids["agent_id"]),
                                    account=getattr(rt.claude_lease, "label", "") if rt.claude_lease else "")
        # 2) run
        async with rt.lock:
            rt.last_used = time.monotonic()
            rt.turn_count += 1
            _trim_history(rt)
            if not rt.vision and any(str(a.get("mime", "")).startswith("image/") for a in ids["attachments"] or []):
                await _caption_now(ids["attachments"])
            user_input = _build_input(rt, ids["text"], ids["attachments"], j)
            t_first = None
            usage_before = (rt.state.turn_token_usage, len(rt.state.turn_token_usage or []))
            # 도구를 부르기 전의 말과 부른 뒤의 말은 다른 문단이다. 그대로 이어 붙이면
            # "확인하겠습니다.하렴 님의…" 처럼 문장이 붙는다.
            after_tool = False
            # 멈추거나 밀려나 이 루프가 끊겨도 실행기의 흐름을 닫고 나서 자물쇠를 놓는다(plan/69). 닫지 않으면 실행기가
            # 대화 상태를 "아직 실행 중" 으로 들고 있어, 뒤이어 온 물음이 'already executing a run' 으로 실패했다.
            async with contextlib.aclosing(rt.pipeline.run_stream(user_input, rt.state)) as stream:
                async for ev in stream:
                    et = ev.type
                    d = ev.data or {}
                    if et == "text.delta":
                        if t_first is None:
                            t_first = time.monotonic()
                            ttft_ms = int((t_first - t0) * 1000)
                        chunk = d.get("text", "")
                        if (after_tool or j.broke) and chunk:
                            after_tool = j.broke = False
                            if j.answer and not j.answer.endswith(("\n", " ")) and not chunk.startswith(("\n", " ")):
                                chunk = "\n\n" + chunk
                        if redactor is not None:
                            # visitor: publish only text that no later token can turn into a
                            # private match (plan/19). The tail is flushed in _finalize.
                            chunk = redactor.feed(chunk)
                        if chunk:
                            j.emit("text.delta", {"text": chunk})
                    elif et == "thinking.delta":
                        j.thinking_chars += len(d.get("text", ""))
                        if ids["audience"] == "owner":
                            j.emit("thinking.delta", {"text": d.get("text", "")})
                        elif j.thinking_chars < 20:
                            j.emit("thinking.status", {"active": True})
                    elif et in ("tool.call_start", "api.tool_use"):
                        after_tool = True      # 어느 길로 부른 도구든(CLI 는 MCP 다리가 알린다) 문단이 바뀐다
                        if et == "api.tool_use" and d.get("source") == "cli":
                            continue
                        if et == "api.tool_use" and rt.pipeline is not None and d.get("source") == "internal":
                            continue
                        tool_calls += 1
                        name = d.get("name", "")
                        j.emit("tool.start", {"call_id": d.get("tool_use_id") or d.get("id"), "name": name, "label": tool_label(name), "label_en": tool_label_en(name),
                                              "input_preview": str(d.get("input", ""))[:200]})
                    elif et == "tool.call_complete":
                        j.emit("tool.end", {"call_id": d.get("tool_use_id"), "name": d.get("name"), "is_error": bool(d.get("is_error")),
                                            "duration_ms": d.get("duration_ms", 0)})
                    elif et == "api.ttft" and ttft_ms is None:
                        ttft_ms = int(d.get("ttft_ms") or 0)
                    elif et == "token.tracked":
                        pass
                    elif et == "api.error":
                        error_msg = str(d.get("message") or d.get("error") or "")[:500]
                        error_code = classify(error_msg, executor_code=d.get("code"))
                    elif et == "pipeline.error":
                        error_msg = str(d.get("error") or "")[:500]
                        error_code = classify(error_msg, executor_code=d.get("code"))
                    elif et == "pipeline.complete":
                        status = "completed"
                    elif et == "context.compacted":
                        j.emit("notice", {"kind": "compacted", "message": "긴 대화를 요약해 정리했어요."})
            _collect_usage(rt, usage_before, usage)
            answer = j.answer or (rt.state.final_text or "")
            if status != "completed" and answer and not error_code:
                status = "completed"
            if status != "completed" and not error_code:
                error_code = "unknown"
    except asyncio.CancelledError:
        status = "cancelled"
        if rt is not None:
            # 실행기는 모델 호출을 따로 도는 작업에서 한다. 읽던 쪽이 멈춰도 그 작업은 끝까지 돌았다 — [그만] 을 눌러도
            # 모델은 계속 일하고(비용), 그동안 대화 상태가 "실행 중" 이라 다음 물음이 실패했다. 그 작업을 멈추고
            # 끝나기를 기다린 뒤에 기록을 고친다(plan/69).
            await _stop_pipeline_run(rt)
            _collect_usage(rt, usage_before, usage)
            _repair_after_cancel(rt)
    except PaymentRequired as e:
        status, error_code, error_msg = "failed", e.code, e.message
    except BlackMoaError as e:
        status, error_code, error_msg = "failed", e.code, e.message
    except Exception as e:  # noqa: BLE001
        log.exception("turn crashed", turn_id=str(turn_id))
        status, error_code, error_msg = "failed", classify(str(e)), str(e)[:500]
        if rt is not None:
            _collect_usage(rt, usage_before, usage)
            _repair_after_cancel(rt)
    # 2b) tell the account pool how its leased account did. A rate limit or a dead session
    # has to take that account out of rotation, and this session has to let go of it, or
    # every following turn in this conversation walks into the same wall.
    with contextlib.suppress(Exception):
        if call_id is not None:
            LLM.manager.end(call_id, ok=(status == "completed"), code=error_code, error=error_msg or "",
                            input_tokens=int(usage.get("input_tokens", 0)), output_tokens=int(usage.get("output_tokens", 0)))
            call_id = None
        await _report_pool_outcome(rt, status, error_code, error_msg)
    # 3) persist (own session, never cancelled mid-way). A cancel arriving while we finalize is swallowed:
    # the shielded task keeps running and the journal is always released.
    try:
        await asyncio.shield(_finalize(ids, j, rt, model_ref, status, error_code, error_msg, usage, ttft_ms, tool_calls, t0))
    except asyncio.CancelledError:
        log.info("turn cancelled during finalize; persistence continues", turn_id=str(turn_id))
    except Exception:  # noqa: BLE001
        log.exception("finalize failed", turn_id=str(turn_id))
        with contextlib.suppress(Exception):
            async with session_scope() as db:
                await CR.release_turn(db, turn_id)
        if not j.done:
            j.emit("turn.error", {"code": "unknown", "message": user_message("unknown"), "retryable": True})
    finally:
        journals.forget(turn_id)


async def _report_pool_outcome(rt: AgentRuntime | None, status: str, error_code: str | None,
                               error_msg: str | None) -> None:
    if rt is None or rt.claude_lease is None:
        return
    # 사람이 멈췄거나 새 물음이 밀어낸 턴은 계정 탓이 아니다. 실패로 세면 [그만] 을 몇 번 누른 것만으로 계정이
    # 쉬러 들어가고, 이 대화의 런타임이 답하는 도중에 닫혔다(plan/69).
    if status == "cancelled":
        return
    from blackmoa.services import claude_pool as CP
    ok = status == "completed"
    code = None if ok else (error_code or "unknown")
    async with session_scope() as db:
        decision = await CP.report(db, rt.claude_lease, ok=ok, code=code, error=error_msg, release=False)
    if decision is not None and decision.status != "ready":
        # The account is no longer in rotation; drop the session so the next turn rebuilds
        # (and re-leases) instead of retrying against the same limited account.
        await runtimes.drop(rt.key)


def _collect_usage(rt: AgentRuntime, usage_before: Any, usage: dict) -> None:
    st = rt.state
    if usage_before is None:
        return
    prev_list, prev_len = usage_before
    if st.turn_token_usage is prev_list and len(st.turn_token_usage or []) == prev_len:
        return
    usage.update({"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0})
    for u in st.turn_token_usage or []:
        usage["input_tokens"] += int(u.input_tokens or 0)
        usage["output_tokens"] += int(u.output_tokens or 0)
        usage["cache_read"] += int(u.cache_read_input_tokens or 0)
        usage["cache_write"] += int(u.cache_creation_input_tokens or 0)
    usage["cost_usd"] = float(st.total_cost_usd or 0.0)


def _trim_history(rt: AgentRuntime) -> None:
    msgs = rt.state.messages
    if len(msgs) <= 80:
        return
    cut = len(msgs) - 60
    while cut < len(msgs) and msgs[cut].get("role") != "user":
        cut += 1
    rt.state.messages = msgs[cut:]


async def _stop_pipeline_run(rt: AgentRuntime) -> None:
    """이 런타임의 대화 상태로 도는 실행기 작업(run_stream 이 따로 띄운 것)을 멈추고 끝나기를 기다린다.

    실행기에는 멈추는 길이 따로 없고, 흐름을 버린 쪽이 있어도 작업은 계속 돈다(그렇게 설계돼 있다). 그 작업은
    자기 상태를 들고 있으므로 그것으로 찾는다 — 다른 대화의 작업은 건드리지 않는다.
    """
    state = rt.state
    me = asyncio.current_task()
    targets: list[asyncio.Task] = []
    for t in asyncio.all_tasks():
        if t is me or t.done():
            continue
        coro = t.get_coro()
        if not getattr(coro, "__qualname__", "").endswith("run_stream.<locals>._run_pipeline"):
            continue
        frame = getattr(coro, "cr_frame", None)
        try:
            owns = frame is not None and frame.f_locals.get("state") is state
        except Exception:  # noqa: BLE001
            owns = False
        if owns:
            targets.append(t)
    for t in targets:
        t.cancel()
    if targets:
        with contextlib.suppress(BaseException):
            await asyncio.wait(targets, timeout=5)


def _repair_after_cancel(rt: AgentRuntime) -> None:
    msgs = rt.state.messages
    while msgs and msgs[-1].get("role") == "user":
        msgs.pop()
    if msgs and msgs[-1].get("role") == "assistant" and isinstance(msgs[-1].get("content"), list):
        if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in msgs[-1]["content"]):
            msgs.pop()
            while msgs and msgs[-1].get("role") == "user":
                msgs.pop()


async def _caption_now(attachments: list[dict[str, Any]]) -> None:
    """그림을 못 보는 모델의 턴: 아직 설명이 없는 그림은 지금 적는다(서비스가 낸다, 결정 4).

    작업자의 읽기를 기다리면 이번 턴에는 설명이 없다. 한 장에 몇 초 — 그림을 무시한 답보다 낫다.
    적은 설명은 파일에 남겨 작업자가 두 번 적지 않게 한다.
    """
    from blackmoa.db.session import session_scope
    from blackmoa.models import AgentFile
    from blackmoa.services import files as FILES

    for a in attachments:
        if not str(a.get("mime", "")).startswith("image/") or a.get("caption") or not a.get("data"):
            continue
        try:
            async with session_scope() as db:
                f = await db.get(AgentFile, uuid.UUID(str(a["file_id"]))) if a.get("file_id") else None
                if f is not None and f.caption:
                    a["caption"] = f.caption
                    continue
                if f is None:
                    continue
                cap = await asyncio.wait_for(FILES.caption(db, f, base64.b64decode(a["data"])), timeout=45)
                if cap:
                    f.caption = cap
                    a["caption"] = cap
                await db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("caption on the spot failed", err=str(e)[:160])


def _build_input(rt: AgentRuntime, text: str, attachments: list[dict[str, Any]], j: TurnJournal) -> Any:
    ref = rt.blocks["memory"].text
    clamped = fit_input(text, ref, budget_tokens=int(rt.context_window or 200_000) // 2)
    if clamped.clamped:
        rt.blocks["memory"].text = clamped.reference_text
        j.emit("notice", {"kind": "input_clamped", "message": CLAMP_NOTICE_KO})
    imgs = [a for a in attachments if str(a.get("mime", "")).startswith("image/") and a.get("data")]
    files_txt = [a for a in attachments if a.get("text")]
    body = clamped.user_text

    def _fid(a: dict[str, Any]) -> str:
        # 파일 id 를 함께 적는다 (plan/55 §5-2): 다음 턴에 다시 열 수 있다는 것을 비서가 안다.
        return f' file_id="{a["file_id"]}"' if a.get("file_id") else ""

    if files_txt:
        body += "\n\n" + "\n\n".join(f"<attachment name=\"{a.get('filename','file')}\"{_fid(a)}>\n{str(a['text'])[:12000]}\n</attachment>" for a in files_txt)
    if imgs and not rt.vision:
        # 그림을 못 보는 모델이다. 그림 대신 작은 모델이 적은 설명을 싣고, 설명이라고 밝힌다.
        # 설명도 없으면 그림이 있었다는 사실만 — 모른 척 답하면 사진을 무시한 것처럼 보인다.
        lines = []
        for a in imgs:
            cap = str(a.get("caption") or "").strip()
            lines.append(f"<picture name=\"{a.get('filename','그림')}\"{_fid(a)}>(그림 설명) {cap}</picture>" if cap
                         else f"<picture name=\"{a.get('filename','그림')}\"{_fid(a)}>(설명 없음)</picture>")
        body += "\n\n" + "\n".join(lines) + ("\n<attachment_note>지금 모델은 그림을 직접 볼 수 없다. 위 설명만 근거로 삼고, "
                                               "설명에 없는 것은 짐작하지 말고 물어라.</attachment_note>")
        return body
    if imgs:
        body += "\n\n" + "\n".join(f"<picture name=\"{a.get('filename','그림')}\"{_fid(a)} />" for a in imgs[:8])
    if not imgs:
        return body
    return {"text": body, "images": [{"kind": "image", "mime_type": a["mime"], "data": a["data"]} for a in imgs[:8]]}



def _tz_of(owner):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(getattr(owner, "timezone", None) or "Asia/Seoul")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


def _visitor_identity(visitor, ctx) -> BP.VisitorIdentity | None:
    if visitor is None:
        return None
    known = getattr(ctx, "visitor_known_contact", "") or ""
    return BP.VisitorIdentity(display_name=visitor.display_name or "", email=visitor.email or "",
                              note=visitor.note or "", known_contact=known)


async def _prepare_context(db, rt: AgentRuntime, owner: User, agent: Agent, visitor: Visitor | None, turn_id: uuid.UUID,
                           text: str, j: TurnJournal) -> None:
    ctx = rt.ctx
    ctx.turn_id = turn_id
    ctx.owner, ctx.agent, ctx.visitor = owner, agent, visitor
    ctx.profile = await PF.shown(db, owner.id)
    # How close this visitor stands decides what the secretary may say, and what the
    # redactor still masks even if the model tries (plan/41 §8).
    from blackmoa.services import people as PPL

    viewer = "owner" if rt.audience != "visitor" else await PPL.viewer_level(
        db, owner.id, visitor.user_id if visitor is not None else None)
    ctx.viewer_level = viewer
    # 이 사람에게 무엇을 쓰는가 — 비서의 [지식] 탭이 정한 것을 턴마다 (plan/57). 도구·지시문·기억·
    # 파일이 모두 이것 하나를 본다. 나와의 대화면 전부.
    from blackmoa.services import outsider as OUT
    dis = await OUT.for_turn(db, agent, viewer)
    ctx.disclosure = dis
    # 금고도 같은 거리를 본다. 런타임은 대화마다 한 번 세워지지만 거리는 턴마다
    # 달라질 수 있다 — 이야기 도중에 인맥을 맺으면 그 턴부터 인맥이다.
    ctx.memory.viewer = viewer
    ctx.memory.share_public = dis.memory
    ctx.memory.share_own = dis.visitors
    visitor_name = PF.display_name(ctx.profile, owner, audience=rt.audience, policy=agent.disclosure_policy or {})
    ctx.private_literals = PF.private_literals(ctx.profile, agent.disclosure_policy or {}, viewer=viewer,
                                               share=dis.profile, keep=(visitor_name,))
    ctx.allowed_disclosures = set()
    if visitor is not None:
        # The visitor's own contact details are theirs to see echoed back — but a visitor
        # chooses these strings, so one of them being the owner's private phone number is a
        # visitor deciding what the redactor may let through. Never allow a value the
        # disclosure policy calls private, whoever claims it as their own.
        private = {x for x in (ctx.private_literals or []) if x}
        for own in (visitor.display_name, visitor.email):
            if own and len(own) >= 3 and str(own) not in private:
                ctx.allowed_disclosures.add(str(own))
    ctx.stream_redactor = StreamRedactor(ctx.private_literals, source=ctx) if rt.audience == "visitor" else None
    ctx.cards, ctx.used_memory, ctx.notices = [], [], []
    ctx.read_rooms = False
    ctx.emit = lambda t, d: j.emit(t, d)
    rt.provider.rebind(ctx)
    audience = rt.audience
    tz = ZoneInfo(owner.timezone or "Asia/Seoul")
    now = datetime.now(tz)
    prof = PF.render_profile(ctx.profile, agent.disclosure_policy or {}, audience, viewer=getattr(ctx, "viewer_level", ""),
                             share=dis.profile)
    pol = agent.disclosure_policy or {}
    extra = []
    if audience == "visitor":
        if pol.get("topics_private"):
            extra.append("Private topics (never discuss): " + ", ".join(pol["topics_private"]))
        if pol.get("topics_public"):
            extra.append("Topics the owner is happy to discuss: " + ", ".join(pol["topics_public"]))
        # 연락처는 [정보] 의 칸이다 — 위 프로필 블록에 있으면 말해도 되고, 없으면 없는 것이다 (plan/57).
        # 예전에는 "연락처 공유" 규칙이 따로 있어, 블록에 이메일이 있으면서 "알려 주지 마라" 가 함께 적혔다.
        extra.append("When you cannot answer: "
                     f"{'offer to take a message' if pol.get('unknown_policy', 'offer_message') == 'offer_message' else 'say you do not know'}.")
    # Layer 1's owner section, rebuilt with this turn's profile and disclosure policy.
    owner_ident = rt.owner_identity or BP.OwnerIdentity(
        name=PF.display_name(ctx.profile, owner, audience=audience, policy=agent.disclosure_policy or {}),
                                                        timezone=owner.timezone or "Asia/Seoul", locale=owner.locale or "ko")
    resources = rt.resources or BP.Resources()
    if rt.resources is not None and "base_resources" in rt.blocks:
        # 스케줄·연락 규칙, 그리고 외부인에게 쓰는 것은 턴마다 새로 (plan/56, plan/57). 글이 같으면 캐시는 그대로다.
        from blackmoa.pipeline.runtime import refresh_outsider
        with contextlib.suppress(Exception):
            await refresh_outsider(db, rt.resources, owner, agent, audience, ctx.profile, dis)
            rt.blocks["base_resources"].text = BP._resources_section(rt.resources, audience)
    rt.blocks["base_owner"].text = BP.owner_section(owner_ident, prof, audience, resources) + (
        "\n\n## Disclosure settings for this conversation\n" + "\n".join(extra) if extra else "")
    if "base_visitor" in rt.blocks:
        if visitor is not None and visitor.matched_node_id:
            with contextlib.suppress(Exception):
                node = await N.get_node(db, owner.id, visitor.matched_node_id)
                # 이 사람에 대해 적어 둔 것은 [지식] 탭의 인맥 줄이 그 사람을 골랐을 때만 (plan/57).
                if dis.network is not None and dis.network.has(node.id):
                    d = N.node_dict(node, viewer=ctx.viewer_level)
                    company = (d["attrs"] or {}).get("company", "")
                    ctx.visitor_known_contact = d["name"] + (f" ({company})" if company else "") + (f", tags: {', '.join(d['tags'])}" if d["tags"] else "")
        block = BP.VISITOR_HEADER + BP.visitor_section(_visitor_identity(visitor, ctx))
        # Answered where it was asked: a claim of ownership made in the visitor's last
        # sentence is met by a line in the block right next to it, for this turn only.
        if claims_to_be_owner(text):
            block += BP.IMPERSONATION_NOTICE
        rt.blocks["base_visitor"].text = block
    rt.blocks["facts"].text = await _facts_block(db, owner.id, agent.id, dis, visitor.id if visitor else None, text)
    if "files" in rt.blocks:
        # 받은 파일의 목록 (plan/55 §5-2). 바이트가 아니라 한 줄씩 — 필요하면 도구로 연다.
        from blackmoa.services import files as FILES
        try:
            rt.blocks["files"].text = await FILES.prompt_block(db, ctx, _tz_of(owner))
        except Exception:  # noqa: BLE001
            rt.blocks["files"].text = ""
    # plan/38: one side of a secretary-to-secretary exchange — who the other secretary is,
    # what this is for, how much budget is left, and when to stop.
    if "relay" in rt.blocks:
        rt.blocks["relay"].text = ""
        if ctx.relay_id:
            try:
                rt.blocks["relay"].text = await RELAY.prompt_block(db, ctx.relay_id, rt.conversation_id, agent, owner)
            except Exception as e:  # noqa: BLE001
                log.warning("relay block failed", err=str(e)[:160])
    # plan/37: how far this pair has come, and what that means for this turn. Owner only —
    # a visitor is not in a relationship with the secretary.
    if audience == "owner" and "relationship" in rt.blocks:
        try:
            rel = await REL.get(db, owner.id, agent.id)
            rt.blocks["relationship"].text = REL.prompt_block(rel, agent, owner, opened_with=await REL.opened_with(db, rt.conversation_id))
        except Exception as e:  # noqa: BLE001
            log.warning("relationship block failed", err=str(e)[:160])
            rt.blocks["relationship"].text = ""
    live = [f"# Now\n{now.strftime('%Y-%m-%d %A %H:%M')} ({owner.timezone or 'Asia/Seoul'})"]
    if audience == "owner":
        bal = await CR.available_balance(db, owner.id)
        live.append(f"Credits available: {float(bal):.1f}")
        # 다가오는 일정은 스케줄에서(black-moa + Google), 안 읽은 메일은 [메일] 에서 — Google 에 직접 닿지 않는다 (plan/57).
        with contextlib.suppress(Exception):
            from blackmoa.services import schedule as SCH
            evs = await SCH.events_between(db, owner, now.astimezone(UTC), (now + timedelta(days=1)).astimezone(UTC), limit=6)
            if evs:
                live.append("Upcoming (24h): " + "; ".join(
                    f"{'all day' if e['all_day'] else datetime.fromisoformat(e['start']).astimezone(tz).strftime('%m/%d (%a) %H:%M')} {e['title']}"
                    for e in evs))
        if "feature:mail" in ctx.features:
            with contextlib.suppress(Exception):
                from blackmoa.services import mail as MAIL
                unread = await MAIL.recent_unread(db, owner.id, days=2, limit=5)
                if unread:
                    live.append("Unread recent mail: " + "; ".join(f"{m['from'][:30]}: {m['subject'][:50]}" for m in unread))
        st = await N.stats(db, owner.id)
        rec = await N.recent(db, owner.id, 5)
        summ = N.render_summary(st, rec)
        if summ:
            live.append(summ)
    if audience == "owner" and text:
        try:
            hits = await N.search(db, owner.id, text[:60], limit=2) if len(text) < 60 else []
            for h in hits:
                if h["score"] >= 0.8:
                    live.append(f"Mentioned contact: {h['name']} — {h.get('attrs', {}).get('title', '')} {h.get('attrs', {}).get('company', '')}; tags {h['tags']}")
        except Exception:
            pass
    rt.blocks["live"].text = "\n".join(live)
    mem_txt = ""
    try:
        mem_txt = await asyncio.wait_for(ctx.memory.context_block(text, max_chars=2400), timeout=6)
        pinned = await asyncio.wait_for(ctx.memory.pinned_text(1000), timeout=3)
    except Exception:
        pinned = ""
    # 비서는 내 지식을 본다 (plan/48 §2). 예전에는 비서 설정의 [지식] 능력이 이
    # 조회를 통째로 건너뛰게 했다. 그건 "어디까지 나가나" 가 아니라 "비서가 아느냐"
    # 를 비서 설정에서 정하는 것이라 철학에 어긋났다. 범위는 `viewer` 가 가른다.
    kn_txt = ""
    qvec = None
    try:
        qvec = await asyncio.wait_for(K.embed_query(db, text), timeout=4) if text.strip() else None
    except Exception:  # noqa: BLE001
        qvec = None
    try:
        hits = await asyncio.wait_for(K.search(db, owner.id, text, k=3, scope=dis.knowledge, qvec=qvec), timeout=6)
        kn_txt = "\n".join(f"- [{h['title']}{(' › ' + h['heading']) if h.get('heading') else ''}] {h['text'][:500]}" for h in hits if h.get("score", 0) >= 0.25)
    except Exception:
        kn_txt = ""
    # 받은 파일의 본문도 같은 줄에서 찾는다 (plan/55 P4). 어느 파일의 어느 대목인지 밝혀
    # 비서가 file_read 로 더 읽을 수 있게 한다. 벽은 visible_to 하나.
    try:
        from blackmoa.services import files as FILES
        fconds = FILES.visible_to(ctx)
        if rt.audience == "owner":
            # 주인 대화에 저절로 실리는 것은 주인이 준 파일뿐이다. 방문자가 준 파일의 글은
            # 남이 쓴 글이라, 비서가 일부러 열 때(<untrusted> 로 싸여서)만 들어온다.
            from blackmoa.models import AgentFile
            fconds.append(AgentFile.scope == "owner")
        fhits = await asyncio.wait_for(FILES.search(db, fconds, text, k=2, qvec=qvec), timeout=6) if text.strip() else []
        ftxt = "\n".join(f"- [file {h['filename']} · file_id {h['file_id']}{(' · p.' + str(h['page'])) if h.get('page') else ''}] {h['text'][:500]}"
                         for h in fhits if h.get("score", 0) >= 0.25)
        if ftxt:
            kn_txt = (kn_txt + "\n" + ftxt).strip()
    except Exception:  # noqa: BLE001
        pass
    parts = []
    if pinned:
        parts.append("# Pinned memory\n" + pinned)
    if mem_txt:
        parts.append("# Relevant memory (retrieved for this message)\n" + mem_txt)
    if kn_txt:
        parts.append("# Reference material (retrieved)\n" + kn_txt)
    rt.blocks["memory"].text = "\n\n".join(parts)
    if mem_txt or kn_txt:
        j.emit("memory.retrieved", {"chars": len(mem_txt) + len(kn_txt)})


async def _facts_block(db, owner_id: uuid.UUID, agent_id: uuid.UUID, dis, visitor_id: uuid.UUID | None, text: str) -> str:
    """**이 비서가** 알게 된 사실 중, 지금 듣는 사람에게 보여도 되는 것만.

    사실은 비서가 대화에서 만들어 낸 것이라 그 비서의 것이다. 기억이 비서별 금고에
    사는 것과 같은 이유다. 주인이 직접 넣은 것(프로필·지식·인맥·내 글)은 [내 정보] 에
    있고 **모든 비서가 전부 본다** — 그쪽이 원장이고, 이쪽은 비서가 겪은 것이다
    (plan/49).

    거리를 셋으로 본다. 주인은 제 것을 전부 보고, 인맥은 [모두 공개]와 [인맥에게만]
    까지, 남은 [모두 공개]만. 예전에는 주인이냐 아니냐 둘로만 갈라서, 인맥에게만
    공개한 사실이 인맥에게도 안 갔다.

    `visitor_private` 은 범위가 아니라 **그 방문자에 대한 사실**이라는 표시다. 그래서
    범위 판정을 태우지 않고 따로 걸러 낸다. 주인의 턴에서는 빼는데, 손님에 대한
    메모가 주인의 원장에 섞이면 그때부터 원장이 아니다.

    외부인 대화에서는 비서의 [지식] 탭 기억 줄이 한 번 더 가른다 (plan/57): 공개로 둔
    사실은 ``memory``, 그 방문자에 대한 사실은 ``visitors`` 가 켜져 있을 때만.
    """
    from sqlalchemy import false, or_

    from blackmoa.core import visibility as VIS

    viewer = dis.viewer
    # 주인이 아닌 비서가 알게 된 것은 이 비서에게 없는 사실이다. `agent_id` 가 비어
    # 있는 옛 행은 누구의 것도 아니므로 모두에게 남긴다(운영에는 없다).
    stmt = select(Fact).where(Fact.owner_id == owner_id, Fact.status == "active",
                              (Fact.agent_id == agent_id) | (Fact.agent_id.is_(None)))
    if viewer == "owner":
        stmt = stmt.where(Fact.visibility != "visitor_private")
    else:
        conds = [Fact.visibility.in_(VIS.readable_levels(viewer))] if dis.memory else []
        if visitor_id and dis.visitors:
            conds.append((Fact.visibility == "visitor_private") & (Fact.visitor_id == visitor_id))
        stmt = stmt.where(or_(*conds) if conds else false())
    rows = (await db.execute(stmt.order_by(Fact.confidence.desc(), Fact.updated_at.desc()).limit(30))).scalars().all()
    if not rows:
        return ""
    lines = ["# Known facts (structured ledger)"]
    for f in rows:
        tag = " (visitor-private)" if viewer != "owner" and f.visibility == "visitor_private" else ""
        lines.append(f"- {f.subject} {f.predicate} {f.object}{tag}")
    return "\n".join(lines)[:2500]


async def _finalize(ids, j: TurnJournal, rt: AgentRuntime | None, model_ref: tuple[str, str] | None, status: str,
                    error_code: str | None, error_msg: str | None,
                    usage: dict, ttft_ms: int | None, tool_calls: int, t0: float) -> None:
    turn_id = ids["turn_id"]
    async with session_scope() as db:
        turn = (await db.execute(select(Turn).where(Turn.id == turn_id).with_for_update())).scalars().first()
        if turn is None:
            await CR.release_turn(db, turn_id)
            return
        # A replacement turn may have cancelled this row while provider work was
        # winding down. Never let a late finalize resurrect it as completed.
        if turn.status == "cancelled" and status == "completed":
            status = "cancelled"
            error_code = error_code or turn.error_code or "superseded"
        conv = await db.get(Conversation, ids["conversation_id"])
        owner = await db.get(User, ids["owner_id"])
        agent = await db.get(Agent, ids["agent_id"])
        if conv is None or owner is None or agent is None:
            await CR.release_turn(db, turn_id)
            turn.status = "failed"
            turn.error_code = "turn_resources_missing"
            turn.ended_at = datetime.now(UTC)
            return
        if rt is not None and rt.ctx.stream_redactor is not None:
            tail = rt.ctx.stream_redactor.flush()
            if tail:
                j.emit("text.delta", {"text": tail})
        answer = j.answer
        redactions = rt.ctx.stream_redactor.count if (rt is not None and rt.ctx.stream_redactor is not None) else 0
        if rt is not None and ids["audience"] == "visitor" and answer:
            allowed = set(rt.ctx.allowed_disclosures)
            prof = rt.ctx.profile
            for sub, val in ((prof.data or {}).get("contact") or {}).items():
                if val and PF.field_visibility(prof, agent.disclosure_policy or {}, f"contact.{sub}") == "public":
                    allowed.add(str(val))
            # second pass over the assembled answer: idempotent belt to the streaming pass
            answer, extra = redact_response(answer, rt.ctx.private_literals, allowed_literals=list(allowed))
            redactions += extra
            if redactions:
                j.emit("guard.redacted", {"count": redactions})
        cards = list(rt.ctx.cards) if rt is not None else []
        turn.status = status
        turn.ended_at = datetime.now(UTC)
        turn.duration_ms = int((time.monotonic() - t0) * 1000)
        turn.ttft_ms = ttft_ms
        turn.tool_call_count = tool_calls
        turn.input_tokens, turn.output_tokens = usage["input_tokens"], usage["output_tokens"]
        turn.cache_read_tokens, turn.cache_write_tokens = usage["cache_read"], usage["cache_write"]
        turn.cost_usd = usage["cost_usd"]
        turn.redactions = redactions
        turn.answer_text = answer[:20000]
        # 값을 매기려면 카탈로그 행이 필요하다. **이 세션에서 다시 읽는다** — 턴을
        # 돌린 세션의 행을 들고 오면 실패한 턴에서는 그 행이 만료돼 있다.
        cat = await CAT.get_model(db, model_ref[0], model_ref[1]) if model_ref else None
        if model_ref is not None:
            turn.provider, turn.model_id = model_ref[0], model_ref[1]
        actual_credits = CR.llm_credits(cat, usage["input_tokens"], usage["output_tokens"], usage["cache_read"], usage["cache_write"])
        balance_after = await CR.available_balance(db, owner.id)
        charged_credits = actual_credits
        if actual_credits > 0 and cat is not None:
            balance_after, charged_credits = await CR.settle_turn(
                db, owner_id=owner.id, agent_id=agent.id, turn_id=turn.id, provider=model_ref[0], model_id=model_ref[1],
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"], cache_read=usage["cache_read"],
                cache_write=usage["cache_write"], cost_usd=usage["cost_usd"], credits=actual_credits, audience=ids["audience"])
            if charged_credits < actual_credits:
                log.error("provider usage exceeded reserved turn cap", turn_id=str(turn.id), actual=float(actual_credits),
                          charged=float(charged_credits), reserved=ids.get("reserved_credits"))
        else:
            balance_after = await CR.release_turn(db, turn.id)
            charged_credits = CR.q(0)
        turn.credits = charged_credits
        msg = None
        if answer or cards:
            msg = await add_message(db, conv, role="assistant", content=answer, turn_id=turn.id, cards=cards)
        if ids["audience"] == "visitor" and not ids["simulated"]:
            conv.unread_owner = True
            if ids["visitor_id"]:
                v = await db.get(Visitor, ids["visitor_id"])
                if v:
                    v.turn_count = (v.turn_count or 0) + 1
                    v.last_seen_at = datetime.now(UTC)
            if ids["share_link_id"]:
                link = await db.get(ShareLink, ids["share_link_id"])
                if link:
                    link.turn_count = (link.turn_count or 0) + 1
                    link.last_visit_at = datetime.now(UTC)
            if conv.message_count <= 2 and status == "completed":
                await J.enqueue(db, "notify.evaluate", {"event": "visitor_new_conversation", "owner_id": str(owner.id), "agent_id": str(agent.id),
                                                        "payload": {"agent_name": agent.name, "text": ids["text"][:300], "conversation_id": str(conv.id)}},
                                dedupe_key=f"newconv:{conv.id}")
        if status == "completed" and ids["audience"] == "owner" and not ids["simulated"]:
            try:
                _rel, new_ms = await REL.record_turn(db, owner=owner, agent=agent)
                if new_ms:
                    pending_rel = {"agent_id": str(agent.id), "stage": _rel.stage, "milestones": new_ms, "days_together": REL.days_together(_rel)}
                else:
                    pending_rel = None
            except Exception as e:  # noqa: BLE001
                log.warning("relationship record failed", err=str(e)[:160])
                pending_rel = None
        else:
            pending_rel = None
        if status == "completed" and rt is not None:
            if rt.ctx.used_memory:
                with contextlib.suppress(Exception):
                    await rt.ctx.memory.learn(ids["text"], rt.ctx.used_memory)
            # A relay turn is two machines talking; there is nothing about the owner in it to
            # distil, and the distillation would cost the owner credits (plan/38 §5).
            #
            # A simulated turn is not the owner speaking either. The secretary answering a
            # post it was named in is handed an errand ("somebody called you on a post, write
            # a comment") and the post itself, which may be **somebody else's**. Distilling
            # that stored the errand as a fact about the owner ("사용자 / 요청하다 / 글에 대한
            # 댓글 작성") and let another person's writing become facts about mine. What a
            # post teaches the secretary comes from the secretary reading it on purpose
            # (plan/45 §3), not from the machinery that made it write a comment.
            #
            # 사람끼리 방을 읽은 턴도 증류하지 않는다 (plan/55 §6-4). 증류가 상대의 말을
            # 사실로 적어 두면 허락을 거둬도 비서는 계속 안다 — 그건 거둔 것이 아니다.
            # 주인이 "기억해" 라고 하면 그때 비서가 memory_remember 로 적는다.
            if rt.ctx.read_rooms:
                # 이 대화가 사람끼리 방을 읽었다는 표시. CLI 모델은 도구 기록이 남지만 API 모델은
                # 남지 않는다 — 어느 길이든 뒤 턴의 증류가 이 표시를 보고 멈춘다(distill._read_a_room).
                seen = (await db.execute(select(ToolSpan.id).where(ToolSpan.turn_id == turn.id,
                                                                   ToolSpan.name.like("%room_read")).limit(1))).first()
                if seen is None:
                    db.add(ToolSpan(turn_id=turn.id, owner_id=turn.owner_id, name="room_read", input={"marker": True},
                                    output_preview="", is_error=False, duration_ms=0, started_at=datetime.now(UTC)))
            if conv.kind != "agent" and not ids["simulated"] and not rt.ctx.read_rooms:
                await J.enqueue(db, "memory.distill", {"turn_id": str(turn.id)}, priority=6, delay_s=2, owner_id=ids["owner_id"])
        if conv.kind == "agent" and conv.relay_id:
            try:
                await RELAY.after_turn(db, conv, turn, answer, status)
            except Exception as e:  # noqa: BLE001
                log.warning("relay after_turn failed", relay_id=str(conv.relay_id), err=str(e)[:200])
        pending: list[tuple[str, dict]] = []
        if pending_rel:
            pending.append(("relationship.milestone", pending_rel))
        if status == "completed":
            pending.append(("usage", {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "cache_read": usage["cache_read"],
                                      "credits": float(charged_credits), "balance_after": float(balance_after)}))
            pending.append(("turn.complete", {"turn_id": str(turn.id), "message_id": str(msg.id) if msg else None, "stop_reason": "end_turn",
                                              "duration_ms": turn.duration_ms, "ttft_ms": ttft_ms, "redactions": redactions,
                                              "answer": answer if redactions else None}))
        elif status == "cancelled":
            # 새 물음이 이 턴을 밀어냈다면(start_turn 이 "superseded" 로 적었다) 그 까닭을 지우지 않는다 —
            # 다른 화면들이 "다른 곳에서 새로 물어 멈췄어요" 로 보여야 한다(plan/69).
            turn.error_code = error_code or turn.error_code or "cancelled"
            # 왜 멈췄는가: 누가 [그만] 을 눌렀다(cancelled), 다른 화면에서 새로 물었다(superseded).
            pending.append(("turn.cancelled", {"turn_id": str(turn.id), "partial": bool(answer), "reason": turn.error_code}))
        else:
            turn.error_code = error_code or "unknown"
            turn.error_message = error_msg
            code = error_code or "unknown"
            pending.append(("turn.error", {"code": code, "message": user_message(code, owner.locale or "ko"), "retryable": retryable(code)}))
            log.warning("turn failed", turn_id=str(turn.id), code=code, err=(error_msg or "")[:300])
        # 끝났다 — 따라 보던 다른 화면들이 저장된 말로 맞춘다(plan/69). 이 트랜잭션과 함께 커밋될 때 나간다.
        await announce_turn(db, owner_id=owner.id, phase="end", turn_id=turn.id, conversation_id=conv.id, agent_id=agent.id,
                            audience=ids["audience"], status=status,
                            reason=turn.error_code if status != "completed" else None,
                            message_id=msg.id if msg else None)
    for t, d in pending:
        j.emit(t, d)


async def record_tool_span(turn_id: uuid.UUID, owner_id: uuid.UUID, name: str, input_: dict, output_preview: str, is_error: bool,
                           duration_ms: int) -> None:
    async with session_scope() as db:
        db.add(ToolSpan(turn_id=turn_id, owner_id=owner_id, name=name, input=_shrink(input_), output_preview=output_preview[:2000],
                        is_error=is_error, duration_ms=duration_ms, started_at=datetime.now(UTC)))


def _shrink(d: Any) -> Any:
    try:
        import json
        s = json.dumps(d, ensure_ascii=False, default=str)
        return d if len(s) < 4000 else {"_truncated": s[:4000]}
    except Exception:
        return {}
