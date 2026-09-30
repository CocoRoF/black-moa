"""Google Drive 와 [파일] (plan/75) — drive.file 하나로.

가짜 Drive 로: 연결·파일 선택 창 설정 여부, 고른 파일 가져오기(일반 파일, Google 시트는 Excel 로 바꿔서, 폴더·없는 파일은
까닭과 함께 건너뜀), [파일]의 파일을 Drive 의 "Memora" 폴더에 저장(폴더가 없으면 만든다).
"""
from __future__ import annotations

import io
import json
import uuid

import httpx
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import AgentFile, Connection
from memora.services import gdrive as GD
from memora.services import settings as S
from tests.conftest import auth, signup
from tests.test_sso import _provider


def _xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.active["A1"] = "매출"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeDrive:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.folders: list[str] = []
        self.uploaded: bytes = b""

    async def request(self, method, url, *, headers=None, params=None, json=None, content=None, retries=3, **kw):
        params = params or {}
        self.calls.append((method, url, params))
        assert headers and headers.get("Authorization") == "Bearer tok"
        req = httpx.Request(method, url)
        if url.startswith(GD.UPLOAD):
            self.uploaded = content or b""
            return httpx.Response(200, request=req, json={"id": "up1", "name": "보고서.txt", "webViewLink": "https://drive.google.com/file/d/up1/view"})
        if method == "POST" and url == GD.API:
            self.folders.append(json["name"])
            return httpx.Response(200, request=req, json={"id": "folder1"})
        if method == "GET" and url == GD.API:
            return httpx.Response(200, request=req, json={"files": [{"id": "folder1"}] if self.folders else []})
        fid = url.rsplit("/", 2)[-2] if url.endswith("/export") else url.rsplit("/", 1)[-1]
        files = {
            "txt1": {"id": "txt1", "name": "회의록.txt", "mimeType": "text/plain", "size": "30"},
            "sheet1": {"id": "sheet1", "name": "매출표", "mimeType": "application/vnd.google-apps.spreadsheet"},
            "dir1": {"id": "dir1", "name": "폴더", "mimeType": GD.FOLDER_MIME},
        }
        if fid not in files:
            from memora.providers.http import ProviderHTTPError
            raise ProviderHTTPError(404, "not found")
        if url.endswith("/export"):
            return httpx.Response(200, request=req, content=_xlsx())
        if params.get("alt") == "media":
            return httpx.Response(200, request=req, content="다음 주 회의는 목요일입니다.".encode())
        return httpx.Response(200, request=req, json=files[fid])


@pytest_asyncio.fixture
async def drive(monkeypatch):
    await _provider("google")
    fake = FakeDrive()
    monkeypatch.setattr(GD, "request", fake.request)

    async def token(db, conn):
        return "tok"
    monkeypatch.setattr(GD.CN, "access_token", token)
    yield fake
    async with session_scope() as db:
        await S.put(db, "oauth.google.picker_api_key", "")
        await db.commit()
    S.invalidate("oauth.")
    await _provider("google", enabled=False)


async def _connect(user_id: str, caps: list[str]) -> None:
    async with session_scope() as db:
        db.add(Connection(owner_id=uuid.UUID(user_id), provider="google", account_label="me@gmail.com", capabilities=caps,
                          scopes=[], access_token_enc="", status="active"))
        await db.commit()


