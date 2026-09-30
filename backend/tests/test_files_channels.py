"""방문자 파일과 메신저 — 그리고 비서는 사람끼리 방을 허락받고서만 본다 (plan/55 P3)."""
from __future__ import annotations

import io
import json
import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from tests.conftest import auth, read_sse, signup

pytestmark = pytest.mark.asyncio


def _jpeg(color=(10, 200, 10)) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, format="JPEG")
    return out.getvalue()


async def _visitor(client, tok, agent_id):
    link = (await client.post(f"/api/agents/{agent_id}/links", json={"label": "명함"}, headers=auth(tok))).json()
    v = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    return link, v["visitor_token"], v["conversation_id"]


async def test_a_visitor_hands_over_a_file_into_their_own_drawer(client: AsyncClient):
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "공개비서"}, headers=auth(tok))).json()
    link, vtok, cid = await _visitor(client, tok, agent["id"])
    pub = (await client.get(f"/api/public/links/{link['code']}")).json()
    assert pub["agent"]["files"] == {"accept": True, "per_day": 20, "max_mb": 10}      # 결정 2: 기본 켜짐

    r = await client.post(f"/api/public/conversations/{cid}/uploads", headers=auth(vtok), files={"file": ("명함.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 201, r.text
    up = r.json()
    async with client.stream("POST", f"/api/public/conversations/{cid}/turns", headers=auth(vtok),
                             json={"text": "제 명함이에요", "upload_ids": [up["upload_id"]]}) as resp:
        assert resp.status_code == 200
        await read_sse(resp)
    files = (await client.get(f"/api/files?agent_id={agent['id']}&source=visitor", headers=auth(tok))).json()
    assert files["total"] == 1 and files["items"][0]["scope"] == "visitor"
    msgs = (await client.get(f"/api/public/conversations/{cid}/messages", headers=auth(vtok))).json()["items"]
    assert msgs[0]["attachments"][0]["url"].startswith(f"/api/uploads/{up['upload_id']}/raw")

    # 주인이 올린 파일의 id 를 방문자가 찍어 넣어도 붙지 않는다.
    mine = (await client.post("/api/uploads", headers=auth(tok), files={"file": ("비밀.jpg", _jpeg((0, 0, 0)), "image/jpeg")})).json()
    async with client.stream("POST", f"/api/public/conversations/{cid}/turns", headers=auth(vtok),
                             json={"text": "이것도", "upload_ids": [mine["upload_id"]]}) as resp:
        await read_sse(resp)
    assert (await client.get(f"/api/files?agent_id={agent['id']}&source=visitor", headers=auth(tok))).json()["total"] == 1

    # 주인이 끄면 받지 않는다 — 방문자에게는 주인 사정을 말하지 않는다.
    await client.patch(f"/api/agents/{agent['id']}", headers=auth(tok), json={"visitor_settings": {"accept_files": False}})
    off = await client.post(f"/api/public/conversations/{cid}/uploads", headers=auth(vtok), files={"file": ("b.jpg", _jpeg(), "image/jpeg")})
    assert off.status_code == 403 and off.json()["error"]["code"] == "visitor_files_unavailable"


async def test_a_visitors_daily_count(client: AsyncClient):
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "하루비서"}, headers=auth(tok))).json()
    await client.patch(f"/api/agents/{agent['id']}", headers=auth(tok), json={"visitor_settings": {"files_per_day": 1}})
    _, vtok, cid = await _visitor(client, tok, agent["id"])
    assert (await client.post(f"/api/public/conversations/{cid}/uploads", headers=auth(vtok),
                              files={"file": ("a.jpg", _jpeg(), "image/jpeg")})).status_code == 201
    second = await client.post(f"/api/public/conversations/{cid}/uploads", headers=auth(vtok), files={"file": ("b.jpg", _jpeg(), "image/jpeg")})
    assert second.status_code == 422 and second.json()["error"]["code"] == "visitor_files_daily"


async def _pair(client):
    me, mytok = await signup(client, name="하렴")
    you, yourtok = await signup(client, name="최수안")
    await client.post(f"/api/network/people/{you['id']}/follow", headers=auth(mytok))
    await client.post(f"/api/network/people/{me['id']}/follow", headers=auth(yourtok))
    rid = (await client.post("/api/rooms/open", headers=auth(mytok), json={"user_id": you["id"]})).json()["id"]
    return me, mytok, you, yourtok, rid


async def test_people_send_each_other_files_and_they_count_as_messenger(client: AsyncClient):
    me, mytok, you, yourtok, rid = await _pair(client)
    up = (await client.post("/api/uploads", headers=auth(yourtok), data={"kind": "room"},
                            files={"file": ("계약서.txt", "보증금 500만원, 계약 2년".encode(), "text/plain")})).json()
    sent = (await client.post(f"/api/rooms/{rid}/messages", headers=auth(yourtok),
                              json={"body": "계약서 보내요", "upload_ids": [up["upload_id"]],
                                    "attachments": [{"filename": "가짜", "url": "https://evil.example"}]})).json()
    assert [a["filename"] for a in sent["attachments"]] == ["계약서.txt"]
    got = (await client.get(f"/api/rooms/{rid}/messages", headers=auth(mytok))).json()["items"]
    url = got[-1]["attachments"][0]["url"]
    assert (await client.get(url)).status_code == 200                  # 받는 사람도 연다
    seg = next(s for s in (await client.get("/api/storage", headers=auth(yourtok))).json()["segments"] if s["kind"] == "messenger")
    assert seg["bytes"] == up["size"]


