"""다운로드 센터 (plan/64).

앱은 GitHub 릴리스로 나간다: 태그(``desktop-v*``)를 밀면 CI 가 세 운영체제에서 굽고 릴리스에 붙인다. 저장소가
비공개라 사람은 GitHub 에서 받을 수 없다. 그래서 서버가 릴리스를 읽고(10분마다) 설치본을 **제 저장소로 옮겨 둔
뒤** 다운로드 센터에서 내어 준다. GitHub 에 릴리스가 나가면 따로 하는 일 없이 여기서도 받을 수 있게 된다.

- 옮기는 일은 파일 하나에 작업 하나(``downloads.mirror``), 한 번에 하나씩. 설치본 하나가 100MB 를 넘는다.
- 내려받는 주소는 서명된 주소다. 브라우저의 링크는 로그인 토큰을 싣지 못하므로 주소 자체가 "받아도 된다" 를
  말한다(첨부 파일과 같은 방식). 이어받기(Range)를 받는다.
- GitHub 에서 사라진 릴리스(지웠거나 초안으로 되돌림)는 목록에서 빠지고 옮겨 둔 파일도 지운다.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core import pools
from memora.core.logging import get_logger
from memora.core.security import sign_state, verify_state
from memora.models import AppRelease, AppReleaseAsset
from memora.services import jobs as J
from memora.services import objectstore
from memora.services import settings as S

log = get_logger("memora.downloads")

GITHUB = "https://api.github.com"
URL_TTL_MIN = 180
MAX_TRIES = 5

# 운영체제마다 **설치 프로그램 하나**만 내어 준다 — 윈도는 설치 마법사(.exe), 맥은 디스크 이미지(.dmg, 새 판부터는
# Apple 칩·Intel 을 한 파일에 담은 universal), 리눅스는 설치 꾸러미(.deb). 같은 운영체제에 파일이 둘이면 사람은
# 무엇을 받아야 할지 헤맨다. AppImage 는 설치 프로그램이 아니라 내어 주지 않는다.
_KINDS = {"exe": "windows", "dmg": "macos", "deb": "linux"}
_MIME = {"exe": "application/vnd.microsoft.portable-executable", "dmg": "application/x-apple-diskimage",
         "deb": "application/vnd.debian.binary-package"}


class GithubError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def classify(name: str) -> tuple[str, str, str] | None:
    """설치 프로그램이면 (운영체제, 아키텍처, 종류). 업데이트용 부속(.blockmap, latest*.yml)과 AppImage 는 아니다."""
    m = re.search(r"\.(exe|dmg|deb)$", name)
    if not m:
        return None
    kind = m.group(1)
    low = name.lower()
    arch = "universal" if "universal" in low else "arm64" if ("arm64" in low or "aarch64" in low) else "x64"
    return _KINDS[kind], arch, kind


def version_of(tag: str, prefix: str) -> str:
    v = tag[len(prefix):] if prefix and tag.startswith(prefix) else tag
    return v.lstrip("v")[:32] or tag[:32]


SESSION_TTL_MIN = 120


async def config(db: AsyncSession) -> dict[str, Any]:
    token = str(await S.get(db, "downloads.github.token", use_cache=False) or "").strip()
    session = False
    if not token:
        # 관리자가 넣은 토큰이 없으면, CI 가 방금 건넨 짧은 토큰(아직 살아 있으면).
        t = str(await S.get(db, "downloads.github.session_token", use_cache=False) or "").strip()
        until = str(await S.get(db, "downloads.github.session_until", use_cache=False) or "")
        with contextlib.suppress(ValueError):
            if t and until and datetime.fromisoformat(until) > datetime.now(UTC):
                token, session = t, True
    return {
        "enabled": bool(await S.get(db, "downloads.enabled", use_cache=False)),
        "repo": str(await S.get(db, "downloads.github.repo", use_cache=False) or "").strip(),
        "token": token,
        "session": session,
        "prefix": str(await S.get(db, "downloads.github.tag_prefix", use_cache=False) or ""),
    }


async def accept_session(db: AsyncSession, token: str) -> None:
    """CI 의 GITHUB_TOKEN 을 받아 둔다(암호화된 설정, 두 시간 뒤나 다 옮기면 지운다)."""
    await S.put(db, "downloads.github.session_token", token.strip())
    await S.put(db, "downloads.github.session_until", (datetime.now(UTC) + timedelta(minutes=SESSION_TTL_MIN)).isoformat())
    S.invalidate("downloads.")


async def _settle_session(db: AsyncSession) -> None:
    """더 옮길 것이 없거나 시간이 지났으면 CI 의 토큰을 지운다 — 쓸 일이 끝난 토큰은 들고 있지 않는다."""
    if not str(await S.get(db, "downloads.github.session_token", use_cache=False) or ""):
        return
    until = str(await S.get(db, "downloads.github.session_until", use_cache=False) or "")
    expired = True
    with contextlib.suppress(ValueError):
        expired = not until or datetime.fromisoformat(until) <= datetime.now(UTC)
    left = (await db.execute(
        select(AppReleaseAsset.id).join(AppRelease, AppRelease.id == AppReleaseAsset.release_id)
        .where(AppRelease.gone.is_(False), AppReleaseAsset.status != "ready", AppReleaseAsset.tries < MAX_TRIES).limit(1)
    )).first()
    if expired or left is None:
        await S.put(db, "downloads.github.session_token", "")
        await S.put(db, "downloads.github.session_until", "")
        S.invalidate("downloads.")


async def ci_state(db: AsyncSession, tag: str = "") -> dict[str, Any]:
    """CI 가 기다리며 묻는 것: 그 태그(없으면 전체)의 설치본이 다 옮겨졌나."""
    q = select(AppRelease, AppReleaseAsset).join(AppReleaseAsset, AppReleaseAsset.release_id == AppRelease.id).where(AppRelease.gone.is_(False))
    if tag:
        q = q.where(AppRelease.tag == tag)
    rows = (await db.execute(q)).all()
    files = [{"tag": r.tag, "name": a.name, "status": a.status, "error": a.error, "tries": a.tries} for r, a in rows]
    failed = any(f["status"] == "failed" and f["tries"] >= MAX_TRIES for f in files)
    ready = bool(files) and all(f["status"] == "ready" for f in files)
    st = dict(await S.get(db, "downloads.status", use_cache=False) or {})
    return {"tag": tag, "found": bool(files), "ready": ready, "failed": failed, "files": files,
            "sync": {k: st.get(k) for k in ("ok", "at", "code", "error")}}


def _headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "memora-downloads"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _raise_for(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise GithubError("token_invalid", "GitHub 토큰이 맞지 않아요.")
    if r.status_code == 404:
        # 비공개 저장소에 권한이 없는 토큰도 404 를 받는다.
        raise GithubError("repo_not_found", "저장소를 찾지 못했어요. 이름과 토큰의 읽기 권한을 확인해 주세요.")
    if r.status_code in (403, 429):
        raise GithubError("rate_limited", "GitHub 가 잠시 요청을 막았어요. 조금 뒤에 다시 시도해요.")
    if r.status_code >= 400:
        raise GithubError("github_error", f"GitHub 가 {r.status_code} 로 답했어요.")


async def list_releases(repo: str, token: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as c:
        for page in range(1, 5):
            try:
                r = await c.get(f"{GITHUB}/repos/{repo}/releases", params={"per_page": 50, "page": page}, headers=_headers(token))
            except httpx.HTTPError as e:
                raise GithubError("unreachable", "GitHub 에 닿지 못했어요.") from e
            _raise_for(r)
            items = r.json()
            out.extend(items)
            if len(items) < 50:
                break
    return out


async def check(repo: str, token: str) -> dict[str, Any]:
    """관리자의 [확인]: 저장소에 닿는지, 앱 릴리스가 몇 개 보이는지."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:
            r = await c.get(f"{GITHUB}/repos/{repo}", headers=_headers(token))
        _raise_for(r)
        info = r.json()
        rels = await list_releases(repo, token)
        return {"ok": True, "private": bool(info.get("private")), "releases": len([x for x in rels if not x.get("draft")])}
    except GithubError as e:
        return {"ok": False, "code": e.code, "message": str(e)}
    except httpx.HTTPError:
        return {"ok": False, "code": "unreachable", "message": "GitHub 에 닿지 못했어요."}


