"""System settings (admin-owned) with defaults, secret encryption and a short in-process cache."""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.redact import mask
from blackmoa.core.security import decrypt, encrypt
from blackmoa.models import SystemSetting

# key -> (default, is_secret)
DEFAULTS: dict[str, tuple[Any, bool]] = {
    "setup_completed": (False, False),
    "branding.service_name": ("black-moa", False),
    "branding.tagline": ("당신의 진짜 비서를 만들어보세요", False),
    "branding.logo_url": ("", False),
    "signup.mode": ("open", False),
    "signup.require_email_verification": (False, False),
    # Signing up is deliberately one step. Owning a secretary — which sends mail, holds a
    # public link and spends credits — is where a reachable address starts to matter.
    "signup.verify_before_agent": (True, False),
    "providers.claude_code.auth_mode": ("oauth", False),  # oauth | api_key | setup_token
    "providers.claude_code.credentials_json": ("", True),
    "providers.claude_code.setup_token": ("", True),
    "providers.claude_code.status": ({}, False),
    # Account pool (plan/30). On by default, but inert until an administrator adds an
    # account — an empty pool falls back to the single credential above, so an upgrade
    # changes nothing until someone asks it to.
    "providers.claude_code.pool.enabled": (True, False),
    "providers.claude_code.pool.strategy": ("least_busy", False),  # least_busy | round_robin | weighted | least_recently_used
    "providers.claude_code.pool.failure_threshold": (3, False),
    "providers.claude_code.pool.failure_cooldown_s": (120, False),
    "providers.claude_code.pool.rate_limit_cooldown_s": (900, False),
    "providers.claude_code.pool.quota_cooldown_s": (3600, False),
    "providers.anthropic.api_key": ("", True),
    "providers.openai.api_key": ("", True),
    "providers.google.api_key": ("", True),
    "providers.elevenlabs.api_key": ("", True),
    "providers.voyage.api_key": ("", True),
    "providers.status": ({}, False),
    "embedding.provider": ("openai", False),
    "embedding.model": ("text-embedding-3-small", False),
    "embedding.dim": (1536, False),
    "embedding.credit_per_1k": (0.02, False),
    # 음성 (plan/67): 받아쓰기·읽어 주기를 따로 켜고 끈다. 끄면 웹·앱이 단추와 설정을 감추고 서버가 요청을 막는다.
    "stt.enabled": (True, False),
    "tts.enabled": (True, False),
    "stt.provider": ("openai", False),
    "stt.model": ("gpt-4o-mini-transcribe", False),
    "stt.credit_per_minute": (3.0, False),
    "tts.provider": ("openai", False),
    "tts.model": ("gpt-4o-mini-tts", False),
    "tts.default_voice": ("nova", False),
    "tts.credit_per_1k_chars": (15.0, False),
    # 연결 (plan/59): 공급자마다 켜기 · 로그인에 쓰기 · 사용자에게 줄 기능 · 앱 키.
    # 공급자의 칸과 기능 목록은 services/oauth 의 공급자 클래스가 정본이다.
    "oauth.google.enabled": (False, False),
    "oauth.google.login": (True, False),
    "oauth.google.features": (["calendar_read", "calendar_write", "contacts", "drive"], False),
    # Drive 파일 선택 창(plan/75): 브라우저용 API 키(Picker API, 도메인 제한)와 Cloud 프로젝트 번호. 비밀이 아니다.
    "oauth.google.picker_api_key": ("", False),
    "oauth.google.app_id": ("", False),
    "oauth.google.client_id": ("", False),
    "oauth.google.client_secret": ("", True),
    "oauth.kakao.enabled": (False, False),
    "oauth.kakao.login": (True, False),
    "oauth.kakao.features": (["calendar_read", "calendar_write", "talk_message"], False),
    "oauth.kakao.client_id": ("", False),
    "oauth.kakao.client_secret": ("", True),
    # 카카오 앱에서 OpenID Connect 를 켰는가 / [카카오계정(이메일)] 동의항목을 설정했는가.
    "oauth.kakao.oidc": (False, False),
    "oauth.kakao.email": (False, False),
    # 한국의 특별한 날 (plan/60): 내장 계산은 늘 작동하고, 한국천문연구원 특일 정보(공공데이터포털)를
    # 이으면 받아 온 해·종류를 그 대신 쓴다. 상태는 해마다 받은 때·개수·마지막 오류.
    "holidays.kasi.enabled": (False, False),
    "holidays.kasi.key": ("", True),
    "holidays.kasi.status": ({}, False),
    # 다운로드 센터 (plan/64): 앱의 GitHub 릴리스를 읽어 설치본을 옮겨 두고 여기서 내어 준다. 저장소가 비공개라
    # 읽기 권한이 있는 토큰이 있어야 한다. 태그가 이 머리로 시작하는 릴리스만 앱으로 본다.
    "downloads.enabled": (True, False),
    "downloads.github.repo": ("CocoRoF/black-moa", False),
    "downloads.github.token": ("", True),
    "downloads.github.tag_prefix": ("desktop-v", False),
    "downloads.status": ({}, False),
    # 릴리스를 굽는 CI 가 끝나면 제 GITHUB_TOKEN(이 저장소 읽기 전용, 잡이 끝나면 무효)을 건넨다. 오래 사는 토큰을
    # 서버에 두지 않고도 새 릴리스가 바로 옮겨진다. ci_key 는 CI 가 그 요청을 할 수 있다는 증표.
    "downloads.ci_key": ("", True),
    "downloads.github.session_token": ("", True),
    "downloads.github.session_until": ("", False),
    # Which relay preset the console last used — the values below are what actually matter,
    # this only reopens the form on the right provider.
    # What the ops watcher last warned about, so a standing problem is not re-sent every
    # five minutes. Cleared when the problem goes away.
    "ops.last_alert": ({}, False),
    "community.require_verified_email": (True, False),
    # What the feed calls hot. Engagement over a decaying age: raise gravity and posts fade
    # faster, raise a weight and that signal counts for more.
    "community.rank_like_weight": (3.0, False),
    "community.rank_comment_weight": (2.0, False),
    "community.rank_view_weight": (0.1, False),
    "community.rank_gravity": (1.5, False),
    "smtp.provider": ("", False),
    "smtp.host": ("", False),
    "smtp.port": (587, False),
    "smtp.user": ("", False),
    "smtp.password": ("", True),
    "smtp.from": ("", False),
    # Two identities, because they mean different things to the person receiving them.
    # `from` is the automated one nobody should answer; `from_agent` is what a secretary
    # writes as, and a reply to it goes to the owner it wrote for.
    "smtp.from_agent": ("", False),
    "smtp.use_tls": (True, False),
    "telegram.bot_token": ("", True),
    "telegram.bot_username": ("", False),
    "credits.usd_per_credit": (0.001, False),
    "credits.margin": (1.0, False),
    "credits.signup_grant": (300, False),
    "credits.low_watermark_ratio": (0.1, False),
    # Secretary-to-secretary conversations (plan/38).
    "relay.enabled": (True, False),
    "relay.max_messages": (8, False),
    "relay.hard_max_messages": (20, False),
    "relay.default_credit_cap": (40, False),
    "relay.hop_delay_s": (3, False),
    "relay.threads_per_day": (10, False),
    "relay.stall_minutes": (10, False),
    "relay.expire_hours": (24, False),
    # 비서 트리거 이벤트 (plan/54). 먼저 말을 거는 일은 제품의 리듬이라 관리자가 정한다.
    # 규칙 목록은 구조가 있어 전용 화면에서 검사하고 저장한다 ({"items": [...]}).
    "triggers.enabled": (True, False),
    "triggers.provider": ("", False),
    "triggers.model": ("", False),
    "triggers.max_per_day": (3, False),
    "triggers.lapse_after_days": (3, False),
    "triggers.min_gap_minutes": (120, False),
    "triggers.rules": ({}, False),
    "memory.distill_enabled": (True, False),
    "memory.distill_provider": ("claude_code", False),
    "memory.distill_model": ("claude-haiku-4-5-20251001", False),
    "memory.max_open_vaults": (200, False),
    "memory.idle_evict_minutes": (15, False),
    "public.turnstile_site_key": ("", False),
    "public.turnstile_secret": ("", True),
    "public.default_rate_per_minute": (8, False),
    "public.default_retention_days": (90, False),
    # 기업 기능 전체 (plan/71): 기업 페이지·리뷰·공고의 기업 연결·회사 인증, 그리고 프로필의 소속. 끄면 어디에도
    # 나가지 않고 새로 쓰이지도 않는다. 저장된 것은 남아 다시 켜면 돌아온다.
    "companies.enabled": (True, False),
    # Company directory keys (plan/33). Both are free and issued instantly, and neither is
    # required: the exchange's own list needs no key at all, so these only widen what is
    # collected — DART reaches unlisted companies, the tax office says who has closed.
    "companies.dart_key": ("", True),
    "companies.data_go_kr_key": ("", True),
    # How many companies one DART enrichment run may look up. The daily allowance is
    # 20,000 and a run is the whole directory, so this is what stops one collection
    # spending the day's budget before the others have had any.
    "companies.dart_per_run": (1000, False),
    # The day's allowance, which a run may never spend past. Counted from what has already
    # been recorded today, so two runs in one day share it rather than each taking it all.
    "companies.dart_daily_limit": (10000, False),
    # Collect on a schedule, not only when somebody presses the button. Off by default so
    # a fresh install does not start calling other people's servers unasked.
    "companies.auto_collect": (False, False),
    "stripe.secret_key": ("", True),
    "stripe.webhook_secret": ("", True),
    "stripe.price_ids": ({}, False),
    "log.level": ("INFO", False),
    # 약관·처리방침 (plan/73). 본문을 비워 두면 기본 문서(assets/legal)를 쓴다. 운영자 정보는 두 문서와 바닥글에
    # 들어간다 — 비어 있는 줄은 문서에서 빠진다. 시행일은 동의받는 판이다: 바꾸면 모두에게 다시 동의를 받는다.
    "legal.terms": ("", False),
    "legal.privacy": ("", False),
    "legal.effective_date": ("", False),
    "legal.company_name": ("", False),
    "legal.ceo_name": ("", False),
    "legal.business_no": ("", False),
    "legal.mail_order_no": ("", False),
    "legal.address": ("", False),
    "legal.phone": ("", False),
    "legal.email": ("", False),
    "legal.hosting": ("", False),
    "legal.privacy_officer": ("", False),
    "legal.privacy_officer_title": ("", False),
    "legal.privacy_email": ("", False),
    "legal.privacy_phone": ("", False),
}

