"""AgentMemory: namespace-scoped facade used by tools, prompt blocks and the worker."""
from __future__ import annotations

import shutil
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from blackmoa.config import get_settings
from blackmoa.core import pools
from blackmoa.core import visibility as VIS
from blackmoa.core.pools import run_blocking
from blackmoa.memory.notes import Note, NoteStore
from blackmoa.memory.synapse import SynapseIndex, index_cache

#: 금고의 방. **누구에 대한 기억인가**로 나뉜다.
#:
#: `shared` 는 옛 방이다. 예전에는 방 이름이 곧 공개 여부였다: `owner` 는 주인만,
#: `shared` 는 방문자도. 그래서 "이 기억을 남에게 보일까" 라는 질문의 답이 폴더를
#: 옮기는 일이 됐고, 화면에는 공개 설정이 아니라 칸 이름으로 보였다.
#:
#: 이제 공개 범위는 **기억마다** 붙는다(`meta.visibility`, plan/48 §2). `shared` 에
#: 이미 들어 있는 것은 읽을 때 [모두 공개]로 본다 — 지금 동작 그대로다.
NAMESPACES = ("owner", "shared", "visitors")

#: 새 기억이 들어가는 방. 주인 이야기는 `owner`, 손님 이야기는 `visitors`.
WRITE_NS = {"owner": "owner", "visitor": "visitors"}


def note_level(ns: str, note: dict[str, Any]) -> str:
    """이 기억이 어디까지 나가는가.

    적혀 있으면 그대로. 안 적혀 있으면 옛 규칙을 그대로 옮긴다: `shared` 였던 것은
    방문자가 읽던 것이므로 [모두 공개], 나머지는 [비공개]. 그래서 이미 쌓인 기억의
    범위가 이 변경으로 넓어지지도 좁아지지도 않는다.
    """
    said = ((note.get("meta") or {}).get("visibility"))
    if said:
        return VIS.normalize(said)
    return "public" if ns == "shared" else "private"


def vault_root(agent_id: uuid.UUID | str) -> Path:
    return get_settings().vault_root / str(agent_id)


def namespace_root(agent_id: uuid.UUID | str, ns: str) -> Path:
    if ns not in NAMESPACES:
        raise PermissionError(f"unknown namespace {ns}")
    return vault_root(agent_id) / ns


