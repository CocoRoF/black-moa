"""Heading-aware chunking with token targets and a hard UTF-8 byte cap (plan/09)."""
from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")
TARGET, MAX_T, OVERLAP = 700, 1000, 100
MAX_BYTES = 7000
_HEAD = re.compile(r"^(#{1,4})\s+(.*)$")
_PAGE = re.compile(r"^\[page (\d+)\]$")


@dataclass
class Chunk:
    ordinal: int
    text: str
    tokens: int
    heading: str
    page: int | None


def count_tokens(t: str) -> int:
    return len(_enc.encode(t, disallowed_special=()))


def _split_paragraph(p: str) -> list[str]:
    toks = _enc.encode(p, disallowed_special=())
    out = []
    i = 0
    while i < len(toks):
        piece = toks[i:i + MAX_T]
        out.append(_enc.decode(piece))
        i += MAX_T - OVERLAP if len(toks) - i > MAX_T else MAX_T
    return out


def _byte_cap(t: str) -> list[str]:
    b = t.encode("utf-8")
    if len(b) <= MAX_BYTES:
        return [t]
    out = []
    while b:
        piece = b[:MAX_BYTES]
        cut = piece.rfind(b"\n") if len(b) > MAX_BYTES else len(piece)
        if cut < MAX_BYTES // 2:
            cut = len(piece)
        out.append(b[:cut].decode("utf-8", errors="ignore"))
        b = b[cut:]
    return [x for x in out if x.strip()]


def chunk_text(text: str, *, max_chunks: int = 1500) -> list[Chunk]:
    heading_path: list[str] = []
    page: int | None = None
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0
    buf_heading = ""
    buf_page: int | None = None

    def flush():
        nonlocal buf, buf_tokens
        if not buf:
            return
        body = "\n".join(buf).strip()
        if body:
            for piece in _byte_cap(body):
                chunks.append(Chunk(len(chunks), piece, count_tokens(piece), buf_heading, buf_page))
        buf, buf_tokens = [], 0

    for raw in text.split("\n"):
        line = raw.rstrip()
        m = _PAGE.match(line.strip())
        if m:
            page = int(m.group(1))
            continue
        h = _HEAD.match(line)
        if h:
            flush()
            level = len(h.group(1))
            heading_path = heading_path[:level - 1] + [h.group(2).strip()]
            buf_heading = " > ".join(heading_path)
            buf_page = page
            buf.append(line)
            buf_tokens += count_tokens(line)
            continue
        t = count_tokens(line)
        if t > MAX_T:
            flush()
            for piece in _split_paragraph(line):
                buf_heading = " > ".join(heading_path)
                buf_page = page
                chunks.append(Chunk(len(chunks), piece, count_tokens(piece), buf_heading, buf_page))
            continue
        if buf_tokens + t > TARGET and buf_tokens > 0:
            flush()
            buf_heading = " > ".join(heading_path)
            buf_page = page
        if not buf:
            buf_heading = " > ".join(heading_path)
            buf_page = page
        buf.append(line)
        buf_tokens += t
        if len(chunks) >= max_chunks:
            raise ValueError("too_many_chunks")
    flush()
    return chunks[:max_chunks]
