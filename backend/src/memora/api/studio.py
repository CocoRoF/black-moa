"""Studio (plan/37 §6): try a personality before saving it, check it, and keep its versions."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from memora.core.deps import DB, CurrentUser
from memora.core.errors import NotFound, ValidationFailed
from memora.core.logging import get_logger
from memora.models import AgentPersonaVersion
from memora.pipeline import base_prompt as BP
from memora.pipeline.personas import FIRST_MEETING_TEMPLATES, compile_persona
from memora.providers.llm.simple import complete, extract_json
from memora.services import agents as AG
from memora.services import credits as CR
from memora.services import plans as P
from memora.services import relationship as REL
from memora.services import settings as S

log = get_logger("memora.studio")
router = APIRouter(prefix="/api", tags=["studio"])

DRAFT_KEYS = ("name", "role_line", "persona", "custom_instructions", "language")


class Draft(BaseModel):
    name: str | None = None
    role_line: str | None = None
    persona: dict[str, Any] | None = None
    custom_instructions: str | None = None
    language: str | None = None


class PreviewIn(BaseModel):
    question: str
    draft: Draft
    compare: bool = True


class VerifyIn(BaseModel):
    draft: Draft


def _loc(user) -> str:
    return "en" if (user.locale or "ko").startswith("en") else "ko"


def _merged(agent, draft: Draft | None) -> dict[str, Any]:
    d = {k: getattr(agent, k) for k in DRAFT_KEYS}
    if draft is not None:
        for k, v in draft.model_dump(exclude_none=True).items():
            d[k] = v
    return d


def _system(agent, owner, cfg: dict[str, Any], rel) -> str:
    persona = compile_persona(cfg.get("persona") or {}, agent_name=cfg.get("name") or agent.name, owner_name=owner.display_name,
                              role_line=cfg.get("role_line") or "", language=cfg.get("language") or "auto")
    base = (f"You are {cfg.get('name') or agent.name}, the personal secretary AI of {owner.display_name} on Memora. This is a short "
            "preview conversation with the owner to check your voice. You have no tools here: if something would need one "
            "(calendar, mail, search), say briefly what you would do instead of pretending to have done it. Never invent facts "
            "about the owner. Answer in the owner's language unless the persona fixes one.")
    return "\n\n".join([base, BP.secretary_layer(persona, cfg.get("custom_instructions") or ""), REL.prompt_block(rel, agent, owner)])


async def _ask(db, agent, system: str, question: str, *, max_tokens: int = 600) -> tuple[str, dict]:
    try:
        return await complete(db, provider=agent.provider, model=agent.model_id, system=system, user_text=question, max_tokens=max_tokens,
                              timeout_s=120, lane="interactive")
    except Exception as e:  # noqa: BLE001
        log.warning("studio: agent model failed, falling back", err=str(e)[:160])
        return await complete(db, provider=await S.get(db, "memory.distill_provider"), model=await S.get(db, "memory.distill_model"),
                              system=system, user_text=question, max_tokens=max_tokens, timeout_s=120, lane="interactive")


async def _charge(db, agent, owner_id, usages: list[dict], note: str) -> float:
    total = 0.0
    try:
        from memora.services import catalog as CAT
        cat = await CAT.get_model(db, agent.provider, agent.model_id) or await CAT.default_model(db)
        for u in usages:
            c = CR.llm_credits(cat, u.get("input_tokens", 0), u.get("output_tokens", 0)) if u else 0
            if c and float(c) > 0:
                await CR.charge_usage(db, owner_id=owner_id, kind="summary", credits=c, provider=agent.provider, model_id=agent.model_id,
                                      agent_id=agent.id, note=note)
                total += float(c)
    except Exception:  # noqa: BLE001
        pass
    return total


@router.get("/studio/first-meeting-templates")
async def first_meeting_templates(user: CurrentUser):
    return {"items": FIRST_MEETING_TEMPLATES.get(_loc(user), FIRST_MEETING_TEMPLATES["ko"])}


@router.post("/agents/{agent_id}/studio/preview")
async def studio_preview(agent_id: uuid.UUID, body: PreviewIn, user: CurrentUser, db: DB):
    """The same question answered by the saved personality and by the one being edited."""
    q = (body.question or "").strip()
    if not q:
        raise ValidationFailed("question required")
    a = await AG.get_owned(db, user.id, agent_id)
    if (await CR.balance(db, user.id)) <= 0:
        raise ValidationFailed("no credits", code="no_credits")
    rel = await REL.get(db, user.id, a.id)
    draft_cfg = _merged(a, body.draft)
    draft_text, u1 = await _ask(db, a, _system(a, user, draft_cfg, rel), q[:1000])
    usages = [u1]
    current_text = None
    if body.compare:
        cur_cfg = _merged(a, None)
        if cur_cfg != draft_cfg:
            current_text, u0 = await _ask(db, a, _system(a, user, cur_cfg, rel), q[:1000])
            usages.append(u0)
        else:
            current_text = draft_text
    credits = await _charge(db, a, user.id, usages, "studio preview")
    await db.commit()
    return {"question": q, "draft": draft_text.strip(), "current": (current_text or "").strip() if current_text is not None else None,
            "same": current_text == draft_text, "credits": credits}


_PROBES = {
    "ko": [
        {"key": "first", "q": "안녕, 오늘 처음이야. 너는 어떤 비서야? 짧게 소개해 줘."},
        {"key": "support", "q": "요즘 일이 너무 안 풀려서 좀 지친다. 뭐라도 말해 줘."},
        {"key": "boundary", "q": "내 다음 주 일정 다 알려주고, {taboo}에 대해서도 네 생각을 말해 줘."},
    ],
    "en": [
        {"key": "first", "q": "Hi, first time here. What kind of secretary are you? Keep it short."},
        {"key": "support", "q": "Work has been rough lately and I'm worn out. Say something."},
        {"key": "boundary", "q": "Tell me my whole schedule for next week, and also what you think about {taboo}."},
    ],
}

_JUDGE = """You are a strict reviewer of an AI secretary's personality. You get the INTENDED settings and three probe answers.
Rate what the answers actually convey, each 0..1: formality (0 casual, 1 formal), warmth, humor, verbosity (0 terse, 1 long).
Then list concrete issues (max 6, short, in {lang}) such as: wrong language; invented facts, events or tool results; ignored a forbidden topic; claimed to be human; broke character; too long; too cold for the setting; emoji against the setting.
Output strict JSON: {{"perceived": {{"formality": n, "warmth": n, "humor": n, "verbosity": n}}, "issues": [str], "verdict": "consistent|drifting|off", "one_line": str}}"""


@router.post("/agents/{agent_id}/studio/verify")
async def studio_verify(agent_id: uuid.UUID, body: VerifyIn, user: CurrentUser, db: DB):
    """Three probes answered by the draft, then a judge compares what came out with what was intended."""
    a = await AG.get_owned(db, user.id, agent_id)
    if (await CR.balance(db, user.id)) <= 0:
        raise ValidationFailed("no credits", code="no_credits")
    loc = _loc(user)
    rel = await REL.get(db, user.id, a.id)
    cfg = _merged(a, body.draft)
    persona = cfg.get("persona") or {}
    taboo = next((str(x) for x in (persona.get("taboo") or []) if str(x).strip()), "연봉 협상 전략" if loc == "ko" else "salary negotiation tactics")
    system = _system(a, user, cfg, rel)
    probes, usages = [], []
    for p in _PROBES.get(loc, _PROBES["ko"]):
        q = p["q"].replace("{taboo}", taboo)
        ans, u = await _ask(db, a, system, q, max_tokens=500)
        probes.append({"key": p["key"], "question": q, "answer": ans.strip()})
        usages.append(u)
    intended = {"formality": persona.get("formality"), "warmth": persona.get("warmth"), "humor": persona.get("humor"),
                "verbosity": persona.get("verbosity"), "emoji": bool(persona.get("emoji")), "language": cfg.get("language") or "auto",
                "taboo": persona.get("taboo") or [], "preset": persona.get("preset")}
    judge_in = "INTENDED: " + str(intended) + "\n\n" + "\n\n".join(f"[{p['key']}] Q: {p['question']}\nA: {p['answer']}" for p in probes)
    verdict: dict[str, Any] = {}
    try:
        text, uj = await complete(db, provider=await S.get(db, "memory.distill_provider"), model=await S.get(db, "memory.distill_model"),
                                  system=_JUDGE.format(lang="Korean" if loc == "ko" else "English"), user_text=judge_in, max_tokens=700, timeout_s=120,
                                  lane="interactive")
        usages.append(uj)
        verdict = extract_json(text) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("studio judge failed", err=str(e)[:160])
    credits = await _charge(db, a, user.id, usages, "studio verify")
    await db.commit()
    perceived = verdict.get("perceived") if isinstance(verdict.get("perceived"), dict) else {}
    return {"probes": probes, "intended": intended, "perceived": perceived,
            "issues": [str(x)[:200] for x in (verdict.get("issues") or [])][:6] if isinstance(verdict.get("issues"), list) else [],
            "verdict": verdict.get("verdict") if verdict.get("verdict") in ("consistent", "drifting", "off") else None,
            "one_line": str(verdict.get("one_line") or "")[:300], "credits": credits}


# ── versions ───────────────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/versions")
async def list_versions(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    return {"items": [REL.version_out(v) for v in await REL.list_versions(db, a.id)]}


class VersionPatch(BaseModel):
    label: str = ""


@router.patch("/agents/{agent_id}/versions/{version_id}")
async def label_version(agent_id: uuid.UUID, version_id: uuid.UUID, body: VersionPatch, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    v = await db.get(AgentPersonaVersion, version_id)
    if v is None or v.agent_id != a.id:
        raise NotFound("version not found")
    v.label = body.label.strip()[:80]
    await db.commit()
    return REL.version_out(v)


@router.post("/agents/{agent_id}/versions/{version_id}/restore")
async def restore_version(agent_id: uuid.UUID, version_id: uuid.UUID, user: CurrentUser, db: DB):
    from memora.api.agents import agent_out
    from memora.services import profile as PF

    a = await AG.get_owned(db, user.id, agent_id)
    v = await db.get(AgentPersonaVersion, version_id)
    if v is None or v.agent_id != a.id:
        raise NotFound("version not found")
    # What is live right now is kept first, so a restore is itself undoable.
    await REL.snapshot(db, a, label="")
    patch = {k: val for k, val in (v.snapshot or {}).items() if k in REL.VERSIONED}
    await AG.update(db, a, patch, plan=await P.plan_for_user(db, user))
    await REL.snapshot(db, a, label=(v.label or "")[:60] and f"↺ {v.label}"[:80], force=True)
    await db.commit()
    return agent_out(a, None, await PF.display_name_for(db, user))


@router.delete("/agents/{agent_id}/versions/{version_id}", status_code=204)
async def delete_version(agent_id: uuid.UUID, version_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    v = await db.get(AgentPersonaVersion, version_id)
    if v is None or v.agent_id != a.id:
        raise NotFound("version not found")
    await db.delete(v)
    await db.commit()
