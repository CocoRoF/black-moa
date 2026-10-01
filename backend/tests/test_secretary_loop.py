"""비서가 나를 알게 되는 통로 (plan/45).

두 가지가 동시에 참이어야 한다. **내 비서는 내가 쓴 글을 전부 알 수 있다.** 그리고
**공개 범위는 그대로 지켜진다.** 둘을 한 조건에 묶어 뒀던 것이 이 서비스에서 가장 큰
구멍이었다: 인맥에게만 쓴 글이 가장 일기다운 글인데 비서에게는 없는 글이었다.
"""
from __future__ import annotations

import uuid as _uuid

from httpx import AsyncClient
from sqlalchemy import select

from blackmoa.core import visibility as VIS
from blackmoa.db.session import session_scope
from blackmoa.models import BlogPost, KnowledgeDocument
from blackmoa.models import User as _U
from tests.conftest import auth, signup, square_name
from tests.test_domain import _run_jobs


async def _verified(user_id: str) -> None:
    from datetime import UTC, datetime

    async with session_scope() as db:
        (await db.get(_U, _uuid.UUID(user_id))).email_verified_at = datetime.now(UTC)
        await db.commit()


async def _agent_for(owner_id: str):
    """외부인 대화를 할 비서 하나 — 기본값 그대로(정보 줄 켜짐)."""
    from blackmoa.models import Agent
    from blackmoa.services import outsider as OUT
    async with session_scope() as db:
        a = Agent(owner_id=_uuid.UUID(owner_id), name="비서", provider="fake", model_id="fake-1", outsider=dict(OUT.DEFAULTS))
        db.add(a)
        await db.commit()
        return a


async def _reaches(agent, doc_id, viewer: str) -> bool:
    from blackmoa.models import Agent
    from blackmoa.services import outsider as OUT
    async with session_scope() as db:
        a = await db.get(Agent, agent.id)
        sc = await OUT.scope(db, a, "knowledge", viewer)
        return sc is not None and sc.has(doc_id)


async def _doc_of(post_id: str) -> KnowledgeDocument | None:
    async with session_scope() as db:
        post = await db.get(BlogPost, _uuid.UUID(post_id))
        if post is None or post.knowledge_document_id is None:
            return None
        return await db.get(KnowledgeDocument, post.knowledge_document_id)


async def test_every_post_reaches_my_own_secretary(client: AsyncClient):
    user, tok = await signup(client)
    made = {}
    for level in ("public", "friends", "private"):
        r = await client.post("/api/blog", headers=auth(tok),
                              json={"body": f"{level} 로 적은 하루", "kind": "note", "visibility": level})
        assert r.status_code == 201, r.text
        made[level] = r.json()["id"]

    agent = await _agent_for(user["id"])
    for level, pid in made.items():
        doc = await _doc_of(pid)
        assert doc is not None, f"{level} 글이 비서에게 닿지 않는다"
        # 외부인에게는 글에 적힌 범위가 **그대로** 걸린다 (plan/48 §1-2, plan/57): 인맥에게만 쓴 글은
        # 인맥에게는 닿고 남에게는 안 닿는다. 예전에는 공개가 아닌 것을 전부 private 으로 눌러서,
        # 인맥에게만 쓴 글이 인맥에게도 닿지 못했다.
        want = VIS.normalize(level)
        assert await _reaches(agent, doc.id, "stranger") is (want == "public"), level
        assert await _reaches(agent, doc.id, "known") is (want in ("public", "known")), level


async def test_narrowing_a_post_stops_the_secretary_repeating_it(client: AsyncClient):
    """공개였다가 좁히면, 비서가 남에게 옮기던 것도 그 자리에서 멈춘다."""
    user, tok = await signup(client)
    agent = await _agent_for(user["id"])
    pid = (await client.post("/api/blog", headers=auth(tok),
                             json={"body": "처음엔 공개", "kind": "note", "visibility": "public"})).json()["id"]
    assert await _reaches(agent, (await _doc_of(pid)).id, "stranger")

    await client.patch(f"/api/blog/{pid}", headers=auth(tok), json={"visibility": "private"})
    doc = await _doc_of(pid)
    assert doc is not None, "좁혔다고 비서가 잊어버리면 안 된다"
    assert not await _reaches(agent, doc.id, "stranger") and not await _reaches(agent, doc.id, "known")


