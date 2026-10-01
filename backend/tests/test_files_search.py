"""파일 본문으로 찾기 · 지식으로 올리기 · 공개 범위 (plan/55 P4)."""
from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import auth, read_sse, signup

pytestmark = pytest.mark.asyncio


async def _handed(client, tok, agent_id, conv_id, name, data, mime):
    up = (await client.post("/api/uploads", headers=auth(tok), files={"file": (name, data, mime)})).json()
    async with client.stream("POST", f"/api/agents/{agent_id}/conversations/{conv_id}/turns",
                             json={"text": "받아", "upload_ids": [up["upload_id"]]}, headers=auth(tok)) as resp:
        await read_sse(resp)
    return up


async def _ingest_pending():
    from blackmoa.db.session import session_scope
    from blackmoa.models import AgentFile
    from blackmoa.services import files as FILES
    async with session_scope() as db:
        ids = (await db.execute(select(AgentFile.id).where(AgentFile.status == "pending"))).scalars().all()
    for i in ids:
        async with session_scope() as db:
            await FILES.ingest(db, i)
            await db.commit()


async def test_words_deep_inside_a_file_are_found_and_it_can_become_knowledge(client: AsyncClient):
    from blackmoa.db.session import session_scope
    from blackmoa.models import Agent, AgentFile, User
    from blackmoa.pipeline.tools.file_tools import FilesList

    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "찾기비서"}, headers=auth(tok))).json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
    body = ("회의록 본문입니다. " * 400) + "\n\n결론: 분기 예산은 사천이백만원으로 확정."
    await _handed(client, tok, agent["id"], conv["id"], "회의록.txt", body.encode(), "text/plain")
    await _ingest_pending()

    found = (await client.get("/api/files?q=사천이백만원", headers=auth(tok))).json()
    assert found["total"] == 1                               # 앞 2,000자 밖에 있는 말
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(user["id"]))
        a = await db.get(Agent, uuid.UUID(agent["id"]))
        f = (await db.execute(select(AgentFile).where(AgentFile.agent_id == a.id))).scalars().first()
    ctx = SimpleNamespace(owner=owner, owner_id=owner.id, agent=a, audience="owner", visitor=None, relay_id=None, vision=True)
    listed = await FilesList(ctx).run({"query": "분기 예산"})
    assert "회의록.txt" in listed and "사천이백만원" in listed

    detail = (await client.get(f"/api/files/{f.id}", headers=auth(tok))).json()
    assert detail["can_promote"] and detail["knowledge_document_id"] is None
    doc = (await client.post(f"/api/files/{f.id}/to-knowledge", headers=auth(tok))).json()
    again = (await client.post(f"/api/files/{f.id}/to-knowledge", headers=auth(tok))).json()
    assert doc["document_id"] == again["document_id"]
    assert (await client.get(f"/api/files/{f.id}", headers=auth(tok))).json()["knowledge_document_id"] == doc["document_id"]


async def test_opening_an_owner_file_to_visitors(client: AsyncClient):
    from blackmoa.db.session import session_scope
    from blackmoa.models import Agent, AgentFile, User
    from blackmoa.pipeline.tools.file_tools import FilesList

    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "공개비서"}, headers=auth(tok))).json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
    await _handed(client, tok, agent["id"], conv["id"], "메뉴판.txt", "아메리카노 3000원".encode(), "text/plain")
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(user["id"]))
        a = await db.get(Agent, uuid.UUID(agent["id"]))
        f = (await db.execute(select(AgentFile).where(AgentFile.agent_id == a.id))).scalars().first()
    visitor = SimpleNamespace(id=uuid.uuid4())
    vctx = SimpleNamespace(owner=owner, owner_id=owner.id, agent=a, audience="visitor", visitor=visitor, relay_id=None,
                           vision=True, viewer_level="stranger")
    from blackmoa.services import outsider as OUT

    async def turn() -> None:
        # 러너가 턴마다 하는 것 — 이 비서의 [지식] 탭대로 이 사람에게 쓸 것을 정한다 (plan/57).
        async with session_scope() as db:
            vctx.agent = await db.get(Agent, uuid.UUID(agent["id"]))
            vctx.disclosure = await OUT.for_turn(db, vctx.agent, "stranger")

    await turn()
    assert "not been given" in await FilesList(vctx).run({})                  # 새 비서는 아무것도 고르지 않았다
    r = await client.put(f"/api/agents/{agent['id']}/outsider/picks", headers=auth(tok), json={"kind": "files", "ids": [str(f.id)]})
    assert r.status_code == 200 and r.json()["files"]["picked"] == 1
    await turn()
    assert "메뉴판.txt" in await FilesList(vctx).run({})
    # 파일 줄을 [쓰지 않음] 으로 두면 고른 것도 쓰지 않는다.
    await client.patch(f"/api/agents/{agent['id']}/outsider", headers=auth(tok), json={"files": "off"})
    await turn()
    assert "메뉴판.txt" not in await FilesList(vctx).run({})
    # 공개 범위를 바꾸던 옛 길은 없다.
    assert (await client.patch(f"/api/files/{f.id}", headers=auth(tok), json={"visibility": "public"})).status_code == 405


async def test_a_photo_does_not_become_knowledge(client: AsyncClient):
    from PIL import Image
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "사진비서"}, headers=auth(tok))).json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, format="JPEG")
    await _handed(client, tok, agent["id"], conv["id"], "a.jpg", buf.getvalue(), "image/jpeg")
    fid = (await client.get("/api/files", headers=auth(tok))).json()["items"][0]["id"]
    assert (await client.get(f"/api/files/{fid}", headers=auth(tok))).json()["can_promote"] is False
    r = await client.post(f"/api/files/{fid}/to-knowledge", headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_promotable"