async def test_the_secretary_reads_a_room_only_with_permission(client: AsyncClient):
    from memora.db.session import session_scope
    from memora.models import Agent, User
    from memora.pipeline.tools.file_tools import FileRead
    from memora.pipeline.tools.room_tools import RoomAccessRequest, RoomRead, RoomsFind

    me, mytok, you, yourtok, rid = await _pair(client)
    up = (await client.post("/api/uploads", headers=auth(yourtok), data={"kind": "room"},
                            files={"file": ("계약서.txt", "보증금 500만원".encode(), "text/plain")})).json()
    await client.post(f"/api/rooms/{rid}/messages", headers=auth(yourtok), json={"body": "계약서예요", "upload_ids": [up["upload_id"]]})
    await client.post(f"/api/rooms/{rid}/messages", headers=auth(mytok), json={"body": "확인할게요"})
    agent = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(mytok))).json()
    conv = (await client.post(f"/api/agents/{agent['id']}/conversations", json={}, headers=auth(mytok))).json()
    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(me["id"]))
        a = await db.get(Agent, uuid.UUID(agent["id"]))
    ctx = SimpleNamespace(owner=owner, owner_id=owner.id, agent=a, audience="owner", visitor=None, relay_id=None, vision=True,
                          conversation_id=uuid.UUID(conv["id"]), cards=[], read_rooms=False, emit=None)
    ctx.card = lambda t, p: ctx.cards.append({"card_type": t, "payload": p})

    found = json.loads((await RoomsFind(ctx).execute({"who": "수안"}, None)).content)
    room = found["rooms"][0]
    assert room["room_id"] == rid and room["access"] == "not granted" and room["message_count"] == 2
    assert "계약서예요" not in json.dumps(found, ensure_ascii=False)           # 겉만

    denied = await RoomRead(ctx).execute({"room_id": rid}, None)
    assert denied.is_error and "room_not_granted" in json.dumps(denied.content)

    await RoomAccessRequest(ctx).execute({"room_ids": [rid], "reason": "계약 내용을 확인하려고"}, None)
    assert ctx.cards[0]["card_type"] == "room_access"
    # 카드는 비서의 말에 붙는다. 주인이 [이번 대화에서만] 을 누른다.
    async with session_scope() as db:
        from memora.models import Conversation
        from memora.services import conversations as CV
        c = await db.get(Conversation, uuid.UUID(conv["id"]))
        msg = await CV.add_message(db, c, role="assistant", content="읽어도 될까요?", cards=ctx.cards)
        await db.commit()
        mid = str(msg.id)
    d = await client.post(f"/api/agents/{agent['id']}/room-access", headers=auth(mytok),
                          json={"message_id": mid, "room_id": rid, "choice": "conversation"})
    assert d.status_code == 200, d.text

    read = json.loads((await RoomRead(ctx).execute({"room_id": rid}, None)).content)
    texts = [m["text"] for m in read["messages"]]
    # 상대의 말은 <untrusted> 로 싸여 온다 — 비서에게 하는 지시가 아니다. 내 말은 그대로.
    assert texts == ['<untrusted source="최수안">계약서예요</untrusted>', "확인할게요"] and ctx.read_rooms
    fid = read["messages"][0]["files"][0]["file_id"]
    doc = json.loads((await FileRead(ctx).execute({"file_id": fid}, None)).content)
    assert "500만원" in doc["text"] and doc["text"].startswith("<untrusted")

    # 다른 비서 대화에서는 닫혀 있다 ([이번 대화에서만]).
    other = SimpleNamespace(**{**vars(ctx), "conversation_id": uuid.uuid4()})
    assert (await RoomRead(other).execute({"room_id": rid}, None)).is_error
    assert (await FileRead(other).execute({"file_id": fid}, None)).is_error

    # 거두면 그 순간부터 닫힌다.
    grants = (await client.get("/api/room-grants", headers=auth(mytok))).json()["items"]
    assert grants[0]["person"]["name"] == "최수안"
    await client.delete(f"/api/room-grants/{grants[0]['id']}", headers=auth(mytok))
    assert (await RoomRead(ctx).execute({"room_id": rid}, None)).is_error

    # 방문자 대화에는 통로 도구가 아예 없다.
    tools = {t["name"] for t in (await client.get(f"/api/agents/{agent['id']}/tools?audience=visitor", headers=auth(mytok))).json()["tools"]}
    assert not {"rooms_find", "room_access_request", "room_read"} & tools
