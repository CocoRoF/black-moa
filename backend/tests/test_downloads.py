"""다운로드 센터 (plan/64).

GitHub 릴리스가 나가면 따로 하는 일 없이 Memora 에서 받을 수 있어야 한다. 저장소가 비공개라 서버가 릴리스를
읽어 설치본을 제 저장소로 옮겨 두고, 서명된 주소로 내어 준다. GitHub 는 여기서 흉내 낸다.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import AppReleaseAsset, Job, User
from memora.services import downloads as D
from tests.conftest import auth, signup

BLOB = bytes(range(256)) * 400  # 102,400 바이트


def _rel(tag: str, *, rid: int, draft: bool = False, assets: list[tuple[int, str]] = ()) -> dict:
    return {"id": rid, "tag_name": tag, "name": f"Memora 앱 {tag}", "body": "- 아바타가 그대로 섭니다", "draft": draft,
            "prerelease": False, "published_at": f"2026-09-{10 + rid % 10:02d}T00:00:00Z",
            "assets": [{"id": aid, "name": n, "size": len(BLOB), "state": "uploaded"} for aid, n in assets]}


def _github(monkeypatch, releases: list[dict], tmp_path: Path) -> list[int]:
    fetched: list[int] = []

    async def fake_list(repo, token):
        return releases

    def fake_mirror(repo, token, gid, key, mime, expect):
        fetched.append(gid)
        p = tmp_path / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(BLOB)
        return str(p), "ab" * 32, len(BLOB)

    monkeypatch.setattr(D, "list_releases", fake_list)
    monkeypatch.setattr(D, "_mirror_sync", fake_mirror)
    return fetched


async def _mirror_all() -> None:
    async with session_scope() as db:
        jobs = (await db.execute(select(Job).where(Job.kind == "downloads.mirror"))).scalars().all()
        ids = [uuid.UUID(j.payload["asset_id"]) for j in jobs]
    for aid in ids:
        async with session_scope() as db:
            await D.mirror(db, aid)


def test_only_installers_are_offered():
    assert D.classify("Memora_windows_0.8.1.exe") == ("windows", "x64", "exe")
    assert D.classify("Memora_macos_arm64_0.8.1.dmg") == ("macos", "arm64", "dmg")
    assert D.classify("Memora_macos_universal_0.8.3.dmg") == ("macos", "universal", "dmg")
    assert D.classify("Memora_linux_0.8.1.deb") == ("linux", "x64", "deb")
    # 설치 프로그램이 아닌 것과 자동 업데이트용 부속은 사람이 받을 것이 아니다.
    for n in ("Memora_linux_0.8.1.AppImage", "Memora_windows_0.8.1.exe.blockmap", "latest.yml", "latest-mac.yml", "builder-debug.yml"):
        assert D.classify(n) is None
    assert D.version_of("desktop-v0.8.1", "desktop-v") == "0.8.1"


async def test_a_github_release_becomes_downloadable_here(client: AsyncClient, monkeypatch, tmp_path):
    fetched = _github(monkeypatch, [
        _rel("desktop-v0.8.1", rid=81, assets=[(1, "Memora_windows_0.8.1.exe"), (2, "Memora_macos_arm64_0.8.1.dmg"),
                                               (3, "Memora_linux_0.8.1.AppImage"), (4, "Memora_windows_0.8.1.exe.blockmap")]),
        _rel("desktop-v0.8.2", rid=82, draft=True, assets=[(5, "Memora_windows_0.8.2.exe")]),   # 초안은 아직 아니다
        _rel("v0.1.0", rid=10, assets=[(6, "server.tar.gz")]),                                  # 앱이 아닌 릴리스
    ], tmp_path)
    async with session_scope() as db:
        r = await D.sync(db, force=True)
    assert r == {"releases": 1, "queued": 2}

    _, tok = await signup(client)
    # 옮기기 전에는 목록에 없다 — 받을 수 없는 것을 보여 주지 않는다.
    assert (await client.get("/api/downloads", headers=auth(tok))).json()["latest"] is None

    await _mirror_all()
    assert sorted(fetched) == [1, 2]
    j = (await client.get("/api/downloads", headers=auth(tok))).json()
    latest = j["latest"]
    assert latest["version"] == "0.8.1" and "아바타" in latest["notes"]
    assert [a["kind"] for a in latest["assets"]] == ["exe", "dmg"]
    win = latest["assets"][0]
    assert win["ready"] and win["url"].startswith(f"/api/downloads/assets/{win['id']}?t=")

    # 받는다: 로그인 머리 없이 서명된 주소만으로, 처음부터 끝까지.
    full = await client.get(win["url"])
    assert full.status_code == 200 and full.content == BLOB
    assert "attachment" in full.headers["content-disposition"] and "Memora_windows_0.8.1.exe" in full.headers["content-disposition"]
    assert full.headers["accept-ranges"] == "bytes"
    # 이어받기.
    part = await client.get(win["url"], headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == BLOB[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(BLOB)}"
    tail = await client.get(win["url"], headers={"Range": "bytes=-10"})
    assert tail.status_code == 206 and tail.content == BLOB[-10:]
    assert (await client.get(win["url"], headers={"Range": f"bytes={len(BLOB)}-"})).status_code == 416
    # 처음부터 받은 것만 센다.
    async with session_scope() as db:
        assert (await db.get(AppReleaseAsset, uuid.UUID(win["id"]))).downloads == 1


async def test_a_download_link_is_only_for_its_own_file(client: AsyncClient, monkeypatch, tmp_path):
    _github(monkeypatch, [_rel("desktop-v0.9.0", rid=90, assets=[(11, "Memora_windows_0.9.0.exe"), (12, "Memora_linux_0.9.0.deb")])], tmp_path)
    async with session_scope() as db:
        await D.sync(db, force=True)
    await _mirror_all()
    _, tok = await signup(client)
    a, b = (await client.get("/api/downloads", headers=auth(tok))).json()["latest"]["assets"]
    t_of_a = a["url"].split("?t=")[1]
    assert (await client.get(f"/api/downloads/assets/{b['id']}?t={t_of_a}")).status_code == 403
    assert (await client.get(f"/api/downloads/assets/{a['id']}?t=garbage")).status_code == 403
    # 목록은 로그인한 사람만.
    assert (await client.get("/api/downloads")).status_code == 401


async def test_a_release_removed_on_github_disappears_here(client: AsyncClient, monkeypatch, tmp_path):
    rel = _rel("desktop-v1.0.0", rid=100, assets=[(21, "Memora_windows_1.0.0.exe")])
    releases = [rel]
    _github(monkeypatch, releases, tmp_path)
    async with session_scope() as db:
        await D.sync(db, force=True)
    await _mirror_all()
    _, tok = await signup(client)
    url = (await client.get("/api/downloads", headers=auth(tok))).json()["latest"]["assets"][0]["url"]
    releases.clear()
    async with session_scope() as db:
        await D.sync(db, force=True)
    assert (await client.get("/api/downloads", headers=auth(tok))).json()["latest"] is None
    assert (await client.get(url)).status_code == 404


async def test_the_admin_sets_where_releases_come_from(client: AsyncClient):
    user, _ = await signup(client)
    async with session_scope() as db:
        (await db.get(User, uuid.UUID(user["id"]))).role = "admin"
        await db.commit()
    tok = (await client.post("/api/auth/login", json={"email": user["email"], "password": "correct-horse-9"})).json()["access_token"]
    _, utok = await signup(client)
    assert (await client.get("/api/admin/downloads", headers=auth(utok))).status_code == 403
    j = (await client.get("/api/admin/downloads", headers=auth(tok))).json()
    assert j["repo"] == "CocoRoF/my-first-secretary-geny" and j["tag_prefix"] == "desktop-v" and j["enabled"] is True
    r = await client.put("/api/admin/downloads", json={"token": "ghp_" + "x" * 36}, headers=auth(tok))
    assert r.status_code == 200
    got = r.json()["token"]
    assert got["has_value"] and "x" * 36 not in got["masked"], "토큰은 다시 내보내지 않는다"
    assert (await client.put("/api/admin/downloads", json={"repo": "not a repo"}, headers=auth(tok))).status_code == 422


async def test_the_release_ci_hands_over_a_short_lived_token(client: AsyncClient, monkeypatch, tmp_path):
    """오래 사는 토큰을 서버에 두지 않는다: CI 가 제 GITHUB_TOKEN 을 건네고, 다 옮기면 서버는 그것을 지운다."""
    from memora.services import settings as S
    used: list[str] = []

    async def fake_list(repo, token):
        used.append(token)
        return [_rel("desktop-v2.0.0", rid=200, assets=[(31, "Memora_windows_2.0.0.exe")])]

    def fake_mirror(repo, token, gid, key, mime, expect):
        used.append(token)
        p = tmp_path / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(BLOB)
        return str(p), "cd" * 32, len(BLOB)

    monkeypatch.setattr(D, "list_releases", fake_list)
    monkeypatch.setattr(D, "_mirror_sync", fake_mirror)
    async with session_scope() as db:
        await S.put(db, "downloads.ci_key", "k" * 40)
        await S.put(db, "downloads.github.token", "")
        await db.commit()
    S.invalidate("downloads.")

    # 열쇠가 없거나 틀리면 받지 않는다.
    body = {"github_token": "ghs_" + "t" * 36, "tag": "desktop-v2.0.0"}
    assert (await client.post("/api/downloads/ci", json=body)).status_code == 403
    assert (await client.post("/api/downloads/ci", json=body, headers={"Authorization": "Bearer wrong"})).status_code == 403
    key = {"Authorization": "Bearer " + "k" * 40}
    assert (await client.post("/api/downloads/ci", json=body, headers=key)).status_code == 202

    # 10분마다의 확인은 토큰이 없으면 두드리지 않는다(CI 를 기다린다) — 여기서는 CI 가 건넸으니 읽는다.
    async with session_scope() as db:
        assert (await D.sync(db))["releases"] >= 1
    await _mirror_all()
    assert set(used) == {"ghs_" + "t" * 36}, "CI 가 건넨 토큰으로 읽고 옮긴다"
    st = (await client.get("/api/downloads/ci?tag=desktop-v2.0.0", headers=key)).json()
    assert st["ready"] and not st["failed"] and st["files"][0]["status"] == "ready"
    # 다 옮겼으니 토큰은 지워졌다.
    async with session_scope() as db:
        assert (await S.get(db, "downloads.github.session_token", use_cache=False)) == ""
        assert (await D.sync(db)) == {"skipped": "waiting_for_ci"}
    assert (await client.get("/api/downloads/ci?tag=desktop-v2.0.0")).status_code == 403


async def test_one_installer_for_each_system(client: AsyncClient, monkeypatch, tmp_path):
    """같은 운영체제에 파일이 둘이면 사람은 무엇을 받아야 할지 헤맨다. 설치 프로그램 하나씩만."""
    releases = [_rel("desktop-v3.0.0", rid=300, assets=[
        (41, "Memora_windows_3.0.0.exe"), (42, "Memora_macos_universal_3.0.0.dmg"), (43, "Memora_macos_arm64_3.0.0.dmg"),
        (44, "Memora_linux_3.0.0.AppImage"), (45, "Memora_linux_3.0.0.deb")])]
    _github(monkeypatch, releases, tmp_path)
    async with session_scope() as db:
        await D.sync(db, force=True)
    await _mirror_all()
    _, tok = await signup(client)
    latest = (await client.get("/api/downloads", headers=auth(tok))).json()["latest"]
    assert [(a["platform"], a["kind"], a["arch"]) for a in latest["assets"]] == [
        ("windows", "exe", "x64"), ("macos", "dmg", "universal"), ("linux", "deb", "x64")]

    # 예전 판(universal 이 없던 때)의 맥은 칩마다 하나씩 남는다.
    releases[0]["assets"] = [a for a in releases[0]["assets"] if "universal" not in a["name"]] + [
        {"id": 46, "name": "Memora_macos_x64_3.0.0.dmg", "size": len(BLOB), "state": "uploaded"}]
    async with session_scope() as db:
        await D.sync(db, force=True)
    await _mirror_all()
    latest = (await client.get("/api/downloads", headers=auth(tok))).json()["latest"]
    assert [(a["platform"], a["arch"]) for a in latest["assets"]] == [
        ("windows", "x64"), ("macos", "arm64"), ("macos", "x64"), ("linux", "x64")]
    # GitHub 에서 빠진 universal 은 옮겨 둔 것까지 지웠다.
    async with session_scope() as db:
        assert not (await db.execute(select(AppReleaseAsset).where(AppReleaseAsset.github_id == 42))).scalars().first()