async def test_a_draft_is_not_a_post_yet(client: AsyncClient):
    user, tok = await signup(client)
    pid = (await client.post("/api/blog", headers=auth(tok),
                             json={"title": "쓰다 만 글", "body": "아직", "publish": False})).json()["id"]
    assert await _doc_of(pid) is None


async def test_search_gives_each_reader_only_what_is_theirs(client: AsyncClient):
    """검색 층이 **세** 세계를 가른다 (plan/48 §2).

    주인은 제 것을 전부, 인맥은 [모두 공개]와 [인맥에게만] 까지, 처음 온 사람은
    [모두 공개]만. 가운데가 이 서비스가 중간 단계를 두는 이유다: 예전에는 인맥에게만
    쓴 글이 인맥에게도 닿지 못했다.
    """
    from blackmoa.services import knowledge as K

    user, tok = await signup(client)
    for body, vis in [("모두에게 열어 둔 공지", "public"),
                      ("인맥에게만 적은 계획", "friends"),
                      ("나만 아는 메모", "private")]:
        await client.post("/api/blog", headers=auth(tok), json={"body": body, "kind": "note", "visibility": vis})
    assert await _run_jobs(["knowledge.index"]) >= 1

    agent = await _agent_for(user["id"])
    from blackmoa.models import Agent
    from blackmoa.services import outsider as OUT
    async with session_scope() as db:
        rows = (await db.execute(select(KnowledgeDocument).where(
            KnowledgeDocument.owner_id == _uuid.UUID(user["id"])))).scalars().all()
        assert len(rows) == 3

        oid = _uuid.UUID(user["id"])
        a = await db.get(Agent, agent.id)

        async def found(viewer: str) -> set[str]:
            sc = await OUT.scope(db, a, "knowledge", viewer)
            out = set()
            for q in ("공지", "계획", "메모"):
                for h in await K.search(db, oid, q, scope=sc):
                    out.add(h["title"])
            return out

        mine, friend, stranger = await found("owner"), await found("known"), await found("stranger")
        assert len(mine) == 3, mine
        assert len(friend) == 2 and len(stranger) == 1, (friend, stranger)
        assert stranger < friend < mine, "넓은 사람이 좁은 사람보다 적게 보면 안 된다"


async def test_a_photo_only_post_is_material_too(client: AsyncClient):
    """사진만 올린 글도 그 날의 기록이다 (plan/45 §2).

    비서가 사진에서 본 것을 한 줄로 적어 두면 그때부터 재료가 된다. 적기 전에는 비서에게
    빈 종이라 문서를 만들지 않는다: 빈 문서를 만드는 것보다 없는 편이 낫다.
    """
    from blackmoa.services import blog as B

    user, tok = await signup(client)
    async with session_scope() as db:
        me = await db.get(_U, _uuid.UUID(user["id"]))
        post = B.BlogPost(owner_id=me.id, slug="photo", title="사진", body="", kind="note",
                          visibility="public", status="published", images=["x"], meta={})
        # 아직 눈이 닿지 않았다.
        assert B._material(post) == ""
        post.meta = {"seen": "책상 위의 커피와 노트북"}
        assert "책상 위의 커피" in B._material(post)
        # 적힌 말이 있으면 둘 다 들어간다.
        post.body = "오늘도 여기서 일했다"
        m = B._material(post)
        assert "오늘도 여기서 일했다" in m and "책상 위의 커피" in m


