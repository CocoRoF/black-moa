import asyncio, uuid
from sqlalchemy import select
from memora.db.session import session_scope
from memora.models import Connection
from memora.providers.http import request
from memora.services import connections as CN
OWNER = uuid.UUID("06abbc3c-4343-75d8-8000-ac12a2c1711a")
async def main():
    async with session_scope() as db:
        conn = (await db.execute(select(Connection).where(Connection.owner_id == OWNER, Connection.provider == "google"))).scalars().first()
        if not conn:
            print("no connection"); return
        tok = await CN.access_token(db, conn)
        await db.commit()
    h = {"Authorization": f"Bearer {tok}"}
    got = (await request("GET", "https://www.googleapis.com/drive/v3/files", headers=h, params={"q": "trashed = false", "fields": "files(id,name,mimeType)", "pageSize": "100"})).json()
    for f in got.get("files", []):
        if f["name"] == "Northwind meeting notes" and "--all" not in __import__("sys").argv:
            continue   # 다음 녹화에서 고를 문서 — 마지막 정리에서 지운다
        print("delete", f["name"], f["mimeType"])
        await request("DELETE", f"https://www.googleapis.com/drive/v3/files/{f['id']}", headers=h)
asyncio.run(main())
