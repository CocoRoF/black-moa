"""A person's own writing (plan/41 §4).

The point of the blog is that writing once is enough: the post is a page at the author's
address and, at the same moment, something their secretary can answer from. These tests
hold that pairing, and the line that keeps private words out of a stranger's answer.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient
from sqlalchemy import select

from blackmoa.db.session import session_scope
from blackmoa.models import Agent, KnowledgeDocument, ShareLink, User
from tests.conftest import auth, signup


async def _open_page(user_id: str, handle: str) -> None:
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(user_id))
        u.mail_handle = handle
        a = Agent(owner_id=u.id, name="비서", provider="fake", model_id="fake-1")
        db.add(a)
        await db.flush()
        db.add(ShareLink(owner_id=u.id, agent_id=a.id, code=handle, status="active"))
        await db.commit()


async def _reaches(owner_id: str, viewer: str) -> set[str]:
    """그 사람의 비서가 외부인 대화에서 이 사람(viewer)에게 쓰는 피드 글 사본의 제목 (plan/57)."""
    from blackmoa.services import outsider as OUT
    async with session_scope() as db:
        a = (await db.execute(select(Agent).where(Agent.owner_id == _uuid.UUID(owner_id)))).scalars().first()
        sc = await OUT.scope(db, a, "knowledge", viewer)
        docs = await _docs(owner_id)
    return {d.title for d in docs if sc is not None and sc.has(d.id)}


async def _docs(owner_id: str) -> list[KnowledgeDocument]:
    async with session_scope() as db:
        return list((await db.execute(select(KnowledgeDocument).where(
            KnowledgeDocument.owner_id == _uuid.UUID(owner_id), KnowledgeDocument.kind == "blog"))).scalars().all())


async def test_publishing_puts_the_post_on_the_page_and_into_the_secretary(client: AsyncClient):
    user, tok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _open_page(user["id"], f"writer{tag}")

    r = await client.post("/api/blog", headers=auth(tok), json={
        "title": "비서와 일하는 법", "body": "저는 아침마다 비서에게 일정을 묻습니다.\n\n그리고 답장을 맡깁니다."})
    assert r.status_code == 201, r.text
    post = r.json()
    assert post["slug"] == "비서와-일하는-법" and post["status"] == "published" and post["visibility"] == "public"

    # On the page, for anybody.
    page = (await client.get(f"/api/public/people/writer{tag}")).json()
    assert [p["slug"] for p in page["posts"]] == ["비서와-일하는-법"]
    assert page["posts"][0]["excerpt"].startswith("저는 아침마다")
    one = (await client.get(f"/api/public/people/writer{tag}/posts/비서와-일하는-법")).json()
    assert one["post"]["body"].startswith("저는 아침마다") and one["display_name"]

    # And in the secretary's material, as one document that carries the same words.
    docs = await _docs(user["id"])
    assert len(docs) == 1 and await _reaches(user["id"], "stranger") == {"비서와 일하는 법"}
    assert (docs[0].meta or {}).get("body", "").startswith("저는 아침마다")
    assert (docs[0].meta or {}).get("blog_post_id") == post["id"]


async def test_editing_a_post_edits_what_the_secretary_knows(client: AsyncClient):
    user, tok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _open_page(user["id"], f"editor{tag}")
    post = (await client.post("/api/blog", headers=auth(tok), json={"title": "첫 글", "body": "처음 쓴 내용"})).json()

    r = await client.patch(f"/api/blog/{post['id']}", headers=auth(tok), json={"body": "고쳐 쓴 내용"})
    assert r.status_code == 200
    docs = await _docs(user["id"])
    assert len(docs) == 1 and (docs[0].meta or {}).get("body") == "고쳐 쓴 내용"

    # Taking it down takes it out of both places.
    assert (await client.patch(f"/api/blog/{post['id']}", headers=auth(tok), json={"status": "draft"})).status_code == 200
    assert await _docs(user["id"]) == []
    assert (await client.get(f"/api/public/people/editor{tag}")).json()["posts"] == []
    assert (await client.get(f"/api/public/people/editor{tag}/posts/첫-글")).status_code == 404

    # And deleting it leaves nothing behind.
    assert (await client.patch(f"/api/blog/{post['id']}", headers=auth(tok), json={"status": "published"})).status_code == 200
    assert len(await _docs(user["id"])) == 1
    assert (await client.delete(f"/api/blog/{post['id']}", headers=auth(tok))).status_code == 200
    assert await _docs(user["id"]) == []


async def test_who_may_read_what(client: AsyncClient):
    """Three shelves. A stranger sees one, a friend sees two, the author sees all three.

    비서는 셋을 **전부** 읽는다(plan/45 §2). 다만 남에게 옮길 수 있는 것은 공개된 것
    하나뿐이고, 그 경계는 문서에 붙은 딱지가 지킨다.
    """
    author, atok = await signup(client)
    friend, ftok = await signup(client)
    stranger, stok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _open_page(author["id"], f"three{tag}")

    for vis, title in (("public", "누구나"), ("friends", "친구에게만"), ("private", "나만")):
        assert (await client.post("/api/blog", headers=auth(atok),
                                  json={"title": title, "body": f"{title} 읽는 글", "visibility": vis})).status_code == 201

    # 셋 다 내 비서가 닿을 수 있는 재료가 된다. 외부인에게는 글에 적힌 범위를 **그대로**
    # 따른다: 인맥에게만 쓴 글은 인맥에게만 나가야 하고, 인맥이 공개 링크로 물으면 닿아야
    # 한다 (plan/48 §1-2). 피드 글은 프로필의 것이라 비서의 [지식] 탭 정보 줄을 따른다 (plan/57).
    docs = await _docs(author["id"])
    assert sorted(d.title for d in docs) == sorted(["누구나", "친구에게만", "나만"])
    assert await _reaches(author["id"], "stranger") == {"누구나"}
    assert await _reaches(author["id"], "known") == {"누구나", "친구에게만"}
    async with session_scope() as db:
        a = (await db.execute(select(Agent).where(Agent.owner_id == _uuid.UUID(author["id"])))).scalars().first()
        a.outsider = {"profile": False, "knowledge": "off"}
        await db.commit()
    assert await _reaches(author["id"], "known") == set()

    assert [p["title"] for p in (await client.get(f"/api/public/people/three{tag}")).json()["posts"]] == ["누구나"]
    assert [p["title"] for p in (await client.get(f"/api/public/people/three{tag}", headers=auth(stok))).json()["posts"]] == ["누구나"]

    # 인맥: each of them connects to the other (plan/43).
    await client.post(f"/api/network/people/{friend['id']}/follow", headers=auth(atok))
    await client.post(f"/api/network/people/{author['id']}/follow", headers=auth(ftok))
    titles = [p["title"] for p in (await client.get(f"/api/public/people/three{tag}", headers=auth(ftok))).json()["posts"]]
    assert titles == ["친구에게만", "누구나"] or titles == ["누구나", "친구에게만"], titles
    assert (await client.get(f"/api/public/people/three{tag}/posts/친구에게만", headers=auth(ftok))).status_code == 200
    assert (await client.get(f"/api/public/people/three{tag}/posts/친구에게만", headers=auth(stok))).status_code == 404
    assert (await client.get(f"/api/public/people/three{tag}/posts/나만", headers=auth(ftok))).status_code == 404
    assert (await client.get(f"/api/public/people/three{tag}/posts/나만", headers=auth(atok))).status_code == 200


async def test_two_posts_with_the_same_title_get_their_own_addresses(client: AsyncClient):
    user, tok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _open_page(user["id"], f"same{tag}")
    a = (await client.post("/api/blog", headers=auth(tok), json={"title": "일기", "body": "하나"})).json()
    b = (await client.post("/api/blog", headers=auth(tok), json={"title": "일기", "body": "둘"})).json()
    assert a["slug"] == "일기" and b["slug"] == "일기-2"
    # A published post keeps its address even when the title changes: somebody may have linked to it.
    assert (await client.patch(f"/api/blog/{a['id']}", headers=auth(tok), json={"title": "고친 제목"})).json()["slug"] == "일기"


async def test_a_post_needs_a_title_and_something_in_it(client: AsyncClient):
    _, tok = await signup(client)
    assert (await client.post("/api/blog", headers=auth(tok), json={"title": "  ", "body": "내용"})).status_code == 422
    assert (await client.post("/api/blog", headers=auth(tok), json={"title": "제목", "body": "   "})).status_code == 422


async def test_one_persons_post_is_not_anothers_to_edit(client: AsyncClient):
    a_user, atok = await signup(client)
    _, btok = await signup(client)
    tag = _uuid.uuid4().hex[:6]
    await _open_page(a_user["id"], f"mineonly{tag}")
    post = (await client.post("/api/blog", headers=auth(atok), json={"title": "내 글", "body": "내용"})).json()
    assert (await client.patch(f"/api/blog/{post['id']}", headers=auth(btok), json={"body": "가로채기"})).status_code == 404
    assert (await client.delete(f"/api/blog/{post['id']}", headers=auth(btok))).status_code == 404