class AgentMemory:
    """한 비서의 기억. 방이 아니라 **기억마다의 범위**가 무엇이 나갈지 정한다.

    `viewer` 는 지금 듣는 사람이 주인에게서 얼마나 가까운가다 (plan/48 §2). 주인의
    턴이면 전부 읽고, 밖에서 온 사람이면 그 사람에게 열어 둔 것만 읽는다.
    """

    def __init__(self, agent_id: uuid.UUID, audience: str, visitor_id: uuid.UUID | None = None,
                 viewer: str | None = None):
        self.agent_id = agent_id
        self.audience = audience
        self.visitor_id = visitor_id
        self.viewer = VIS.normalize_viewer(viewer if viewer is not None
                                           else ("owner" if audience == "owner" else "stranger"))
        # 외부인 대화에서 쓰는 기억 (plan/57, 비서의 [지식] 탭 기억 줄). 턴마다 러너가 맞춘다.
        #: 공개로 둔 기억을 쓰는가
        self.share_public = True
        #: 이 방문자에 대해 적어 둔 것을 쓰는가 — "다시 온 사람 기억하기"
        self.share_own = True
        # 방은 누구에 대한 기억인지로만 나뉜다. 무엇이 보이는지는 `_visible` 이 가른다.
        self.read_ns = NAMESPACES
        self.write_ns = WRITE_NS.get(audience, "visitors")

    async def _index(self, ns: str) -> SynapseIndex:
        if ns not in self.read_ns and ns != self.write_ns:
            raise PermissionError(f"namespace {ns} not readable for {self.audience}")
        return await index_cache.get(namespace_root(self.agent_id, ns))

    async def warm(self) -> dict[str, Any]:
        out = {}
        for ns in self.read_ns:
            idx = await self._index(ns)
            out[ns] = await run_blocking("memory", idx.reconcile, label="reconcile")
        return out

    def _visible(self, ns: str, note: dict[str, Any]) -> bool:
        """이 기억을 지금 듣는 사람에게 보여도 되는가.

        손님 방은 **제 것만** 본다. 남의 손님에 대해 적어 둔 것을 다른 손님이 읽으면
        그건 범위 문제가 아니라 사고다. 나머지는 기억에 붙은 범위가 정한다.
        """
        if ns == "visitors":
            if self.audience == "owner":
                return True
            if not self.share_own:
                return False
            vid = (note.get("meta") or {}).get("visitor_id") or (note.get("tags") and next((t[8:] for t in note["tags"] if t.startswith("visitor:")), None))
            return bool(vid) and str(vid) == str(self.visitor_id)
        if self.viewer != "owner" and not self.share_public:
            return False
        return VIS.visible_to(note_level(ns, note), self.viewer)

    async def search(self, query: str, *, top_k: int = 8, categories: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for ns in self.read_ns:
            idx = await self._index(ns)
            hits = await run_blocking("memory", partial(idx.search, query, top_k=top_k, kinds=categories), label="memory_search")
            for h in hits:
                n = idx.notes.read(h["id"])
                if n is None:
                    continue
                h["meta"] = n.meta
                if not self._visible(ns, h):
                    continue
                h["namespace"] = ns
                results.append(h)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    async def read(self, namespace: str, note_id: str) -> Note | None:
        if namespace not in self.read_ns:
            return None
        idx = await self._index(namespace)
        n = idx.notes.read(note_id)
        if n is None:
            return None
        if not self._visible(namespace, {"meta": n.meta, "tags": n.tags}):
            return None
        return n

    async def recent_in_conversation(self, conversation_id: str, *, namespace: str | None = None, limit: int = 40) -> list[Note]:
        """이 대화에서 이미 적어 둔 기억들 (plan/50 §2).

        같은 대화가 이어지는 동안 턴마다 증류가 돌기 때문에, 방금 적은 것을 모르면
        같은 이야기를 턴 수만큼 쌓는다. 비교는 **같은 대화 안에서만** 한다: 다른
        대화에서 같은 사람을 이야기한 것은 다른 기억이다.
        """
        ns = namespace or self.write_ns
        notes = await self.list_notes(ns, limit=limit)
        return [n for n in notes if str((n.meta or {}).get("conversation_id") or "") == str(conversation_id)]

    async def remember(self, *, title: str, body: str, category: str = "notes", tags: list[str] | None = None,
                       pinned: bool = False, importance: str = "medium", source: str = "", namespace: str | None = None,
                       meta: dict | None = None, visibility: str | None = None, note_id: str | None = None) -> Note:
        """기억 하나를 적는다.

        범위를 안 주면 **비공개**다 (plan/48 §2). 새로 생긴 기억이 저절로 밖으로
        나가면, 주인이 고르지 않은 것이 공개된 것이다.
        """
        ns = namespace or self.write_ns
        if self.audience == "visitor" and ns != "visitors":
            raise PermissionError("visitors may only write to the visitors namespace")
        meta = dict(meta or {})
        meta["visibility"] = VIS.normalize(visibility or meta.get("visibility"))
        tags = list(tags or [])
        if ns == "visitors" and self.visitor_id:
            meta["visitor_id"] = str(self.visitor_id)
            tags.append(f"visitor:{self.visitor_id}")
        idx = await self._index(ns)
        # `note_id` 가 오면 그 기억을 **고친다.** 이야기가 진행됐으면 그 줄이 자라는
        # 것이 맞고, 줄이 하나 더 생기는 것은 맞지 않다 (plan/50 §2).
        note = await pools.to_thread("memory", idx.notes.write, title=title, body=body, category=category, tags=tags,
                                       pinned=pinned, importance=importance, source=source, meta=meta, note_id=note_id)
        await run_blocking("memory", lambda: idx.index_note(note), label="index_note")
        return note

    async def forget(self, namespace: str, note_id: str) -> bool:
        if self.audience == "visitor":
            raise PermissionError("visitors cannot delete memory")
        idx = await self._index(namespace)
        ok = await pools.to_thread("memory", idx.notes.delete, note_id)
        await pools.to_thread("memory", idx.remove, note_id)
        return ok

    async def pinned_text(self, max_chars: int = 1200) -> str:
        """고정한 기억 — **지금 듣는 사람에게 보여도 되는 것만.**

        예전에는 방마다의 고정 기억을 통째로 붙였다. 그래서 외부인 대화에도 주인 방에
        고정해 둔 비공개 기억이 지시문에 실렸다 (plan/57 에서 발견). 검색과 같은 벽을 지난다.
        """
        parts: list[str] = []
        used = 0
        for ns in self.read_ns:
            if ns == "visitors":
                continue
            idx = await self._index(ns)
            notes = await pools.to_thread("memory", idx.notes.list, pinned=True, limit=50)
            for n in notes:
                if not self._visible(ns, {"meta": n.meta, "tags": n.tags}):
                    continue
                piece = f"- {n.title}: {n.body[:300]}"
                if used + len(piece) > max_chars:
                    return "\n".join(parts)
                parts.append(piece)
                used += len(piece) + 1
        return "\n".join(parts)

    async def context_block(self, query: str, *, max_chars: int = 2400, top_k: int = 6) -> str:
        """Retrieved memory rendered for the prompt."""
        hits = await self.search(query, top_k=top_k)
        lines: list[str] = []
        used = 0
        for h in hits:
            if h["score"] <= 0:
                continue
            piece = f"- [{h['category']}] {h['title']}: {h['body'][:500]}"
            if used + len(piece) > max_chars:
                break
            lines.append(piece)
            used += len(piece)
        return "\n".join(lines)

    async def learn(self, query: str, used_ids: list[tuple[str, str]]) -> None:
        by_ns: dict[str, list[str]] = {}
        for ns, nid in used_ids:
            by_ns.setdefault(ns, []).append(nid)
        for ns, ids in by_ns.items():
            if ns in self.read_ns:
                idx = await self._index(ns)
                await pools.to_thread("memory", idx.learn, query, ids)

    async def counts(self) -> dict[str, dict[str, int]]:
        out = {}
        for ns in self.read_ns:
            idx = await self._index(ns)
            out[ns] = await pools.to_thread("memory", idx.notes.counts)
        return out

    async def list_notes(self, namespace: str, *, category: str | None = None, limit: int = 100, offset: int = 0) -> list[Note]:
        if namespace not in self.read_ns:
            return []
        idx = await self._index(namespace)
        notes = await pools.to_thread("memory", idx.notes.list, category=category, limit=limit, offset=offset)
        return [n for n in notes if self._visible(namespace, {"meta": n.meta, "tags": n.tags})]


async def delete_vault(agent_id: uuid.UUID) -> None:
    root = vault_root(agent_id)
    for ns in NAMESPACES:
        await index_cache.drop(root / ns)
    if root.exists():
        await pools.to_thread("memory", shutil.rmtree, root, True)


def note_store(agent_id: uuid.UUID, ns: str) -> NoteStore:
    return NoteStore(namespace_root(agent_id, ns))
