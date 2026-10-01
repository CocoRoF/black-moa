"""Markdown note store per vault namespace. Files are the source of truth; Synapse is derived."""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("conversations", "observations", "decisions", "people", "inbox", "notes", "summaries")
_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")


def slugify(title: str, limit: int = 40) -> str:
    s = _SLUG_RE.sub("-", (title or "").lower()).strip("-")
    return (s[:limit] or "note").strip("-") or "note"


@dataclass
class Note:
    id: str                      # relative path without .md, e.g. "observations/2026-09-07/coffee-x1z9"
    title: str
    body: str
    category: str
    tags: list[str] = field(default_factory=list)
    pinned: bool = False
    importance: str = "medium"
    created: str = ""
    updated: str = ""
    source: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def text_for_index(self) -> str:
        return f"{self.title}\n{self.body}"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "body": self.body, "category": self.category, "tags": self.tags,
                "pinned": self.pinned, "importance": self.importance, "created": self.created, "updated": self.updated,
                "source": self.source, "meta": self.meta}


class NoteStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.notes_dir = self.root / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    # ── paths ─────────────────────────────────────────────────────
    def _path(self, note_id: str) -> Path:
        p = (self.notes_dir / f"{note_id}.md").resolve()
        if self.notes_dir.resolve() not in p.parents:
            raise PermissionError("note path escapes namespace")
        return p

    # ── io ────────────────────────────────────────────────────────
    @staticmethod
    def _dump(note: Note) -> str:
        fm = {"title": note.title, "category": note.category, "tags": note.tags, "pinned": note.pinned,
              "importance": note.importance, "created": note.created, "updated": note.updated, "source": note.source}
        if note.meta:
            fm["meta"] = note.meta
        return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n" + note.body.strip() + "\n"

    def _load(self, path: Path) -> Note | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        fm: dict[str, Any] = {}
        body = raw
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end != -1:
                try:
                    fm = yaml.safe_load(raw[4:end]) or {}
                except Exception:
                    fm = {}
                body = raw[end + 5:]
        rel = path.relative_to(self.notes_dir).with_suffix("").as_posix()
        return Note(id=rel, title=str(fm.get("title") or path.stem), body=body.strip(), category=str(fm.get("category") or rel.split("/")[0]),
                    tags=[str(t) for t in (fm.get("tags") or [])], pinned=bool(fm.get("pinned", False)),
                    importance=str(fm.get("importance") or "medium"), created=str(fm.get("created") or ""),
                    updated=str(fm.get("updated") or ""), source=str(fm.get("source") or ""), meta=dict(fm.get("meta") or {}))

    # ── public ────────────────────────────────────────────────────
    def write(self, *, title: str, body: str, category: str = "notes", tags: list[str] | None = None,
              pinned: bool = False, importance: str = "medium", source: str = "", meta: dict | None = None,
              note_id: str | None = None) -> Note:
        if category not in CATEGORIES:
            category = "notes"
        now = datetime.now(UTC).isoformat(timespec="seconds")
        if note_id is None:
            day = datetime.now(UTC).strftime("%Y-%m-%d")
            note_id = f"{category}/{day}/{slugify(title)}-{secrets.token_hex(2)}"
            created = now
        else:
            existing = self.read(note_id)
            created = existing.created if existing else now
        note = Note(id=note_id, title=title.strip()[:200] or "untitled", body=body.strip()[:20000], category=category,
                    tags=[t.strip()[:40] for t in (tags or []) if t and t.strip()][:20], pinned=pinned,
                    importance=importance if importance in ("critical", "high", "medium", "low") else "medium",
                    created=created, updated=now, source=source, meta=meta or {})
        path = self._path(note_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(self._dump(note), encoding="utf-8")
        tmp.replace(path)
        return note

    def read(self, note_id: str) -> Note | None:
        try:
            return self._load(self._path(note_id))
        except PermissionError:
            return None

    def delete(self, note_id: str) -> bool:
        try:
            p = self._path(note_id)
        except PermissionError:
            return False
        if p.exists():
            p.unlink()
            return True
        return False

    def iter_all(self):
        for p in sorted(self.notes_dir.rglob("*.md")):
            n = self._load(p)
            if n:
                yield n

    def list(self, *, category: str | None = None, limit: int = 100, offset: int = 0, pinned: bool | None = None) -> list[Note]:
        base = self.notes_dir / category if category else self.notes_dir
        if not base.exists():
            return []
        paths = sorted(base.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        out: list[Note] = []
        for p in paths:
            n = self._load(p)
            if n is None:
                continue
            if pinned is not None and n.pinned != pinned:
                continue
            out.append(n)
        return out[offset:offset + limit]

    def manifest(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.notes_dir.rglob("*.md"):
            rel = p.relative_to(self.notes_dir).with_suffix("").as_posix()
            out[rel] = p.stat().st_mtime
        return out

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.notes_dir.rglob("*.md"):
            cat = p.relative_to(self.notes_dir).parts[0]
            out[cat] = out.get(cat, 0) + 1
        return out

    def pinned(self, max_chars: int = 1500) -> str:
        parts: list[str] = []
        used = 0
        for n in self.list(pinned=True, limit=50):
            piece = f"- {n.title}: {n.body[:300]}"
            if used + len(piece) > max_chars:
                break
            parts.append(piece)
            used += len(piece)
        return "\n".join(parts)

    def touch(self) -> float:
        return time.time()

def content_words(text: str) -> set[str]:
    """이 글의 **내용어**. 조사와 어미를 뗀 낱말들.

    글자 조각(3-gram)으로 재면 어미가 겹쳐 엉뚱한 것이 붙는다. "금요일에 배포하기로
    했다" 와 "수요일에 점심을 먹기로 했다" 가 0.30 이 나온다 — 겹치는 것은 "요일에",
    "하기로", " 했다" 뿐인데 그게 짧은 문장의 대부분이다 (plan/50 §2).

    토큰화기는 엔진 것을 그대로 쓴다. 한국어 조사 떼기는 이미 거기 있고, 여기서 또
    만들면 두 벌을 같이 고쳐야 한다.
    """
    from geny_memory_adaptor.tokenizer import strip_suffix

    out: set[str] = set()
    for raw in re.findall(r"[0-9A-Za-z가-힣]+", (text or "").lower()):
        korean = any("\uac00" <= c <= "\ud7a3" for c in raw)
        w = strip_suffix(raw) if korean else raw
        # 엔진의 조사 떼기는 `의` 를 안 뗀다. 소유격이라 매우 흔해서 그냥 두면
        # "스완의" 와 "스완" 이 남남이 된다. 엔진을 고치려면 별 패키지를 배포해야
        # 하므로 그 한 글자만 여기서 본다.
        #
        # 떼고 나서 두 글자가 안 되면 떼지 않는다: "회의" · "임의" · "편의" 처럼
        # `의` 로 끝나는 낱말은 거의 다 두 글자다.
        if korean and len(w) >= 3 and w.endswith("의"):
            w = w[:-1]
        # 한 글자는 거의 다 조사나 수사다. 낱말로 세면 아무 두 글이나 겹친다.
        if len(w) >= 2:
            out.add(w)
    return out


def overlap(a: str, b: str) -> float:
    """두 글이 얼마나 같은 이야기인가. 0에서 1 사이 (내용어 자카드).

    같은 대화가 이어지는 동안 턴마다 증류가 돌면 같은 이야기가 턴 수만큼 쌓인다.
    운영에 "스완과의 연락 시도" 가 52분 간격으로 두 개 있었다 (plan/50 §1-2).
    """
    x, y = content_words(a), content_words(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)
