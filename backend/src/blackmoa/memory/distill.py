"""Post-turn distillation (worker): turn → facts + note + network proposals (plan/08 §쓰기 경로)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.logging import get_logger
from blackmoa.memory.facade import AgentMemory
from blackmoa.memory.notes import overlap
from blackmoa.models import Agent, Fact, Message, Turn, User
from blackmoa.providers.llm.simple import complete, extract_json
from blackmoa.services import credits as CR
from blackmoa.services import network as N
from blackmoa.services import settings as S

log = get_logger("blackmoa.distill")

SYSTEM = """You are a memory distiller for a personal secretary agent. Read ONE conversation turn between {speaker} and the secretary of the owner ({owner}).
Extract durable information only. Output strict JSON:
{{
 "facts": [{{"subject": str, "predicate": str, "object": str, "kind": "identity|preference|relationship|commitment|context|knowledge", "confidence": 0-1, "visibility_hint": "public|private"}}],
 "note": {{"title": str, "body": str, "category": "conversations|observations|decisions|people", "tags": [str], "importance": "high|medium|low"}} | null,
 "people": [{{"name": str, "kind": "person|organization", "company": str|null, "title": str|null, "relation_hint": str|null, "confidence": 0-1}}]
}}
Rules:
- Facts are atomic and about the owner or their world (not about the assistant). Never store the secretary's personality or tone as a fact.
- Write subject, predicate and object in the CONVERSATION'S language. A Korean conversation must not produce English facts.
- {audience_rule}
- The secretary already recorded these during the conversation. Do NOT repeat any of them, in any language or wording:
{known}
- note: ONLY if the turn leaves something that will still matter next week. Body ≤ 600 chars, in the conversation's language. Otherwise null.
  A note IS worth writing for: a decision made, a preference or habit revealed, a state that will be acted on later
  ("no contact details for X yet, so it was not sent"), new information about a person or relationship.
  A note is NOT worth writing for: the fact that an errand happened ("asked to comment on the post", "asked to describe
  the photo"), instructions given to the secretary quoted back, a question that this turn already answered and closed,
  or anything about the secretary's own tone or personality. If the turn was only an errand, note is null.
- These notes already exist for THIS conversation. If your note would say the same thing as one of them, return null
  instead — the existing one will be extended:
{notes_here}
- people: only newly mentioned real people/organizations with enough identity to be useful; never the owner or the secretary.
- If nothing durable: {{"facts": [], "note": null, "people": []}}"""

OWNER_RULE = "Speaker is the owner: facts default to visibility private unless clearly public (job title, public links)."
VISITOR_RULE = ("Speaker is an external visitor: facts describe the VISITOR (subject = visitor's name or 'visitor'); visibility_hint must be 'private'. "
                "Do not create facts about the owner from a visitor's claims.")


async def _already_known(db: AsyncSession, owner_id: uuid.UUID, turn_id: uuid.UUID) -> str:
    """The facts the distiller must not produce again, as compact lines for the prompt."""
    rows = (await db.execute(
        select(Fact.subject, Fact.predicate, Fact.object, Fact.source_turn_id)
        .where(Fact.owner_id == owner_id, Fact.status == "active")
        .order_by(Fact.created_at.desc()).limit(80))).all()
    # This turn's own first, since those are the ones the model is most likely to restate.
    rows = sorted(rows, key=lambda r: r[3] != turn_id)
    return "\n".join(f"  - {r[0]} / {r[1]} / {str(r[2])[:80]}" for r in rows[:50])


#: 같은 이야기로 볼 겹침. 운영에 쌓인 것으로 직접 재서 정했다.
#:
#:   실제 중복 ("스완과의 연락 시도" 두 개)        0.32 · 0.43
#:   같은 일을 다른 말로 적은 것                   0.20
#:   무관한 짧은 문장 (어미만 겹침)                0.17
#:
#: 0.30 은 실제 중복을 잡고 무관한 것과는 떨어져 있다. 가운데 0.20 구간은 자동으로
#: 합치지 않는다 — 거기서 무관한 것을 합치면 기억을 잃고, 그건 되돌릴 수 없다.
#: 그 구간은 프롬프트가 맡는다: 이 대화에 이미 적어 둔 것을 모델에게 보여 주고 같은
#: 말이면 쓰지 말라고 한다.
SAME_STORY = 0.30


#: 이어 붙여 자란 기억의 상한. 한 줄이 끝없이 자라면 꺼내 쓸 수 없다.
NOTE_MAX = 4000


def _merged_body(old: str, new: str) -> str:
    """같은 이야기에 오늘 줄을 **잇는다** (plan/50 §2).

    덮어쓰면 옛 줄에만 있던 것이 사라진다. "연락처가 없어 못 보냈다" 위에 "보냈다"
    를 덮으면 왜 늦었는지가 없어지고, 그건 되돌릴 수 없다. 이야기가 진행된 것이니
    뒤에 붙이고, 이미 적힌 말이면 아무것도 하지 않는다.

    자라기만 하는 줄은 결국 못 읽으므로, 상한에 닿으면 **가장 오래된 토막부터**
    내보낸다. 무엇을 버릴지 골라야 한다면 오래된 쪽이다.
    """
    old_s, new_s = (old or "").strip(), (new or "").strip()
    if not old_s:
        return new_s[:NOTE_MAX]
    if not new_s or new_s in old_s:
        return old_s[:NOTE_MAX]
    parts = [p.strip() for p in old_s.split("\n\n") if p.strip()] + [new_s]
    out = "\n\n".join(parts)
    while len(out) > NOTE_MAX and len(parts) > 1:
        parts.pop(0)
        out = "\n\n".join(parts)
    return out[:NOTE_MAX]


def _same_story(title: str, body: str, here: list[Any]) -> Any | None:
    """이 대화에 이미 같은 이야기가 적혀 있나 (plan/50 §2).

    제목이 같으면 같은 이야기다 — 운영의 중복 쌍은 제목이 글자 그대로 같았다.
    제목이 달라도 본문이 많이 겹치면 같은 이야기로 본다.
    """
    want = (title or "").strip().lower()
    for n in here:
        if (n.title or "").strip().lower() == want:
            return n
    best, score = None, 0.0
    for n in here:
        sc = overlap(body, n.body or "")
        if sc > score:
            best, score = n, sc
    return best if score >= SAME_STORY else None


async def _read_a_room(db: AsyncSession, conversation_id: Any) -> bool:
    from sqlalchemy import text as _text
    row = (await db.execute(_text("""
        SELECT 1 FROM tool_spans s JOIN turns t ON t.id = s.turn_id
         WHERE t.conversation_id = :c
           AND (s.name LIKE '%room_read' OR (s.name LIKE '%file_%' AND s.input::text LIKE '%room:%'))
         LIMIT 1"""), {"c": conversation_id})).first()
    return row is not None


async def distill_turn(db: AsyncSession, turn_id: uuid.UUID) -> dict[str, Any]:
    if not await S.get(db, "memory.distill_enabled"):
        return {"skipped": "disabled"}
    turn = await db.get(Turn, turn_id)
    if turn is None or turn.status != "completed" or not (turn.user_text or turn.answer_text):
        return {"skipped": "no_turn"}
    # **막는 자리는 여기 하나다** (plan/50 §2). 부르는 쪽에서 거르면 다른 경로로 증류를
    # 부르는 코드가 생기는 순간 다시 샌다. 심부름 지시문이 주인이 한 말로 기억되면,
    # 코드에 적힌 문장이 주인에 대한 사실이 된다.
    if turn.simulated:
        return {"skipped": "simulated"}
    # 사람끼리 방을 허락받아 읽은 대화는 증류하지 않는다 — 읽은 그 턴만이 아니라 그 뒤의
    # 턴도 (plan/55 §6-4, 결정 3-b). 뒤 턴의 답이 "보증금은 500만원이었죠" 처럼 방의 말을
    # 되풀이하면 그것이 사실로 적히고, 허락을 거둬도 비서는 계속 알게 된다.
    if await _read_a_room(db, turn.conversation_id):
        return {"skipped": "room_read"}
    owner = await db.get(User, turn.owner_id)
    agent = await db.get(Agent, turn.agent_id)
    if owner is None or agent is None:
        return {"skipped": "orphan"}
    if (await CR.balance(db, owner.id)) <= 0:
        return {"skipped": "no_credits"}
    # 다시 온 사람을 기억하지 않는 비서는 방문자와의 대화에서 기억을 적지 않는다 (plan/57, [지식] 탭 기억 줄).
    from blackmoa.services import outsider as OUT
    if turn.audience == "visitor" and not OUT.settings(agent)["visitors"]:
        return {"skipped": "visitor_memory_off"}
    convo = f"[{ 'owner' if turn.audience == 'owner' else 'visitor'}]: {turn.user_text[:4000]}\n[secretary]: {turn.answer_text[:4000]}"
    provider = await S.get(db, "memory.distill_provider")
    model = await S.get(db, "memory.distill_model")
    owner_name = owner.display_name
    # What the agent wrote down for itself during the turn, plus what this owner already
    # knows. Without it the distiller re-derives the same facts from the same text and the
    # near-duplicate survives, because "팀 회의 시간" and "has team meeting" are not equal to
    # any deduplication that compares strings: one turn produced every fact twice, once in
    # each language.
    known = await _already_known(db, owner.id, turn.id)
    visitor_id = None
    if turn.audience == "visitor":
        from blackmoa.models import Conversation
        conv = await db.get(Conversation, turn.conversation_id)
        visitor_id = conv.visitor_id if conv else None
    mem = AgentMemory(agent.id, turn.audience, visitor_id)
    here = await mem.recent_in_conversation(str(turn.conversation_id))
    system = SYSTEM.format(speaker="the owner" if turn.audience == "owner" else "an external visitor", owner=owner_name,
                           audience_rule=OWNER_RULE if turn.audience == "owner" else VISITOR_RULE,
                           known=known or "  (nothing yet)",
                           notes_here="\n".join(f"  - {n.title}: {n.body.splitlines()[0][:90] if n.body else ''}" for n in here[:8])
                                      or "  (none yet)")
    try:
        text, usage = await complete(db, provider=provider, model=model, system=system, user_text=convo, max_tokens=1200, timeout_s=150)
    except Exception as e:  # noqa: BLE001
        log.warning("distill llm failed", err=str(e)[:200])
        return {"error": str(e)[:200]}
    data = extract_json(text)
    if not isinstance(data, dict):  # the model may answer with a bare list / prose → treat as "nothing durable"
        data = {}
    # charge (small)
    try:
        from blackmoa.services import catalog as CAT
        cat = await CAT.get_model(db, provider, model) or await CAT.default_model(db)
        credits = CR.llm_credits(cat, usage.get("input_tokens", 0), usage.get("output_tokens", 0)) if usage else 0
        if credits and float(credits) > 0:
            await CR.charge_usage(db, owner_id=owner.id, kind="summary", credits=credits, provider=provider, model_id=model, agent_id=agent.id, note="memory distill")
    except Exception:
        pass
    n_facts = n_people = 0
    facts_in = data.get("facts")
    for f in (facts_in if isinstance(facts_in, list) else [])[:12]:
        if not isinstance(f, dict):
            continue
        try:
            subj, pred, obj = str(f["subject"]).strip()[:200], str(f["predicate"]).strip()[:200], str(f["object"]).strip()[:2000]
        except Exception:
            continue
        if not subj or not pred or not obj:
            continue
        vis = "visitor_private" if turn.audience == "visitor" else ("public" if f.get("visibility_hint") == "public" else "private")
        dup = (await db.execute(select(Fact).where(Fact.owner_id == owner.id, Fact.status == "active", Fact.subject.ilike(subj), Fact.predicate.ilike(pred),
                                                   Fact.visibility == vis))).scalars().all()
        if any(d.object.strip().lower() == obj.lower() for d in dup):
            continue
        try:
            conf = max(0.0, min(1.0, float(f.get("confidence") or 0.7)))
        except (TypeError, ValueError):
            conf = 0.7
        fact = Fact(owner_id=owner.id, agent_id=agent.id, subject=subj, predicate=pred, object=obj, kind=f.get("kind") if f.get("kind") in
                    ("identity", "preference", "relationship", "commitment", "context", "knowledge") else "context",
                    confidence=conf, visibility=vis, visitor_id=visitor_id, source_turn_id=turn.id)
        db.add(fact)
        await db.flush()
        for d in dup:
            if d.confidence <= fact.confidence:
                d.status, d.superseded_by = "superseded", fact.id
        n_facts += 1
    note = data.get("note")
    if isinstance(note, dict) and note.get("title") and note.get("body"):
        title, body = str(note["title"])[:120], str(note["body"])[:2000]
        # 프롬프트로 말해 두어도 모델은 같은 이야기를 다시 쓴다. 쓰기 직전에 한 번 더
        # 본다: 같은 것이면 **새로 쓰지 않고 있던 것을 고친다** (plan/50 §2).
        same = _same_story(title, body, here)
        if same is not None:
            # 있던 줄을 **고친다**: 제목은 그 이야기가 처음 불린 이름을 지키고,
            # 본문은 오늘 것을 뒤에 잇는다. 읽는 사람에게는 한 줄이 자란 것이다.
            title, body = (same.title or title), _merged_body(same.body or "", body)
        try:
            await mem.remember(title=title, body=body,
                               category=note.get("category") if note.get("category") in ("conversations", "observations", "decisions", "people") else "conversations",
                               tags=[str(t)[:30] for t in (note.get("tags") or [])][:8], importance=note.get("importance") if note.get("importance") in ("high", "medium", "low") else "medium",
                               source=f"distill:{turn.id}", note_id=same.id if same else None,
                               meta={**((same.meta or {}) if same else {}), "turn_id": str(turn.id),
                                     "conversation_id": str(turn.conversation_id)})
        except Exception as e:  # noqa: BLE001
            log.warning("distill note failed", err=str(e)[:200])
    people_in = data.get("people")
    for p in (people_in if isinstance(people_in, list) else [])[:5]:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            continue
        name = p["name"].strip()
        if len(name) < 2 or name.lower() in (owner_name.lower(), agent.name.lower()):
            continue
        existing = await N.search(db, owner.id, name, limit=1)
        if existing and existing[0]["score"] >= 0.95:
            continue
        payload = {"kind": p.get("kind") if p.get("kind") in ("person", "organization") else "person", "name": name[:200],
                   "attrs": {k: v for k, v in (("company", p.get("company")), ("title", p.get("title"))) if v},
                   "relation_to_owner": p.get("relation_hint"), "reason": f"mentioned in {turn.audience} conversation", "tags": ["chat_derived"]}
        if visitor_id:
            payload["from_visitor_id"] = str(visitor_id)
        try:
            pconf = max(0.0, min(1.0, float(p.get("confidence") or 0.5)))
        except (TypeError, ValueError):
            pconf = 0.5
        await N.propose(db, owner.id, agent_id=agent.id, kind="add_node", payload=payload, confidence=pconf, source_turn_id=turn.id)
        n_people += 1
    return {"facts": n_facts, "note": bool(note), "people": n_people, "at": datetime.now(UTC).isoformat()}


async def summarize_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> str | None:
    from blackmoa.models import Conversation
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        return None
    msgs = (await db.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(30))).scalars().all()
    if len(msgs) < 4:
        return None
    text = "\n".join(f"[{m.role}] {m.content[:600]}" for m in reversed(msgs) if m.content)
    provider = await S.get(db, "memory.distill_provider")
    model = await S.get(db, "memory.distill_model")
    try:
        out, _ = await complete(db, provider=provider, model=model, system="Summarize this conversation in 2 sentences (same language). Output only the summary.",
                                user_text=text[:12000], max_tokens=200, timeout_s=90)
    except Exception:
        return None
    conv.summary = out.strip()[:1000]
    return conv.summary