_cache: dict[str, tuple[float, Any]] = {}
_TTL = 20.0


def is_secret(key: str) -> bool:
    return DEFAULTS.get(key, (None, False))[1]


def default_for(key: str) -> Any:
    return DEFAULTS.get(key, (None, False))[0]


async def get(db: AsyncSession, key: str, *, use_cache: bool = True) -> Any:
    now = time.monotonic()
    if use_cache and key in _cache and _cache[key][0] > now:
        return _cache[key][1]
    row = await db.get(SystemSetting, key)
    if row is None:
        value = default_for(key)
    else:
        raw = row.value.get("v") if isinstance(row.value, dict) else row.value
        value = decrypt(raw) if (row.is_secret and raw) else raw
    _cache[key] = (now + _TTL, value)
    return value


async def get_many(db: AsyncSession, prefix: str) -> dict[str, Any]:
    out = {k: default_for(k) for k in DEFAULTS if k.startswith(prefix)}
    rows = (await db.execute(select(SystemSetting).where(SystemSetting.key.like(prefix + "%")))).scalars().all()
    for row in rows:
        raw = row.value.get("v") if isinstance(row.value, dict) else row.value
        out[row.key] = decrypt(raw) if (row.is_secret and raw) else raw
    return out


async def put(db: AsyncSession, key: str, value: Any, *, updated_by: uuid.UUID | None = None) -> None:
    secret = is_secret(key)
    stored = encrypt(str(value)) if (secret and value) else value
    row = await db.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value={"v": stored}, is_secret=secret)
        db.add(row)
    else:
        row.value = {"v": stored}
        row.is_secret = secret
    row.updated_by = updated_by
    row.updated_at = datetime.now(UTC)
    _cache.pop(key, None)


def invalidate(prefix: str = "") -> None:
    for k in list(_cache):
        if k.startswith(prefix):
            _cache.pop(k, None)


async def public_view(db: AsyncSession, prefix: str = "") -> dict[str, Any]:
    """Admin GET view: secrets are masked, with has_value flag."""
    values = await get_many(db, prefix)
    out: dict[str, Any] = {}
    for k, v in values.items():
        if is_secret(k):
            out[k] = {"has_value": bool(v), "masked": mask(str(v)) if v else ""}
        else:
            out[k] = v
    return out