async def test_every_post_with_photos_gets_looked_at(client: AsyncClient):
    """본문이 있다고 사진을 건너뛰면 안 된다 (plan/45 §2).

    처음에는 "글이 한 줄도 없는 글만" 보게 해 두었다. 그래서 운영에 있던 사진 붙은 글
    두 편이 **둘 다** 안 읽힌 채로 남아 있었다. "오늘 회식" 이라고 적고 가게 사진을 올린
    글에서, 적힌 말과 찍힌 것은 서로 다른 사실이다.
    """
    from blackmoa.services import blog as B

    user, tok = await signup(client)
    queued: list[str] = []

    async def fake_enqueue(db, kind, payload, **kw):
        queued.append(kind)

    async with session_scope() as db:
        me = await db.get(_U, _uuid.UUID(user["id"]))
        import blackmoa.services.jobs as J

        real = J.enqueue
        J.enqueue = fake_enqueue
        try:
            # 본문이 있어도 본다.
            with_body = B.BlogPost(owner_id=me.id, slug="a", title="", body="오늘 회식", kind="note",
                                   visibility="public", status="published", images=["x"], meta={})
            await B._look_at_photos(db, with_body)
            assert queued == ["post.describe_photos"], "본문이 있는 글의 사진을 건너뛰었다"

            # 이미 본 글은 다시 보지 않는다. 볼 때마다 크레딧이 나간다.
            queued.clear()
            seen_already = B.BlogPost(owner_id=me.id, slug="b", title="", body="", kind="note",
                                      visibility="public", status="published", images=["x"],
                                      meta={"seen": "책상"})
            await B._look_at_photos(db, seen_already)
            assert queued == []

            # 사진이 없으면 부를 일도 없다.
            no_photo = B.BlogPost(owner_id=me.id, slug="c", title="", body="글만", kind="note",
                                  visibility="public", status="published", images=[], meta={})
            await B._look_at_photos(db, no_photo)
            assert queued == []
        finally:
            J.enqueue = real


async def test_the_square_never_reaches_the_secretary(client: AsyncClient):
    """광장은 **익명 커뮤니티**다. 비서는 여기를 보지 않는다 (plan/51).

    예전에는 실명으로 쓴 글만 재료로 들였다. 그런데 익명이라는 말은 "그 글이 나와
    이어지지 않는다" 는 뜻이고, 내 비서가 그 글을 알고 있으면 언젠가 어떤 말끝에서
    두 이름이 만난다. 설정으로 막는 것이 아니라 **길을 내지 않는다.**

    내 글이 비서에게 가는 길은 [피드] 하나다. 거기는 실명이고 내 집이다.
    """
    from blackmoa.models import KnowledgeDocument
    from blackmoa.services import community as C

    user, tok = await signup(client)
    await _verified(user["id"])
    await square_name(client, tok)
    slug = (await client.get("/api/community/boards", headers=auth(tok))).json()["items"][0]["slug"]

    for title, body in [("첫 글", "회사 이야기를 적어 둔다."), ("둘째 글", "아무도 몰랐으면 하는 이야기.")]:
        r = await client.post("/api/community/posts", headers=auth(tok), json={"board": slug, "title": title, "body": body})
        assert r.status_code == 201, r.text

    async with session_scope() as db:
        docs = (await db.execute(select(KnowledgeDocument).where(
            KnowledgeDocument.owner_id == _uuid.UUID(user["id"])))).scalars().all()
        assert [d for d in docs if d.kind == "community"] == [], "광장 글이 비서에게 갔다"

    # 길 자체가 없다. 붙이는 함수도, 부르는 자리도.
    assert not hasattr(C, "sync_knowledge"), "광장에서 비서로 가는 다리가 되살아났다"
    import inspect

    for fn in (C.create_post, C.update_post, C.delete_post):
        assert "sync_knowledge" not in inspect.getsource(fn), fn.__name__


async def test_the_square_name_lives_on_the_account(client: AsyncClient):
    """광장 이름은 계정에 하나다 (plan/52).

    예전에는 글마다 적었다. 그래서 한 사람이 두 이름으로 흩어졌고, 한 사람은 **남의
    실명**을 필명 칸에 적어 넣었다(운영에서 실제로 있었다). 이름을 계정에 두면
    같은 사람은 늘 같은 이름이고, 자주 못 바꾸게 할 자리도 생긴다.
    """
    user, tok = await signup(client)
    await _verified(user["id"])
    slug = (await client.get("/api/community/boards", headers=auth(tok))).json()["items"][0]["slug"]

    # 이름이 없으면 쓸 수 없다. 화면은 이 코드를 보고 정하러 보낸다.
    blocked = await client.post("/api/community/posts", headers=auth(tok),
                                json={"board": slug, "title": "이름 없이", "body": "본문을 충분히 적는다."})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["code"] == "community_name_required"

    name = await square_name(client, tok)
    ids = []
    for title in ("첫 글", "둘째 글"):
        r = await client.post("/api/community/posts", headers=auth(tok),
                              json={"board": slug, "title": title, "body": "본문을 충분히 적는다."})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    for pid in ids:
        got = (await client.get(f"/api/community/posts/{pid}", headers=auth(tok))).json()
        assert got["author"]["name"] == name and got["author"]["pen_name"] and not got["author"]["id"]
        assert got["author"]["name"] != user["display_name"]


