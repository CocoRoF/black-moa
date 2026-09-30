import asyncio, uuid, sys
from sqlalchemy import select, text
from memora.db.session import session_scope
from memora.models import Connection
from memora.providers.http import request
from memora.services import connections as CN
OWNER = uuid.UUID("06abbc3c-4343-75d8-8000-ac12a2c1711a")
PREFIXES = tuple(sys.argv[1:]) or ("Meeting with Jamie",)
async def main():
    async with session_scope() as db:
        conn = (await db.execute(select(Connection).where(Connection.owner_id == OWNER, Connection.provider == "google"))).scalars().first()
        tok = await CN.access_token(db, conn)
        # Memora 쪽: 미팅 일정과 미팅 요청을 지운다(데모 흔적)
        await db.execute(text("DELETE FROM schedule_events WHERE owner_id = :o AND source = 'meeting'"), {"o": OWNER})
        await db.execute(text("DELETE FROM inbox_items WHERE owner_id = :o AND kind = 'meeting_request'"), {"o": OWNER})
        await db.commit()
    h = {"Authorization": f"Bearer {tok}"}
    got = (await request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events", headers=h,
                         params={"timeMin": "2026-09-27T00:00:00+09:00", "timeMax": "2026-10-20T00:00:00+09:00", "singleEvents": "true", "maxResults": "250"})).json()
    for e in got.get("items", []):
        if str(e.get("summary", "")).startswith(PREFIXES):
            print("delete", e.get("summary"), e["start"])
            await request("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{e['id']}", headers=h, params={"sendUpdates": "none"})
asyncio.run(main())