async def _status(db: AsyncSession, **kw: Any) -> None:
    st = dict(await S.get(db, "downloads.status", use_cache=False) or {})
    st.update(kw)
    await S.put(db, "downloads.status", st)


async def sync(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """GitHub 의 앱 릴리스를 읽어 목록을 맞추고, 아직 옮기지 않은 설치본마다 옮기는 작업을 건다."""
    cfg = await config(db)
    if not cfg["enabled"] and not force:
        return {"skipped": "off"}
    if not cfg["repo"]:
        return {"skipped": "no_repo"}
    if not cfg["token"] and not force and await S.get(db, "downloads.ci_key", use_cache=False):
        # 토큰 없이 CI 가 알려 오는 방식이면 10분마다 두드려 봐야 비공개 저장소의 404 뿐이다. CI 를 기다린다.
        return {"skipped": "waiting_for_ci"}
    now = datetime.now(UTC)
    try:
        rels = await list_releases(cfg["repo"], cfg["token"])
    except GithubError as e:
        await _status(db, ok=False, at=now.isoformat(), code=e.code, error=str(e))
        await db.commit()
        return {"error": e.code}

    rows = {r.tag: r for r in (await db.execute(select(AppRelease))).scalars().all()}
    seen: set[str] = set()
    for rel in rels:
        tag = str(rel.get("tag_name") or "")
        if rel.get("draft") or not tag.startswith(cfg["prefix"]):
            continue
        seen.add(tag)
        row = rows.get(tag)
        published = rel.get("published_at")
        fields = {
            "version": version_of(tag, cfg["prefix"]),
            "name": str(rel.get("name") or tag)[:160],
            "notes": str(rel.get("body") or "")[:20000],
            "published_at": datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
            "prerelease": bool(rel.get("prerelease")),
            "github_id": int(rel.get("id") or 0),
            "gone": False,
            "synced_at": now,
        }
        if row is None:
            row = AppRelease(tag=tag, **fields)
            db.add(row)
            await db.flush()
            rows[tag] = row
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        have = {a.github_id: a for a in (await db.execute(select(AppReleaseAsset).where(AppReleaseAsset.release_id == row.id))).scalars().all()}
        offered: set[int] = set()
        for a in rel.get("assets") or []:
            c = classify(str(a.get("name") or ""))
            if not c or a.get("state") != "uploaded":
                continue
            gid = int(a["id"])
            offered.add(gid)
            if gid in have:
                cur = have[gid]
                cur.name = str(a["name"])[:200]
                if cur.size != int(a.get("size") or 0) and cur.status == "ready":
                    cur.status, cur.tries = "pending", 0
                cur.size = int(a.get("size") or 0)
                continue
            platform, arch, kind = c
            db.add(AppReleaseAsset(release_id=row.id, github_id=gid, name=str(a["name"])[:200], platform=platform, arch=arch,
                                   kind=kind, size=int(a.get("size") or 0), status="pending"))
        # 더는 내어 주지 않는 파일(GitHub 에서 지웠거나, 설치 프로그램이 아니게 된 것)은 옮겨 둔 것까지 지운다.
        for gid, cur in have.items():
            if gid in offered:
                continue
            if cur.storage_path:
                with contextlib.suppress(Exception):
                    await objectstore.delete(cur.storage_path)
            await db.delete(cur)
    # GitHub 에서 사라진 릴리스: 목록에서 빼고 옮겨 둔 파일을 지운다.
    for tag, row in rows.items():
        if tag in seen or row.gone:
            continue
        row.gone = True
        for a in (await db.execute(select(AppReleaseAsset).where(AppReleaseAsset.release_id == row.id))).scalars().all():
            if a.storage_path:
                with contextlib.suppress(Exception):
                    await objectstore.delete(a.storage_path)
            a.storage_path, a.status = None, "pending"
    await db.flush()

    todo = (await db.execute(
        select(AppReleaseAsset).join(AppRelease, AppRelease.id == AppReleaseAsset.release_id)
        .where(AppRelease.gone.is_(False), AppReleaseAsset.status.in_(("pending", "failed")), AppReleaseAsset.tries < MAX_TRIES)
    )).scalars().all()
    for a in todo:
        await J.enqueue(db, "downloads.mirror", {"asset_id": str(a.id)}, priority=7, dedupe_key=f"dlmirror:{a.id}")
    await _status(db, ok=True, at=now.isoformat(), code="", error="", releases=len(seen), queued=len(todo))
    await _settle_session(db)
    await db.commit()
    return {"releases": len(seen), "queued": len(todo)}


def _tmp_dir() -> Path:
    d = get_settings().upload_root / "_tmp_releases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mirror_sync(repo: str, token: str, gid: int, key: str, mime: str, expect: int) -> tuple[str, str, int]:
    """GitHub 에서 받아(임시 파일) 제 저장소에 올린다. 돌려주는 것은 (storage_path, sha256, 크기).

    GitHub 는 실제 파일을 다른 주소(서명된 저장소 주소)로 넘겨준다. httpx 는 다른 곳으로 넘어갈 때 인증 머리를
    떼므로 토큰이 그쪽으로 새지 않는다."""
    h = hashlib.sha256()
    fd, tmp = tempfile.mkstemp(dir=_tmp_dir(), suffix=".part")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out, httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as c:
            with c.stream("GET", f"{GITHUB}/repos/{repo}/releases/assets/{gid}", headers=_headers(token, "application/octet-stream")) as r:
                _raise_for(r)
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
        if expect and size != expect:
            raise GithubError("size_mismatch", f"받은 크기({size})가 GitHub 의 크기({expect})와 달라요.")
        s = get_settings()
        if objectstore.s3_enabled():
            client = objectstore._client()
            with contextlib.suppress(Exception):
                client.create_bucket(Bucket=s.s3_bucket)
            client.upload_file(tmp, s.s3_bucket, key, ExtraArgs={"ContentType": mime})
            path = f"{objectstore.S3_PREFIX}{s.s3_bucket}/{key}"
        else:
            dest = s.upload_root / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(tmp, dest)
            path = str(dest)
        return path, h.hexdigest(), size
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


async def mirror(db: AsyncSession, asset_id: uuid.UUID) -> dict[str, Any]:
    a = await db.get(AppReleaseAsset, asset_id)
    if a is None or a.status == "ready":
        return {"skipped": True}
    rel = await db.get(AppRelease, a.release_id)
    if rel is None or rel.gone:
        return {"skipped": True}
    cfg = await config(db)
    a.tries += 1
    await db.commit()
    key = f"releases/{rel.tag}/{a.name}"
    try:
        path, digest, size = await pools.to_thread("misc", _mirror_sync, cfg["repo"], cfg["token"], a.github_id, key,
                                                   _MIME.get(a.kind, "application/octet-stream"), a.size)
    except (GithubError, httpx.HTTPError, OSError) as e:
        a.status, a.error = "failed", str(e)[:500]
        await _settle_session(db)
        await db.commit()
        log.warning("downloads.mirror_failed", asset=a.name, error=str(e)[:200])
        return {"error": a.error}
    a.storage_path, a.sha256, a.size, a.status, a.error = path, digest, size, "ready", ""
    a.mirrored_at = datetime.now(UTC)
    await db.commit()
    await _settle_session(db)
    await db.commit()
    return {"ready": a.name, "size": size}


# ── 내어 주기 ────────────────────────────────────────────────────────────────


def signed_url(asset_id: uuid.UUID | str) -> str:
    return f"/api/downloads/assets/{asset_id}?t={sign_state({'dl': str(asset_id)}, ttl_minutes=URL_TTL_MIN)}"


def allowed(asset_id: uuid.UUID, token: str) -> bool:
    try:
        return verify_state(token).get("dl") == str(asset_id)
    except Exception:
        return False


def asset_out(a: AppReleaseAsset) -> dict[str, Any]:
    ready = a.status == "ready" and bool(a.storage_path)
    return {"id": str(a.id), "name": a.name, "platform": a.platform, "arch": a.arch, "kind": a.kind, "size": a.size,
            "sha256": a.sha256 if ready else None, "ready": ready, "url": signed_url(a.id) if ready else None}


_ORDER = {"windows": 0, "macos": 1, "linux": 2}


def pick(assets: list[AppReleaseAsset]) -> list[AppReleaseAsset]:
    """운영체제마다 하나. 맥은 universal 이 있으면 그것 하나, 없으면(0.8.2 까지) Apple 칩·Intel 둘."""
    out: list[AppReleaseAsset] = []
    for platform in ("windows", "macos", "linux"):
        same = [a for a in assets if a.platform == platform]
        if platform == "macos" and not any(a.arch == "universal" for a in same):
            out += sorted(same, key=lambda a: a.arch != "arm64")
            continue
        best = next((a for a in same if a.arch == "universal"), None) or next(iter(same), None)
        if best:
            out.append(best)
    return out


def release_out(r: AppRelease, assets: list[AppReleaseAsset]) -> dict[str, Any]:
    items = sorted(pick(assets), key=lambda a: (_ORDER.get(a.platform, 9), a.arch != "arm64"))
    return {"tag": r.tag, "version": r.version, "name": r.name, "notes": r.notes,
            "published_at": r.published_at.isoformat() if r.published_at else None, "prerelease": r.prerelease,
            "assets": [asset_out(a) for a in items]}


async def releases(db: AsyncSession) -> list[tuple[AppRelease, list[AppReleaseAsset]]]:
    rels = (await db.execute(select(AppRelease).where(AppRelease.gone.is_(False))
                             .order_by(AppRelease.published_at.desc().nullslast()))).scalars().all()
    if not rels:
        return []
    assets = (await db.execute(select(AppReleaseAsset).where(AppReleaseAsset.release_id.in_([r.id for r in rels])))).scalars().all()
    by: dict[uuid.UUID, list[AppReleaseAsset]] = {}
    for a in assets:
        by.setdefault(a.release_id, []).append(a)
    return [(r, by.get(r.id, [])) for r in rels]


async def listing(db: AsyncSession) -> dict[str, Any]:
    """다운로드 센터가 보는 것. 받을 수 있는 설치본이 하나라도 있는 릴리스만, 최신이 먼저."""
    out = [release_out(r, a) for r, a in await releases(db)]
    out = [r for r in out if any(x["ready"] for x in r["assets"])]
    latest = next((r for r in out if not r["prerelease"]), out[0] if out else None)
    return {"latest": latest, "releases": out}


def _range_sync(storage_path: str, start: int, end: int) -> Any:
    if storage_path.startswith(objectstore.S3_PREFIX):
        bucket, key = objectstore._split(storage_path)
        return objectstore._client().get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")["Body"]
    fh = open(storage_path, "rb")  # noqa: SIM115 — 닫는 것은 stream() 의 finally
    fh.seek(start)
    return fh


async def stream(storage_path: str, start: int, end: int) -> AsyncIterator[bytes]:
    """[start, end] 를 1MB 씩. 내려받는 사람이 느려도 서버의 메모리에 통째로 올리지 않는다."""
    body = await pools.to_thread("misc", _range_sync, storage_path, start, end)
    left = end - start + 1
    try:
        while left > 0:
            chunk = await pools.to_thread("misc", body.read, min(1 << 20, left))
            if not chunk:
                break
            left -= len(chunk)
            yield chunk
    finally:
        with contextlib.suppress(Exception):
            body.close()