async def test_two_people_cannot_share_one_square_name(client: AsyncClient):
    """익명 게시판에서 같은 이름 둘은 서로를 사칭하는 것과 같다 (plan/52)."""
    # 이름은 **전역 유일**이라 검사끼리도 겹치면 안 된다. 그 자체가 규칙의 증거다.
    tag = _uuid.uuid4().hex[:6]
    _, mine = await signup(client)
    _, theirs = await signup(client)
    assert (await client.put("/api/users/me/community-name", json={"name": f"퇴근{tag}"},
                             headers=auth(mine))).status_code == 200
    # 앞뒤 공백이 달라도 같은 이름이다.
    for want in (f"퇴근{tag}", f"  퇴근{tag}  "):
        r = await client.put("/api/users/me/community-name", json={"name": want}, headers=auth(theirs))
        assert r.status_code == 409, (want, r.text)
        assert r.json()["error"]["code"] == "name_taken", (want, r.text)
    # 대소문자가 달라도 같은 이름이다.
    assert (await client.put("/api/users/me/community-name", json={"name": f"Coffee{tag}"},
                             headers=auth(theirs))).status_code == 200
    _, third = await signup(client)
    r = await client.put("/api/users/me/community-name", json={"name": f"coffee{tag}"}, headers=auth(third))
    assert r.status_code == 409 and r.json()["error"]["code"] == "name_taken", r.text


async def test_a_square_name_cannot_be_changed_every_day(client: AsyncClient):
    """오늘 쓴 글과 어제 쓴 글이 같은 사람의 것인지 읽는 사람이 알 수 있어야 한다.

    매일 바꿀 수 있으면 이름이 아니라 가면이 되고, 하고 싶은 말만 하고 이름을 바꿔
    도망갈 수 있다 (plan/52).
    """
    from datetime import UTC, datetime, timedelta

    from blackmoa.services import community as C

    tag = _uuid.uuid4().hex[:6]
    user, tok = await signup(client)
    # 처음 정하는 것은 바꾸는 것이 아니다. 가입하자마자 한 주를 기다릴 이유가 없다.
    assert (await client.put("/api/users/me/community-name", json={"name": f"첫{tag}"},
                             headers=auth(tok))).status_code == 200
    again = await client.put("/api/users/me/community-name", json={"name": f"둘째{tag}"}, headers=auth(tok))
    assert again.status_code == 200, again.text

    # 바꾼 뒤에는 기다린다. 얼마나 남았는지 알려 준다.
    blocked = await client.put("/api/users/me/community-name", json={"name": f"셋째{tag}"}, headers=auth(tok))
    assert blocked.status_code == 409, blocked.text
    err = blocked.json()["error"]
    assert err["code"] == "name_change_too_soon"
    assert 1 <= err["detail"]["days"] <= C.NAME_CHANGE_DAYS

    # 같은 이름으로 다시 저장하는 것은 바꾸는 것이 아니다.
    assert (await client.put("/api/users/me/community-name", json={"name": f"둘째{tag}"},
                             headers=auth(tok))).status_code == 200

    async with session_scope() as db:
        me = await db.get(_U, _uuid.UUID(user["id"]))
        me.community_name_at = datetime.now(UTC) - timedelta(days=C.NAME_CHANGE_DAYS + 1)
        await db.commit()
    assert (await client.put("/api/users/me/community-name", json={"name": f"셋째{tag}"},
                             headers=auth(tok))).status_code == 200


async def test_the_visitor_simulator_never_teaches_the_secretary(client: AsyncClient):
    """방문자 시뮬레이션은 주인이 제 비서를 시험해 보는 자리다. 거기서 나온 말이 주인에
    대한 사실이 되면 안 된다 (plan/45 §8)."""
    import inspect

    import blackmoa.pipeline.runner as R

    assert 'conv.kind != "agent" and not ids["simulated"]' in inspect.getsource(R)
