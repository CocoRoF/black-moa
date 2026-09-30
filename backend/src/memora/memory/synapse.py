"""Synapse (geny-memory-adaptor) index per namespace, with manifest-diff reconcile and process LRU."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from geny_memory_adaptor import MemoryBusy, SynapseConfig, SynapseMemory

from memora.core import pools
from memora.core.logging import get_logger
from memora.memory.notes import Note, NoteStore

log = get_logger("memora.memory.synapse")

_IMPORTANCE = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5}


class SynapseIndex:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.mem = SynapseMemory(SynapseConfig(path=str(self.root / "synapse.db"), dim=256, store_text=True,
                                               store_text_maxlen=6000, top_k=8))
        self.notes = NoteStore(self.root)
        self._lock = threading.Lock()
        self.last_used = time.monotonic()

    # all methods below are SYNC — callers wrap with pools.to_thread("memory", ...)
    def index_note(self, note: Note) -> None:
        with self._lock:
            self.mem.index(note.id, note.text_for_index(), title=note.title, kind=note.category, tags=tuple(note.tags),
                           importance=_IMPORTANCE.get(note.importance, 1.0), pinned=note.pinned)

    def remove(self, note_id: str) -> None:
        with self._lock:
            try:
                self.mem.remove(note_id)
            except Exception:
                pass

    def reconcile(self) -> dict[str, int]:
        """Diff note files vs index manifest; index stale, drop orphans."""
        with self._lock:
            indexed = self.mem.manifest()  # id -> (updated_at, sha)
        files = self.notes.manifest()
        stale = [nid for nid, mtime in files.items()
                 if nid not in indexed or not indexed[nid][1] or abs((indexed[nid][0] or 0) - mtime) > 1.0]
        orphans = [nid for nid in indexed if nid not in files]
        items = []
        for nid in stale:
            n = self.notes.read(nid)
            if n:
                items.append(dict(node_id=n.id, text=n.text_for_index(), title=n.title, kind=n.category, tags=tuple(n.tags),
                                  importance=_IMPORTANCE.get(n.importance, 1.0), pinned=n.pinned,
                                  updated_at=files[nid]))
        with self._lock:
            if items:
                self.mem.index_many(items)
            for nid in orphans:
                try:
                    self.mem.remove(nid)
                except Exception:
                    pass
        return {"indexed": len(items), "removed": len(orphans)}

    def search(self, query: str, *, top_k: int = 8, kinds: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        try:
            with self._lock:
                hits = self.mem.search(query, top_k=top_k, kinds=list(kinds) if kinds else None, timeout=5.0)
        except MemoryBusy:
            log.warning("synapse busy; degrading to empty", root=str(self.root))
            return []
        out = []
        for h in hits:
            n = self.notes.read(h.id)
            if n is None:
                continue
            out.append({"id": h.id, "score": float(h.score), "title": n.title, "category": n.category,
                        "tags": n.tags, "pinned": n.pinned, "body": n.body[:800], "sources": list(h.sources)})
        return out

    def learn(self, query: str, used_ids: list[str]) -> None:
        # Retrieval is never a reward; only explicit use signals reach here.
        try:
            with self._lock:
                for nid in used_ids:
                    self.mem.trust_feedback(nid, True)
        except Exception:
            pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return self.mem.stats()

    def close(self) -> None:
        with self._lock:
            try:
                self.mem.close()
            except Exception:
                pass


class IndexCache:
    """Process-wide LRU of open SynapseIndex instances keyed by namespace root."""

    def __init__(self, max_open: int = 200):
        self._max = max_open
        self._items: OrderedDict[str, SynapseIndex] = OrderedDict()
        self._lock = asyncio.Lock()
        self._opening: dict[str, asyncio.Lock] = {}

    def _touch(self, key: str) -> SynapseIndex | None:
        idx = self._items.get(key)
        if idx is not None:
            idx.last_used = time.monotonic()
            self._items.move_to_end(key)
        return idx

    async def get(self, root: Path) -> SynapseIndex:
        key = str(root)
        async with self._lock:
            idx = self._touch(key)
            if idx is not None:
                return idx
            opening = self._opening.setdefault(key, asyncio.Lock())
        # one opener per namespace: two concurrent SynapseMemory(...) on the same synapse.db race on schema
        # creation ("database is locked") and would leave two writers / a leaked handle.
        async with opening:
            async with self._lock:
                idx = self._touch(key)
                if idx is not None:
                    return idx
            idx = await pools.to_thread("memory", SynapseIndex, root)
            async with self._lock:
                self._items[key] = idx
                self._items.move_to_end(key)
                self._opening.pop(key, None)
                while len(self._items) > self._max:
                    _, old = self._items.popitem(last=False)
                    await pools.to_thread("memory", old.close)
            return idx

    async def evict_idle(self, idle_seconds: float) -> int:
        now = time.monotonic()
        n = 0
        async with self._lock:
            for key in list(self._items):
                idx = self._items[key]
                if now - idx.last_used > idle_seconds:
                    self._items.pop(key)
                    await pools.to_thread("memory", idx.close)
                    n += 1
        return n

    async def drop(self, root: Path) -> None:
        async with self._lock:
            idx = self._items.pop(str(root), None)
        if idx:
            await pools.to_thread("memory", idx.close)

    def open_count(self) -> int:
        return len(self._items)


index_cache = IndexCache()
