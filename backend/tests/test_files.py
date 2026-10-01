"""비서의 파일과 하나의 저장 공간 (plan/55 P1).

실제로 겪은 결함만 고정한다: 대화에 붙인 파일이 그 턴에만 있고 사라지던 것, 그리고 이번에
새로 세운 약속들(같은 바이트는 한 행, 지우면 한도에서 빠지고 더는 안 열림, 가득 차면 안 받음).
"""
from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from tests.conftest import auth, read_sse, signup

pytestmark = pytest.mark.asyncio


def _jpeg() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (900, 600), (20, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


async def _turn(client, tok, agent_id, conv_id, text, upload_ids):
    async with client.stream("POST", f"/api/agents/{agent_id}/conversations/{conv_id}/turns",
                             json={"text": text, "upload_ids": upload_ids}, headers=auth(tok)) as resp:
        assert resp.status_code == 200, await resp.aread()
        return await read_sse(resp)


async def _setup(client):
    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "파일비서"}, headers=auth(tok))).json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(tok))).json()
    return user, tok, agent, conv


async def _up(client, tok, name, data, mime):
    r = await client.post("/api/uploads", headers=auth(tok), files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()


async def _ingest_all(monkeypatch):
    from blackmoa.db.session import session_scope
    from blackmoa.models import AgentFile
    from blackmoa.services import files as FILES

    async def fake_caption(db, f, data):
        return "파란 사각형 사진"
    monkeypatch.setattr(FILES, "caption", fake_caption)
    async with session_scope() as db:
        ids = (await db.execute(select(AgentFile.id).where(AgentFile.status == "pending"))).scalars().all()
    for i in ids:
        async with session_scope() as db:
            await FILES.ingest(db, i)


async def test_what_was_handed_over_stays_with_the_secretary(client: AsyncClient, monkeypatch):
    _, tok, agent, conv = await _setup(client)
    img = await _up(client, tok, "사진.jpg", _jpeg(), "image/jpeg")
    doc = await _up(client, tok, "메모.txt", "회의는 목요일 3시.\n장소는 3층.".encode(), "text/plain")
    await _turn(client, tok, agent["id"], conv["id"], "이거 봐", [img["upload_id"], doc["upload_id"]])

    listed = (await client.get(f"/api/files?agent_id={agent['id']}", headers=auth(tok))).json()
    assert listed["total"] == 2
    msgs = (await client.get(f"/api/agents/{agent['id']}/conversations/{conv['id']}/messages", headers=auth(tok))).json()["items"]
    atts = msgs[0]["attachments"]
    assert {a["file_id"] for a in atts} == {f["id"] for f in listed["items"]}

    # 같은 사진을 다시 붙여도 [파일] 은 하나다.
    again = await _up(client, tok, "사진.jpg", _jpeg(), "image/jpeg")
    await _turn(client, tok, agent["id"], conv["id"], "아까 그거", [again["upload_id"]])
    assert (await client.get(f"/api/files?agent_id={agent['id']}", headers=auth(tok))).json()["total"] == 2

    await _ingest_all(monkeypatch)
    items = {f["kind"]: f for f in (await client.get("/api/files", headers=auth(tok))).json()["items"]}
    assert items["image"]["status"] == "ready" and items["image"]["caption"] == "파란 사각형 사진"
    thumb = await client.get(items["image"]["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    txt = (await client.get(f"/api/files/{items['text']['id']}/text", headers=auth(tok))).json()
    assert "목요일 3시" in txt["text"] and not txt["truncated"]
    found = (await client.get("/api/files?q=목요일", headers=auth(tok))).json()
    assert [f["id"] for f in found["items"]] == [items["text"]["id"]]


async def test_storage_is_one_account_and_deleting_frees_it(client: AsyncClient):
    _, tok, agent, conv = await _setup(client)
    img = await _up(client, tok, "a.jpg", _jpeg(), "image/jpeg")
    await _turn(client, tok, agent["id"], conv["id"], "사진", [img["upload_id"]])
    st = (await client.get("/api/storage", headers=auth(tok))).json()
    seg = next(s for s in st["segments"] if s.get("agent_id") == agent["id"])
    assert seg["bytes"] == img["size"] and seg["files"] == 1 and seg["name"] == "파일비서"
    assert st["used_bytes"] == sum(s["bytes"] for s in st["segments"])
    assert st["limit_bytes"] == 1024 * 1024 * 1024        # Free 1GB (결정 1-a)

    fid = (await client.get("/api/files", headers=auth(tok))).json()["items"][0]["id"]
    assert (await client.delete(f"/api/files/{fid}", headers=auth(tok))).status_code == 204
    assert (await client.get("/api/files", headers=auth(tok))).json()["total"] == 0
    st2 = (await client.get("/api/storage", headers=auth(tok))).json()
    assert st2["used_bytes"] == st["used_bytes"] - img["size"]
    # 지우면 대화의 그림도 더는 열리지 않는다.
    assert (await client.get(img["url"])).status_code == 404


async def test_a_full_account_refuses_new_files_and_says_so_once(client: AsyncClient):
    from blackmoa.db.session import session_scope
    from blackmoa.models import InboxItem, Plan, User

    user, tok, agent, conv = await _setup(client)
    async with session_scope() as db:
        u = await db.get(User, uuid.UUID(user["id"]))
        plan = Plan(code=f"tiny{uuid.uuid4().hex[:6]}", name="Tiny", monthly_credits=10, max_agents=1, max_share_links=1,
                    max_storage_mb=1, features={}, is_default=False)
        db.add(plan)
        await db.flush()
        u.plan_id = plan.id
        await db.commit()
    big = b"x" * (950 * 1024)
    await _up(client, tok, "big.txt", big, "text/plain")                       # 93% → 알림
    r = await client.post("/api/uploads", headers=auth(tok), files={"file": ("more.txt", big, "text/plain")})
    assert r.status_code == 409 and r.json()["error"]["code"] == "storage_full"
    await client.post("/api/uploads", headers=auth(tok), files={"file": ("tiny.txt", b"a", "text/plain")})
    async with session_scope() as db:
        notes = (await db.execute(select(InboxItem).where(InboxItem.owner_id == uuid.UUID(user["id"]),
                                                          InboxItem.kind == "storage_notice"))).scalars().all()
    assert len(notes) == 1 and notes[0].payload["level"] == 90


async def test_deleted_files_are_really_removed_after_thirty_days(client: AsyncClient):
    from blackmoa.db.session import session_scope
    from blackmoa.models import AgentFile, Upload
    from blackmoa.services import files as FILES

    _, tok, agent, conv = await _setup(client)
    img = await _up(client, tok, "old.jpg", _jpeg(), "image/jpeg")
    await _turn(client, tok, agent["id"], conv["id"], "옛날 사진", [img["upload_id"]])
    fid = (await client.get("/api/files", headers=auth(tok))).json()["items"][0]["id"]
    await client.delete(f"/api/files/{fid}", headers=auth(tok))
    async with session_scope() as db:
        assert await FILES.purge(db) == 0                                     # 아직 30일이 안 됐다
        await db.execute(update(AgentFile).where(AgentFile.id == uuid.UUID(fid))
                         .values(deleted_at=datetime.now(UTC) - timedelta(days=31)))
        await db.commit()
    async with session_scope() as db:
        assert await FILES.purge(db) >= 1
        await db.commit()
    async with session_scope() as db:
        assert await db.get(Upload, uuid.UUID(img["upload_id"])) is None
