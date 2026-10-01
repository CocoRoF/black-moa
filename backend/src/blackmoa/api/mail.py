"""[내 정보 → 메일] (plan/57): 연결한 메일함의 메일과, 비서가 내 이름으로 보낸 메일."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import NotFound
from blackmoa.core.ratelimit import limiter
from blackmoa.services import connections as CN
from blackmoa.services import imap_mail as IM
from blackmoa.services import mail as MAIL

router = APIRouter(prefix="/api/mail", tags=["mail"])


@router.get("")
async def inbox(user: CurrentUser, db: DB, q: str = "", before: datetime | None = None, limit: int = 30):
    """받은 메일 — 최근부터. ``before`` 로 다음 쪽."""
    items = await MAIL.search(db, user.id, q, limit=limit, before=before)
    if before is None and await MAIL.refresh_if_stale(db, user.id):
        await db.commit()       # 끝나면 화면이 소식을 받아 다시 읽는다(plan/76)
    return {"accounts": await MAIL.accounts(db, user.id), "items": items,
            "next_before": items[-1]["received_at"] if len(items) >= max(1, min(limit, 100)) else None}


@router.get("/sent")
async def sent(user: CurrentUser, db: DB, limit: int = 50):
    return {"items": await MAIL.sent(db, user.id, limit=limit)}


@router.post("/sync", status_code=202)
async def sync(user: CurrentUser, db: DB):
    """지금 가져오기 — 메일함마다 가져오기를 건다. 끝나면 목록의 마지막 가져온 때가 바뀐다."""
    n = await MAIL.request_sync(db, user.id)
    await db.commit()
    return {"queued": n}


class AccountIn(BaseModel):
    #: gmail · naver · daum · kakao · custom
    preset: str = Field(max_length=16)
    email: str = Field(max_length=254)
    #: 메일 서비스에서 만든 앱 비밀번호(2단계 인증을 켠 계정). 저장할 때 암호화하고 다시 돌려주지 않는다.
    password: str = Field(max_length=200)
    #: custom 일 때만 — IMAP 서버 주소(993 포트).
    host: str | None = Field(default=None, max_length=253)


@router.post("/accounts", status_code=201)
async def add_account(body: AccountIn, user: CurrentUser, db: DB):
    """메일함을 잇는다(plan/74) — 먼저 실제로 들어가 보고, 되면 저장하고 가져오기를 건다."""
    # 남의 메일 서버에 비밀번호를 대 보는 통로가 되지 않게.
    limiter.check(f"imap:{user.id}", 8, 600)
    await IM.connect(db, user, preset=body.preset, email_addr=body.email, password=body.password, host=body.host)
    await db.commit()
    return {"accounts": await MAIL.accounts(db, user.id)}


@router.delete("/accounts/{conn_id}")
async def remove_account(conn_id: uuid.UUID, user: CurrentUser, db: DB):
    """메일함 연결을 끊는다 — 저장한 앱 비밀번호와 가져온 메일을 지운다."""
    c = await CN.get_owned(db, user.id, conn_id)
    if c.provider != IM.PROVIDER:
        raise NotFound("mailbox not found", code="connection_not_found")
    await CN.remove(db, c)
    await db.commit()
    return {"accounts": await MAIL.accounts(db, user.id)}


@router.get("/{mail_id}")
async def read(mail_id: str, user: CurrentUser, db: DB):
    """메일 한 통 — 본문은 메일함에서 그때 읽는다."""
    m = await MAIL.read(db, user.id, mail_id)
    await db.commit()
    return m
