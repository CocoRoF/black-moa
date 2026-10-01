"""Pure-ASGI deny-by-default auth gate (pattern ported from Geny's RequireLoginMiddleware).

Endpoint dependencies remain the authority (they load the user); this layer only rejects
requests that carry no plausible credential outside the public allowlist, so streaming and
static paths pass untouched and an unauthenticated scan never reaches handler code.
"""
from __future__ import annotations

import re

from blackmoa.core.security import decode_access_token, decode_visitor_token

PUBLIC_EXACT = {
    "/", "/health", "/health/ready", "/metrics", "/favicon.ico", "/api/auth/status", "/api/auth/signup",
    "/api/auth/login", "/api/auth/refresh", "/api/auth/logout",
    "/api/auth/sso/pending", "/api/auth/sso/complete", "/api/auth/password/forgot", "/api/auth/password/reset", "/api/auth/email/verify",
    "/api/billing/webhook", "/api/notifications/telegram/webhook", "/api/notifications/unsubscribe",
    "/api/telemetry/client-error", "/api/admin/bootstrap-status", "/api/public/branding",
}
# Community post images carry their own signed, expiring token because an <img> tag cannot
# send an Authorization header. The handler verifies the signature; the gate only lets the
# request reach it.
PUBLIC_PREFIXES = ("/static/", "/api/public/", "/api/community/images/", "/api/internal/mcp/",
                   # The worker's relay hop (plan/38) carries its own HMAC header, checked by the handler.
                   "/internal/relay/",
                   "/docs", "/openapi.json", "/redoc")
# 대화에 붙인 파일의 서명 주소 (plan/55). 같은 이유로 관문은 통과시키고 처리기가 서명을 본다.
# 접두어가 아니라 모양으로 연다 — ``/api/uploads/`` 전체를 열면 목록·세션 인증 길까지 열린다.
PUBLIC_PATTERNS = (re.compile(r"^/api/uploads/[0-9a-fA-F-]{36}/raw$"), re.compile(r"^/api/files/[0-9a-fA-F-]{36}/thumb$"),
                   # 연결 (plan/59): 공급자의 로그인 시작·돌아오는 곳. 공급자 이름은 소문자 낱말 하나.
                   re.compile(r"^/api/auth/[a-z]+/(start|callback)$"), re.compile(r"^/api/integrations/[a-z]+/callback$"),
                   # Google 캘린더 변경 알림(plan/76) — 채널 id 와 서명 토큰을 처리기가 확인한다.
                   re.compile(r"^/api/integrations/google/push$"),
                   # 공공의 달력 한 해치 (plan/60) — 누구의 것도 아니다.
                   re.compile(r"^/api/calendar/[A-Z]{2}/\d{4}$"),
                   # 다운로드 센터의 설치본(plan/64): 주소의 서명이 곧 허락이다(링크는 로그인 토큰을 싣지 못한다).
                   re.compile(r"^/api/downloads/assets/[0-9a-fA-F-]{36}$"),
                   # 릴리스를 굽는 CI 의 알림(plan/64) — 제 열쇠(downloads.ci_key)로 따로 확인한다.
                   re.compile(r"^/api/downloads/ci$"))


class AuthGateMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES) or any(p.match(path) for p in PUBLIC_PATTERNS):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        ok = False
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            try:
                decode_access_token(token)
                ok = True
            except Exception:
                try:
                    decode_visitor_token(token)
                    ok = path.startswith("/api/public/")
                except Exception:
                    ok = False
        if not ok:
            body = b'{"error":{"code":"unauthorized","message":"authentication required"}}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        return await self.app(scope, receive, send)
