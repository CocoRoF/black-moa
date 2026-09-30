"""SSRF-guarded fetch + DuckDuckGo search for the web tools and URL knowledge."""
from __future__ import annotations

import asyncio

from memora.core import pools
from memora.services.extract import extract
from memora.services.safe_http import check_url, safe_request

MAX_BYTES = 5 * 1024 * 1024


async def fetch_text(url: str, *, max_chars: int = 40000) -> str:
    response = await safe_request(
        "GET",
        url,
        headers={"User-Agent": "Memora/1.0 (+secretary)"},
        max_bytes=MAX_BYTES,
        timeout=20.0,
        max_redirects=3,
    )
    if response.status_code >= 400:
        raise ValueError(f"http_{response.status_code}")
    if response.status_code in (301, 302, 303, 307, 308):
        raise ValueError("too_many_redirects")
    body = response.content
    ctype = response.headers.get("content-type", "")
    is_html = "html" in ctype or body[:200].lower().lstrip().startswith(b"<!doctype") or b"<html" in body[:500].lower()
    if is_html:
        # Remote HTML is untrusted parser input too. Keep readability/lxml out
        # of the API/worker process and reuse the bounded no-network child.
        parsed = await pools.to_thread("docs", extract, body, ctype or "text/html", "remote.html")
        return parsed.text[:max_chars]
    return body.decode(response.encoding, errors="replace")[:max_chars]


async def web_search(query: str, *, max_results: int = 5) -> list[dict]:
    def _run():
        from ddgs import DDGS

        with DDGS() as d:
            return list(d.text(query, max_results=max_results))

    try:
        rows = await asyncio.wait_for(pools.to_thread("docs", _run), timeout=15)
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)[:200]}]
    return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")[:300]} for r in rows]


__all__ = ["check_url", "fetch_text", "web_search"]
