"""비서가 받은 파일을 다시 연다 (plan/55 P2).

"아까 보낸 사진 다시 봐" 가 되는지, 그리고 방문자 대화의 도구가 제 방문자 칸만 보는지.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import auth, read_sse, signup

pytestmark = pytest.mark.asyncio


def _jpeg() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


def _pdf() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (200, 280), (255, 255, 255)).save(out, format="PDF")
    return out.getvalue()


async def _given(client, tok, agent_id, conv_id, name, data, mime):
    up = (await client.post("/api/uploads", headers=auth(tok), files={"file": (name, data, mime)})).json()
    async with client.stream("POST", f"/api/agents/{agent_id}/conversations/{conv_id}/turns",
                             json={"text": "받아", "upload_ids": [up["upload_id"]]}, headers=auth(tok)) as resp:
        await read_sse(resp)
    return up


async def _world(client):
    from memora.db.session import session_scope
    from memora.models import Agent, AgentFile, User, Visitor
    from memora.services import files as FILES

    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "도구비서"}, headers=auth(tok))).json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
    await _given(client, tok, agent["id"], conv["id"], "빨간사진.jpg", _jpeg(), "image/jpeg")
    await _given(client, tok, agent["id"], conv["id"], "계약서.txt", "계약 기간은 2년, 위약금 10%.".encode(), "text/plain")
    await _given(client, tok, agent["id"], conv["id"], "도면.pdf", _pdf(), "application/pdf")
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(user["id"]))
        a = await db.get(Agent, uuid.UUID(agent["id"]))
        v1 = Visitor(agent_id=a.id, owner_id=owner.id, display_name="손님1", token_hash=uuid.uuid4().hex, first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC))
        v2 = Visitor(agent_id=a.id, owner_id=owner.id, display_name="손님2", token_hash=uuid.uuid4().hex, first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC))
        db.add_all([v1, v2])
        await db.flush()
        from memora.services import uploads as U
        up = await U.store(db, owner.id, kind="attachment", filename="손님사진.jpg", mime="image/jpeg", data=_jpeg())
        await FILES.record(db, agent_id=a.id, upload=up, source="public", scope="visitor", visitor_id=v1.id)
        for f in (await db.execute(select(AgentFile).where(AgentFile.agent_id == a.id))).scalars().all():
            f.caption = f.caption or ("빨간 사각형" if f.kind == "image" else "")
            if f.kind == "text":
                await FILES.ingest(db, f.id)
        await db.commit()
        return SimpleNamespace(owner=owner, agent=a, v1=v1, v2=v2)


def _ctx(w, audience="owner", visitor=None, vision=True, relay_id=None):
    return SimpleNamespace(owner=w.owner, owner_id=w.owner.id, agent=w.agent, audience=audience, visitor=visitor,
                           relay_id=relay_id, vision=vision)


async def test_the_fence_owner_sees_all_a_visitor_only_their_own(client: AsyncClient):
    from memora.pipeline.tools.file_tools import FilesList

    w = await _world(client)
    owner_view = await FilesList(_ctx(w)).run({})
    assert "빨간사진.jpg" in owner_view and "손님사진.jpg" in owner_view and "from a visitor" in owner_view
    v1_view = await FilesList(_ctx(w, "visitor", w.v1)).run({})
    assert "손님사진.jpg" in v1_view and "빨간사진.jpg" not in v1_view and "계약서" not in v1_view
    assert "not been given" in await FilesList(_ctx(w, "visitor", w.v2)).run({})
    assert "not been given" in await FilesList(_ctx(w, "visitor", w.v1, relay_id=uuid.uuid4())).run({})
    assert "계약서.txt" in await FilesList(_ctx(w)).run({"query": "계약"})


async def test_read_view_and_the_prompt_block(client: AsyncClient):
    from memora.db.session import session_scope
    from memora.models import AgentFile
    from memora.pipeline.tools.file_tools import FileRead, FileView
    from memora.services import files as FILES

    w = await _world(client)
    async with session_scope() as db:
        files = {f.filename: f for f in (await db.execute(select(AgentFile).where(AgentFile.agent_id == w.agent.id))).scalars().all()}
        block = await FILES.prompt_block(db, _ctx(w))
    assert f"[{files['계약서.txt'].id}]" in block and "file_view" in block

    got = json.loads((await FileRead(_ctx(w)).execute({"file_id": str(files["계약서.txt"].id)}, None)).content)
    assert "위약금 10%" in got["text"]

    seen = await FileView(_ctx(w)).execute({"file_id": str(files["빨간사진.jpg"].id)}, None)
    assert [b["type"] for b in seen.content] == ["text", "image"]
    page = await FileView(_ctx(w)).execute({"file_id": str(files["도면.pdf"].id), "page": 1}, None)
    assert page.content[1]["source"]["media_type"] == "image/jpeg" and "page 1 of 1" in page.content[0]["text"]

    blind = json.loads((await FileView(_ctx(w, vision=False)).execute({"file_id": str(files["빨간사진.jpg"].id)}, None)).content)
    assert blind["description"] == "빨간 사각형"

    # 방문자는 주인의 파일을 id 로 찍어도 못 연다.
    denied = await FileRead(_ctx(w, "visitor", w.v1)).execute({"file_id": str(files["계약서.txt"].id)}, None)
    assert denied.is_error


def test_mcp_gets_pictures_in_its_own_shape():
    from memora.api.internal_mcp import _to_mcp_content

    out = _to_mcp_content([{"type": "text", "text": "a"},
                           {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}])
    assert out[1] == {"type": "image", "data": "QUJD", "mimeType": "image/jpeg"}


def test_this_turns_attachments_carry_their_file_ids():
    from memora.pipeline.runner import _build_input

    class Block:
        text = ""

    rt = SimpleNamespace(blocks={"memory": Block()}, context_window=200_000, vision=True)
    j = SimpleNamespace(emit=lambda *a, **k: None)
    out = _build_input(rt, "봐", [{"filename": "a.jpg", "mime": "image/jpeg", "data": "QUJD", "file_id": "F1"},
                                 {"filename": "b.txt", "mime": "text/plain", "text": "본문", "file_id": "F2"}], j)
    assert 'file_id="F1"' in out["text"] and 'file_id="F2"' in out["text"] and len(out["images"]) == 1
    rt.vision = False
    blind = _build_input(rt, "봐", [{"filename": "a.jpg", "mime": "image/jpeg", "data": "QUJD", "file_id": "F1", "caption": "고양이"}], j)
    assert isinstance(blind, str) and "(그림 설명) 고양이" in blind