async def test_files_come_in_from_drive_and_go_back_out(client: AsyncClient, drive: FakeDrive):
    user, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()

    st = (await client.get("/api/drive/status", headers=auth(tok))).json()
    assert st == {"available": True, "connected": False, "picker": False}
    r = await client.get("/api/drive/picker", headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "drive_not_connected"

    await _connect(user["id"], ["calendar_read", "drive"])
    r = await client.get("/api/drive/picker", headers=auth(tok))
    assert r.json()["error"]["code"] == "drive_picker_unconfigured"   # 관리자가 브라우저 키를 넣기 전
    async with session_scope() as db:
        await S.put(db, "oauth.google.picker_api_key", "AIza-test")
        await S.put(db, "oauth.google.app_id", "145625595263")
        await db.commit()
    S.invalidate("oauth.")
    assert (await client.get("/api/drive/status", headers=auth(tok))).json() == {"available": True, "connected": True, "picker": True}
    pk = (await client.get("/api/drive/picker", headers=auth(tok))).json()
    assert pk == {"access_token": "tok", "api_key": "AIza-test", "app_id": "145625595263"}

    # 비서를 고르지 않는다 — 파일은 [내 정보 → 파일]로 간다 (plan/77).
    r = await client.post("/api/drive/import", json={"file_ids": ["txt1", "sheet1", "dir1", "gone"]}, headers=auth(tok))
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(x["name"] for x in out["imported"]) == ["매출표.xlsx", "회의록.txt"]   # 시트는 Excel 로 바꿔서
    assert sorted((x["drive_id"], x["code"]) for x in out["failed"]) == [("dir1", "drive_folder"), ("gone", "drive_not_found")]
    listed = (await client.get("/api/files", params={"source": "drive"}, headers=auth(tok))).json()["items"]
    assert sorted(f["filename"] for f in listed) == ["매출표.xlsx", "회의록.txt"] and all(f["source"] == "drive" for f in listed)
    assert all(f["agent_id"] is None for f in listed)
    async with session_scope() as db:
        files = (await db.execute(select(AgentFile).where(AgentFile.owner_id == uuid.UUID(user["id"]),
                                                          AgentFile.source == "drive"))).scalars().all()
        assert {f.kind for f in files} == {"text", "sheet"} and {f.agent_id for f in files} == {None}
    # 같은 파일을 다시 가져와도 하나다.
    r = await client.post("/api/drive/import", json={"file_ids": ["txt1"]}, headers=auth(tok))
    assert len((await client.get("/api/files", params={"source": "drive"}, headers=auth(tok))).json()["items"]) == 2

    # 비서는 나와의 대화에서 이 파일을 본다 — 어느 비서든 (plan/77).
    from types import SimpleNamespace

    from memora.services import files as FILES
    async with session_scope() as db:
        ctx = SimpleNamespace(owner_id=uuid.UUID(user["id"]), agent=SimpleNamespace(id=uuid.UUID(agent["id"])), audience="owner")
        seen = (await db.execute(select(AgentFile.filename).where(*FILES.visible_to(ctx)))).scalars().all()
        assert {"매출표.xlsx", "회의록.txt"} <= set(seen)

    # [파일]의 파일을 Drive 에 저장 — "Memora" 폴더를 한 번 만들고 거기에 올린다.
    fid = next(f["id"] for f in listed if f["filename"] == "회의록.txt")
    r = await client.post("/api/drive/save", json={"file_id": fid}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["link"].startswith("https://drive.google.com/")
    assert drive.folders == ["Memora"]
    head = drive.uploaded.split(b"\r\n\r\n", 2)[1].split(b"\r\n")[0]
    assert json.loads(head) == {"name": "회의록.txt", "parents": ["folder1"]}
    assert "다음 주 회의는 목요일입니다.".encode() in drive.uploaded
    await client.post("/api/drive/save", json={"file_id": fid}, headers=auth(tok))
    assert drive.folders == ["Memora"]   # 두 번째는 있는 폴더를 쓴다


async def test_google_asks_only_for_the_files_the_user_picks(client: AsyncClient):
    from memora.services import oauth as OA
    g = OA.get("google")
    drive = next(c for c in g.capabilities if c.id == "drive")
    assert drive.scopes == ("https://www.googleapis.com/auth/drive.file",)
    assert not any(s.endswith(("/auth/drive", "/auth/drive.readonly", "/auth/docs")) for c in g.capabilities for s in c.scopes)


async def test_the_consent_screen_speaks_the_users_language(client: AsyncClient, drive: FakeDrive):
    from urllib.parse import parse_qs, urlparse
    _, tok = await signup(client)
    await client.patch("/api/users/me", json={"locale": "en"}, headers=auth(tok))
    r = await client.post("/api/integrations/google/start", json={"capabilities": ["drive"], "next": "/app/files"}, headers=auth(tok))
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert q["hl"] == ["en"] and "https://www.googleapis.com/auth/drive.file" in q["scope"][0].split()



async def test_any_secretary_can_be_linked_to_a_file_it_never_received(client: AsyncClient, drive: FakeDrive):
    """[내 정보 → 파일]의 파일을 비서에 잇는다 (plan/77) — Drive 에서 온 파일도, 다른 비서가 받은 파일도."""
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "하나"}, headers=auth(tok))).json()
    await _connect(user["id"], ["drive"])
    async with session_scope() as db:
        await S.put(db, "oauth.google.picker_api_key", "AIza-test")
        await db.commit()
    S.invalidate("oauth.")
    await client.post("/api/drive/import", json={"file_ids": ["txt1"]}, headers=auth(tok))
    fid = (await client.get("/api/files", params={"source": "drive"}, headers=auth(tok))).json()["items"][0]["id"]
    for ag in (a,):         # Drive 파일은 어느 비서도 받은 적이 없다
        listed = (await client.get(f"/api/agents/{ag['id']}/outsider/items", params={"kind": "files"}, headers=auth(tok))).json()
        assert fid in {i["id"] for i in listed["items"]}
        r = await client.put(f"/api/agents/{ag['id']}/outsider/picks", json={"kind": "files", "scope": "picked", "ids": [fid]},
                             headers=auth(tok))
        assert r.status_code == 200, r.text


async def test_the_cloud_page_shows_where_space_goes_and_a_deleted_file_comes_back(client: AsyncClient, drive: FakeDrive):
    """[관리·설정 → 클라우드 관리] (plan/78): 출처별·종류별·큰 파일·지운 파일, 그리고 되살리기."""
    user, tok = await signup(client)
    await _connect(user["id"], ["drive"])
    async with session_scope() as db:
        await S.put(db, "oauth.google.picker_api_key", "AIza-test")
        await db.commit()
    S.invalidate("oauth.")
    await client.post("/api/drive/import", json={"file_ids": ["txt1", "sheet1"]}, headers=auth(tok))
    c = (await client.get("/api/cloud", headers=auth(tok))).json()
    assert c["totals"]["files"] == 2 and c["totals"]["trash_files"] == 0
    assert [s["source"] for s in c["by_source"]] == ["drive"] and c["by_source"][0]["files"] == 2
    assert {k["kind"] for k in c["by_kind"]} == {"text", "sheet"}
    assert c["largest"][0]["size"] >= c["largest"][-1]["size"] and c["drive"]["connected"] is True
    assert any(s["kind"] == "files" for s in c["usage"]["segments"])

    fid = c["largest"][0]["id"]
    assert (await client.delete(f"/api/files/{fid}", headers=auth(tok))).status_code == 204
    c = (await client.get("/api/cloud", headers=auth(tok))).json()
    assert c["totals"]["files"] == 1 and c["totals"]["trash_files"] == 1
    assert c["trash"][0]["id"] == fid and c["trash"][0]["purge_at"] > c["trash"][0]["deleted_at"]
    r = await client.post(f"/api/files/{fid}/restore", headers=auth(tok))
    assert r.status_code == 200 and r.json()["id"] == fid
    c = (await client.get("/api/cloud", headers=auth(tok))).json()
    assert c["totals"]["files"] == 2 and c["totals"]["trash_files"] == 0
