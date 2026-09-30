"""한국의 특별한 날 (plan/60): 공휴일 · 대체공휴일 · 명절 · 24절기 · 기념일 · 음력.

스케줄이 한 해를 한국의 달력대로 보여 주고, 빈 시간을 셀 때 쉬는 날을 뺀다. 두 겹이다.

1. **내장 계산** — 키도 네트워크도 없이 늘 작동한다.
   - 공휴일: ``holidays`` 라이브러리(대한민국). 대체공휴일 규칙, 선거일, 이미 발표된 임시공휴일, 법 개정
     (2026년부터 노동절·제헌절)이 들어 있다. 법이 바뀌면 라이브러리 판을 올린다.
   - 음력과 음력 명절(정월대보름·단오·칠석): ``korean-lunar-calendar`` (한국천문연구원 자료, 2050년까지).
   - 24절기: ``ephem`` 으로 태양의 겉보기 황경이 15°의 배수가 되는 때를 구해 한국 시각의 날짜로.
     (겉보기 — 광행차·장동을 넣는다. 빼면 8분쯤 일러서 2025년 동지가 하루 앞당겨진다.)
   - 한식(동지 다음 날부터 105일째)과 삼복(하지 뒤 셋째·넷째 경일, 입추 뒤 첫 경일).
   - 기념일: 누구나 아는 몇 개만. 전부는 공식 출처가 준다.
2. **한국천문연구원 특일 정보** (공공데이터포털) — 관리자가 [연결 → 공휴일]에서 서비스 키를 넣고 켜면
   올해와 내년을 받아 온다. 받아 온 해·종류는 내장 계산 대신 쓴다 — 갑자기 정한 임시공휴일도, 기념일
   전부도 정부 발표 그대로다. 아직 발표되지 않은 해(개수가 모자란 해)는 내장 계산을 그대로 쓴다.
   한 해치가 다 발표되면 그해는 고정이다. 그 뒤로는 공휴일만 날마다 확인한다(임시공휴일·선거일).

**한 해치는 한 번 만들어 두고 쓴다.** 달력 한 해는 한번 정해지면 거의 바뀌지 않는다. 프로세스마다 해별로
만들어 두고(``year_of``), 내용이 바뀔 때만 바뀌는 버전(계산 방법 · 라이브러리 판 · 공식 출처 내용의
해시)이 같으면 조회 한 번 없이 그대로 쓴다. 브라우저는 ``/api/calendar/KR/{year}`` 로 한 해치를 받아
기기에 두고(ETag 로 확인만), 스케줄 화면은 사용자 일정만 불러온다.

날짜는 한국의 날짜다(시간대가 없다).
"""
from __future__ import annotations

import asyncio
import functools
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.logging import get_logger
from memora.models import SpecialDay
from memora.providers.http import ProviderHTTPError, request
from memora.services import settings as S

log = get_logger("memora.special_days")

COUNTRY = "KR"
#: 화면·도구에 나오는 순서
KINDS = ("holiday", "festival", "solar_term", "anniversary")
_ORDER = {k: i for i, k in enumerate(KINDS)}


@dataclass(frozen=True)
class Day:
    day: date
    name: str
    kind: str
    off: bool = False


# ── 이름 ────────────────────────────────────────────────────────────────

#: 출처마다 다른 이름을 하나로. 법의 이름보다 달력에서 읽히는 이름.
_NAMES = {"신정연휴": "신정", "1월1일": "신정", "기독탄신일": "성탄절"}


def _norm(name: str, d: date) -> str:
    name = " ".join(str(name).split())
    if name.endswith("대체 휴일") or name.endswith("대체휴일") or name == "대체공휴일":
        return "대체공휴일"
    name = _NAMES.get(name, name)
    # 공식 출처는 설날·추석 사흘을 모두 "설날"·"추석" 이라 부른다 — 음력으로 전날·당일·다음날을 가른다.
    if name in ("설날", "추석"):
        lm, ld, leap = lunar(d) or (0, 0, False)
        if name == "설날" and lm == 12:
            return "설날 전날"
        if name == "설날" and (lm, ld) == (1, 2):
            return "설날 다음날"
        if name == "추석" and (lm, ld) == (8, 14):
            return "추석 전날"
        if name == "추석" and (lm, ld) == (8, 16):
            return "추석 다음날"
    return name


# ── 음력 ────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=16)
def _lunar_year(year: int) -> dict[date, tuple[int, int, bool]]:
    from korean_lunar_calendar import KoreanLunarCalendar

    out: dict[date, tuple[int, int, bool]] = {}
    c = KoreanLunarCalendar()
    d = date(year, 1, 1)
    while d.year == year:
        if c.setSolarDate(d.year, d.month, d.day):
            out[d] = (c.lunarMonth, c.lunarDay, bool(c.isIntercalation))
        d += timedelta(days=1)
    return out


def lunar(d: date) -> tuple[int, int, bool] | None:
    """(음력 달, 날, 윤달인가). 음력 표가 닿지 않는 해(2051년 이후)면 없음."""
    return _lunar_year(d.year).get(d)


def _from_lunar(year: int, m: int, d: int) -> date | None:
    from korean_lunar_calendar import KoreanLunarCalendar

    c = KoreanLunarCalendar()
    if not c.setLunarDate(year, m, d, False):
        return None
    return date.fromisoformat(c.SolarIsoFormat())


# ── 24절기 ─────────────────────────────────────────────────────────────

#: 황경 0°(춘분)부터 15°씩
TERMS = ("춘분", "청명", "곡우", "입하", "소만", "망종", "하지", "소서", "대서", "입추", "처서", "백로",
         "추분", "한로", "상강", "입동", "소설", "대설", "동지", "소한", "대한", "입춘", "우수", "경칩")
_KST = timedelta(hours=9)


def _sun_longitude(t: Any) -> float:
    """태양의 겉보기 황경(그날의 분점 기준, 광행차·장동 포함), 도."""
    import ephem

    s = ephem.Sun(t)
    eq = ephem.Equatorial(s.g_ra, s.g_dec, epoch=t)
    return math.degrees(ephem.Ecliptic(eq).lon) % 360


@functools.lru_cache(maxsize=16)
def solar_terms(year: int) -> tuple[tuple[date, str, datetime], ...]:
    """그해의 24절기: (한국 날짜, 이름, 한국 시각). 이분법으로 1초 안까지 좁힌다."""
    import ephem

    out = []
    for i, name in enumerate(TERMS):
        target = i * 15.0
        # 춘분(3월 20일 무렵)을 기준으로 대략의 날을 잡는다. 소한~경칩(285°~345°)은 그해 1~3월이다.
        offset = target if target < 285 else target - 360
        guess = datetime(year, 3, 20, 12) + timedelta(days=offset / 360 * 365.2422)
        lo, hi = ephem.Date(guess - timedelta(days=12)), ephem.Date(guess + timedelta(days=12))
        for _ in range(48):
            mid = ephem.Date((lo + hi) / 2)
            if ((_sun_longitude(mid) - target + 540) % 360 - 180) < 0:
                lo = mid
            else:
                hi = mid
        at = ephem.Date(hi).datetime() + _KST
        out.append((at.date(), name, at))
    out.sort()
    return tuple(out)


def _term_day(year: int, name: str) -> date:
    return next(d for d, n, _ in solar_terms(year) if n == name)


# ── 명절·잡절 ──────────────────────────────────────────────────────────

_STEMS = "갑을병정무기경신임계"
_STEM_EPOCH = date(2026, 9, 11)     # 무자일 — 천간 '무'(4)


def _stem(d: date) -> str:
    return _STEMS[(4 + (d - _STEM_EPOCH).days) % 10]


def _gyeong(start: date, nth: int) -> date:
    """start 부터 세어 nth 번째 경일(庚日). start 가 경일이면 그날이 첫째."""
    d, k = start, 0
    while True:
        if _stem(d) == "경":
            k += 1
            if k == nth:
                return d
        d += timedelta(days=1)


def _festivals(year: int) -> list[Day]:
    out: list[Day] = []
    for (m, d), name in (((1, 15), "정월대보름"), ((5, 5), "단오"), ((7, 7), "칠석")):
        s = _from_lunar(year, m, d)
        if s:
            out.append(Day(s, name, "festival"))
    # 한식: 전해 동지 다음 날부터 105일째
    out.append(Day(_term_day(year - 1, "동지") + timedelta(days=105), "한식", "festival"))
    haji, ipchu = _term_day(year, "하지"), _term_day(year, "입추")
    out += [Day(_gyeong(haji, 3), "초복", "festival"), Day(_gyeong(haji, 4), "중복", "festival"),
            Day(_gyeong(ipchu, 1), "말복", "festival")]
    return out


# ── 기념일 (내장은 누구나 아는 몇 개만) ────────────────────────────────

_ANNIVERSARIES = ((4, 5, "식목일"), (4, 19, "4·19혁명 기념일"), (5, 8, "어버이날"), (5, 15, "스승의 날"),
                  (5, 18, "5·18민주화운동 기념일"), (6, 25, "6·25전쟁일"), (10, 1, "국군의 날"), (10, 2, "노인의 날"))


def _anniversaries(year: int) -> list[Day]:
    out = [Day(date(year, m, d), n, "anniversary") for m, d, n in _ANNIVERSARIES]
    if year < 2026:
        # 2026년 공휴일 법 개정 전에는 쉬는 날이 아니던 날들
        out += [Day(date(year, 7, 17), "제헌절", "anniversary"), Day(date(year, 5, 1), "근로자의 날", "anniversary")]
    if year >= 2020:
        # 청년의 날: 9월 셋째 토요일
        first = date(year, 9, 1)
        sat = first + timedelta(days=(5 - first.weekday()) % 7)
        out.append(Day(sat + timedelta(days=14), "청년의 날", "anniversary"))
    return out


# ── 내장 계산 ──────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=16)
def builtin(year: int) -> tuple[Day, ...]:
    """그해의 특별한 날을 내장 계산으로. 같은 해는 한 번만 계산한다."""
    import holidays as HL

    out: list[Day] = []
    for d, names in sorted(HL.country_holidays(COUNTRY, years=year, language="ko").items()):
        for n in str(names).split("; "):
            out.append(Day(d, _norm(n, d), "holiday", True))
    out += _festivals(year)
    out += [Day(d, n, "solar_term") for d, n, _ in solar_terms(year)]
    out += _anniversaries(year)
    return tuple(_dedupe(out))


def _dedupe(days: list[Day]) -> list[Day]:
    """같은 날 같은 이름은 하나 — 쉬는 날인 쪽을 남긴다(예: 제헌절이 공휴일이면 기념일 줄은 버린다)."""
    best: dict[tuple[date, str], Day] = {}
    for x in days:
        k = (x.day, x.name)
        cur = best.get(k)
        if cur is None or (x.off and not cur.off) or (x.off == cur.off and _ORDER[x.kind] < _ORDER[cur.kind]):
            best[k] = x
    return sorted(best.values(), key=lambda x: (x.day, not x.off, _ORDER[x.kind], x.name))


def builtin_version() -> str:
    import importlib.metadata as md
    return f"holidays {md.version('holidays')}"


# ── 공식 출처: 한국천문연구원 특일 정보 ─────────────────────────────────

KASI = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService"
DATASET_URL = "https://www.data.go.kr/data/15012690/openapi.do"
#: 오퍼레이션 → 우리 종류. 국경일(getHoliDeInfo)은 쉬는 날이 아닌 것(예: 옛 제헌절)만 기념일로 쓴다.
OPS = {"getRestDeInfo": "holiday", "getHoliDeInfo": "national", "getAnniversaryInfo": "anniversary",
       "get24DivisionsInfo": "solar_term", "getSundryDayInfo": "festival"}
#: 이만큼은 있어야 "그해가 발표됐다" 고 본다. 모자라면 그 종류는 내장 계산을 쓴다.
ENOUGH = {"holiday": 10, "anniversary": 20, "solar_term": 20, "festival": 3}


class KasiError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


#: 공공데이터포털이 돌려주는 오류 → 관리자 화면의 코드
_KASI_ERRORS = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR": "invalid_key",
    "SERVICE_ACCESS_DENIED_ERROR": "not_approved",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR": "quota",
    "UNREGISTERED_IP_ERROR": "ip_blocked",
    "DEADLINE_HAS_EXPIRED_ERROR": "expired",
}


def _kasi_error(text: str) -> KasiError:
    code = ""
    try:
        doc = json.loads(text)
        hdr = (doc.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader") or {}
        code = str(hdr.get("errMsg") or hdr.get("returnAuthMsg") or "")
        rh = ((doc.get("response") or {}).get("header") or {})
        if not code and rh:
            code = str(rh.get("resultMsg") or rh.get("resultCode") or "")
    except ValueError:
        # 게이트웨이가 XML 로 답할 때가 있다.
        import re
        m = re.search(r"<returnAuthMsg>([^<]+)</returnAuthMsg>", text) or re.search(r"<errMsg>([^<]+)</errMsg>", text) \
            or re.search(r"<resultMsg>([^<]+)</resultMsg>", text)
        code = m.group(1) if m else ""
    for k, v in _KASI_ERRORS.items():
        if k in code:
            return KasiError(v, code)
    return KasiError("error", (code or text)[:200])


def _items(doc: dict[str, Any]) -> list[dict[str, Any]]:
    body = ((doc.get("response") or {}).get("body") or {})
    items = body.get("items")
    if not items:          # 없으면 빈 문자열로 온다
        return []
    it = items.get("item") if isinstance(items, dict) else None
    if it is None:
        return []
    return [it] if isinstance(it, dict) else list(it)


def _key(raw: str) -> str:
    # 포털이 주는 두 가지 키 중 "Encoding" 을 붙여 넣었으면 풀어서 쓴다(보낼 때 다시 인코딩된다).
    raw = (raw or "").strip()
    return unquote(raw) if "%" in raw else raw


async def fetch(op: str, key: str, year: int, month: int) -> list[dict[str, Any]]:
    params = {"ServiceKey": _key(key), "solYear": str(year), "solMonth": f"{month:02d}", "numOfRows": "100",
              "pageNo": "1", "_type": "json"}
    try:
        r = await request("GET", f"{KASI}/{op}", params=params, retries=2)
    except ProviderHTTPError as e:
        raise _kasi_error(e.body) from e
    try:
        doc = r.json()
    except ValueError as e:
        raise _kasi_error(r.text) from e
    if "OpenAPI_ServiceResponse" in doc:
        raise _kasi_error(r.text)
    code = str(((doc.get("response") or {}).get("header") or {}).get("resultCode") or "00")
    if code not in ("00", "0000"):
        raise _kasi_error(r.text)
    return _items(doc)


def _parse(op: str, item: dict[str, Any]) -> Day | None:
    try:
        d = datetime.strptime(str(item.get("locdate")), "%Y%m%d").date()
    except ValueError:
        return None
    name = str(item.get("dateName") or "").strip()
    if not name:
        return None
    off = str(item.get("isHoliday") or "N").upper() == "Y"
    kind = OPS[op]
    if kind == "national":
        if off:
            return None           # 쉬는 국경일은 공휴일 목록에 이미 있다
        kind = "anniversary"
    if kind == "holiday":
        off = True
    return Day(d, _norm(name, d)[:80], kind, off)


async def check(key: str) -> dict[str, Any]:
    """관리자의 [설정 확인]: 이번 달 공휴일을 물어본다."""
    if not (key or "").strip():
        return {"ok": False, "code": "missing"}
    now = datetime.now(UTC) + _KST
    try:
        items = await fetch("getRestDeInfo", key, now.year, now.month)
    except KasiError as e:
        return {"ok": False, "code": e.code, "detail": e.detail}
    except Exception as e:  # noqa: BLE001 — 닿지 않으면 그렇다고
        return {"ok": False, "code": "unreachable", "detail": str(e)[:200]}
    return {"ok": True, "code": "ok", "items": len(items)}


#: 공휴일(임시공휴일·선거일)은 언제든 새로 정해질 수 있어 날마다 확인한다. 나머지는 한 해치가 다 발표되면 고정.
HOLIDAY_OP = "getRestDeInfo"
FULL_OPS = ("getHoliDeInfo", "getAnniversaryInfo", "get24DivisionsInfo", "getSundryDayInfo")
_OP_KINDS = {"getRestDeInfo": {"holiday"}, "getHoliDeInfo": {"anniversary"}, "getAnniversaryInfo": {"anniversary"},
             "get24DivisionsInfo": {"solar_term"}, "getSundryDayInfo": {"festival"}}
#: 한 해치가 다 발표되지 않았으면 이만큼마다 다시 받아 본다.
FULL_EVERY = timedelta(days=7)


async def _fetch_year(year: int, key: str, ops: tuple[str, ...]) -> list[Day]:
    sem = asyncio.Semaphore(4)

    async def one(op: str, month: int) -> list[Day]:
        async with sem:
            return [x for x in (_parse(op, it) for it in await fetch(op, key, year, month)) if x is not None]

    parts = await asyncio.gather(*(one(op, m) for op in ops for m in range(1, 13)))
    return _dedupe([x for part in parts for x in part if x.day.year == year])


def _digest(days: list[Day]) -> str:
    import hashlib
    h = hashlib.sha1()
    for x in sorted(days, key=lambda x: (x.day, x.kind, x.name)):
        h.update(f"{x.day.isoformat()}|{x.kind}|{x.name}|{int(x.off)}\n".encode())
    return h.hexdigest()[:16]


def _complete(counts: dict[str, int]) -> bool:
    """공휴일을 뺀 종류가 다 발표됐는가 — 그러면 그해는 공휴일만 확인한다."""
    return all(counts.get(k, 0) >= ENOUGH[k] for k in ("festival", "solar_term", "anniversary"))


async def sync_year(db: AsyncSession, year: int, key: str, *, full: bool = True) -> dict[str, Any]:
    """그해를 받아 온다. ``full`` 이 아니면 공휴일만. 한 오퍼레이션이라도 실패하면 아무것도 바꾸지 않는다.

    받은 종류마다: 내용이 같으면 쓰지 않는다(버전이 그대로 — 화면이 다시 받지 않는다). 전에 넉넉히
    있던 종류가 모자라게 오면(포털의 일시 오류) 앞의 것을 그대로 둔다.
    """
    ops = (HOLIDAY_OP, *FULL_OPS) if full else (HOLIDAY_OP,)
    got = await _fetch_year(year, key, ops)
    kinds = set().union(*(_OP_KINDS[op] for op in ops))
    have = [x for x in (await _official(db, [year]))[year]]
    changed: list[str] = []
    kept: list[str] = []
    for k in sorted(kinds):
        new = [x for x in got if x.kind == k]
        old = [x for x in have if x.kind == k]
        if len(old) >= ENOUGH[k] and len(new) < ENOUGH[k]:
            kept.append(k)
            continue
        if _digest(new) == _digest(old):
            continue
        await db.execute(delete(SpecialDay).where(SpecialDay.country == COUNTRY, SpecialDay.year == year,
                                                  SpecialDay.source == "kasi", SpecialDay.kind == k))
        now = datetime.now(UTC)
        for x in new:
            db.add(SpecialDay(country=COUNTRY, year=year, day=x.day, kind=x.kind, name=x.name, off=x.off, source="kasi",
                              fetched_at=now))
        changed.append(k)
    await db.flush()
    rows = (await _official(db, [year]))[year]
    counts = {k: sum(1 for x in rows if x.kind == k) for k in KINDS}
    return {"counts": counts, "digest": _digest(rows), "changed": changed, "kept": kept}


async def sync(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """켜져 있으면 올해와 내년을 확인한다. 한 해치가 다 발표된 해는 공휴일만(임시공휴일 때문에), 아직이면
    일주일마다 전부. ``force`` 는 관리자의 [지금 받기] — 전부 다시."""
    if not await S.get(db, "holidays.kasi.enabled") and not force:
        return {"skipped": "off"}
    key = str(await S.get(db, "holidays.kasi.key") or "")
    if not key:
        return {"skipped": "no_key"}
    status = dict(await S.get(db, "holidays.kasi.status", use_cache=False) or {})
    now = datetime.now(UTC)
    this = (now + _KST).year
    out: dict[str, Any] = {}
    for y in (this, this + 1):
        st = dict(status.get(str(y)) or {})
        last_full = datetime.fromisoformat(st["full_at"]) if st.get("full_at") else None
        full = force or (not st.get("complete") and (last_full is None or now - last_full >= FULL_EVERY))
        try:
            r = await sync_year(db, y, key, full=full)
        except KasiError as e:
            status["last_error"] = {"at": now.isoformat(), "code": e.code, "detail": e.detail}
            log.warning("kasi sync failed", year=y, code=e.code, detail=e.detail)
            out[str(y)] = {"error": e.code}
            break
        except Exception as e:  # noqa: BLE001
            status["last_error"] = {"at": now.isoformat(), "code": "unreachable", "detail": str(e)[:200]}
            out[str(y)] = {"error": "unreachable"}
            break
        st.update({"checked_at": now.isoformat(), "counts": r["counts"], "digest": r["digest"]})
        if full:
            st["full_at"] = now.isoformat()
            st["complete"] = _complete(r["counts"])
        if r["changed"]:
            st["changed_at"] = now.isoformat()
        status[str(y)] = st
        status.pop("last_error", None)
        out[str(y)] = {"full": full, "changed": r["changed"], "kept": r["kept"], **r["counts"]}
    await S.put(db, "holidays.kasi.status", status)
    return out


# ── 한 해치: 한 번 만들어 두고 쓴다 ───────────────────────────────────

#: 계산 방법이 바뀌면 올린다 — 화면과 캐시가 새로 받는다.
ALGO = "1"


async def _official(db: AsyncSession, years: list[int]) -> dict[int, list[Day]]:
    rows = (await db.execute(select(SpecialDay).where(SpecialDay.country == COUNTRY, SpecialDay.year.in_(years)))).scalars().all()
    out: dict[int, list[Day]] = {y: [] for y in years}
    for r in rows:
        out.setdefault(r.year, []).append(Day(r.day, r.name, r.kind, bool(r.off)))
    return out


def merge(year: int, official: list[Day]) -> tuple[list[Day], dict[str, str]]:
    """그해의 날들과, 종류마다 어디서 왔는지. 공식 출처가 넉넉히 준 종류만 내장 계산을 대신한다."""
    base = builtin(year)
    sources: dict[str, str] = {}
    out: list[Day] = []
    for k in KINDS:
        theirs = [x for x in official if x.kind == k]
        if len(theirs) >= ENOUGH[k]:
            sources[k] = "kasi"
            out += theirs
        else:
            sources[k] = "builtin"
            out += [x for x in base if x.kind == k]
    return _dedupe(out), sources


@functools.lru_cache(maxsize=16)
def lunar_codes(year: int) -> tuple[str | None, ...]:
    """그해의 날마다 음력을 "8.15"(윤달이면 "L6.1")로. 음력 표가 닿지 않는 날은 없음."""
    lu = _lunar_year(year)
    out: list[str | None] = []
    d = date(year, 1, 1)
    while d.year == year:
        x = lu.get(d)
        out.append(f"{'L' if x[2] else ''}{x[0]}.{x[1]}" if x else None)
        d += timedelta(days=1)
    return tuple(out)


@dataclass
class Year:
    """한 해치. 버전은 내용이 바뀔 때만 바뀐다(계산 방법 · 라이브러리 판 · 공식 출처의 내용)."""

    year: int
    version: str
    sources: dict[str, str]
    days: list[Day]
    by_date: dict[date, list[Day]]


_YEARS: dict[int, Year] = {}
_YEARS_MAX = 64
#: 브라우저가 볼 수 있는 해 — 음력 표가 2050년까지다.
YEAR_MIN, YEAR_MAX = 1990, 2050


def _version(year: int, status: dict[str, Any]) -> str:
    import hashlib
    digest = (status.get(str(year)) or {}).get("digest") or "-"
    return hashlib.sha1(f"{ALGO}|{builtin_version()}|{digest}".encode()).hexdigest()[:16]


async def year_of(db: AsyncSession, year: int) -> Year:
    """그해 한 해치. 이 프로세스에 만들어 둔 것이 같은 버전이면 그대로 — 조회 한 번 없이."""
    from memora.core import pools

    status = dict(await S.get(db, "holidays.kasi.status") or {})
    ver = _version(year, status)
    hit = _YEARS.get(year)
    if hit is not None and hit.version == ver:
        return hit
    # 처음 한 번은 천문 계산·음력이 든다 — 이벤트 루프를 붙잡지 않게 스레드에서.
    await pools.to_thread("misc", builtin, year)
    days, sources = merge(year, (await _official(db, [year]))[year])
    by: dict[date, list[Day]] = {}
    for x in days:
        by.setdefault(x.day, []).append(x)
    y = Year(year=year, version=ver, sources=sources, days=days, by_date=by)
    if len(_YEARS) >= _YEARS_MAX:
        _YEARS.pop(next(iter(_YEARS)))
    _YEARS[year] = y
    return y


async def payload(db: AsyncSession, year: int) -> dict[str, Any]:
    """브라우저에 보내는 한 해치: 특별한 날(이름이 있는 날만)과 날마다의 음력."""
    from memora.core import pools

    y = await year_of(db, year)
    codes = await pools.to_thread("misc", lunar_codes, year)
    return {"country": COUNTRY, "year": year, "version": y.version, "sources": y.sources,
            "days": {d.isoformat(): {"off": any(x.off for x in xs), "names": [{"name": x.name, "kind": x.kind, "off": x.off} for x in xs]}
                     for d, xs in sorted(y.by_date.items())},
            "lunar": list(codes)}


async def between(db: AsyncSession, start: date, end: date) -> dict[str, dict[str, Any]]:
    """기간의 날마다: 쉬는 날인가, 이름들, 음력 (비서 도구가 쓴다)."""
    if end < start or (end - start).days > 400:
        return {}
    years = {y: await year_of(db, y) for y in range(start.year, end.year + 1)}
    out: dict[str, dict[str, Any]] = {}
    d = start
    while d <= end:
        xs = years[d.year].by_date.get(d, [])
        lu = lunar(d)
        out[d.isoformat()] = {
            "off": any(x.off for x in xs),
            "names": [{"name": x.name, "kind": x.kind, "off": x.off} for x in xs],
            "lunar": {"month": lu[0], "day": lu[1], "leap": lu[2]} if lu else None,
        }
        d += timedelta(days=1)
    return out


async def off_days(db: AsyncSession, start: date, end: date) -> dict[date, str]:
    """기간의 쉬는 날과 그 이름(여럿이면 가운뎃점으로). 빈 시간 계산이 쓴다."""
    out: dict[date, str] = {}
    for yr in range(start.year, end.year + 1):
        y = await year_of(db, yr)
        for d, xs in y.by_date.items():
            if start <= d <= end:
                names = [x.name for x in xs if x.off]
                if names:
                    out[d] = "·".join(dict.fromkeys(names))
    return out


async def status(db: AsyncSession) -> dict[str, Any]:
    """관리자 화면: 해마다 종류별 출처·개수·버전·확인한 때·바뀐 때, 두 출처가 쉬는 날을 다르게 본 날."""
    st = dict(await S.get(db, "holidays.kasi.status", use_cache=False) or {})
    this = (datetime.now(UTC) + _KST).year
    years = [this, this + 1]
    off = await _official(db, years)
    out = []
    for yr in years:
        days, sources = merge(yr, off.get(yr, []))
        mine = {x.day: x.name for x in builtin(yr) if x.off}
        theirs: dict[date, str] = {}
        for x in off.get(yr, []):
            if x.off:
                theirs.setdefault(x.day, x.name)
        official_holidays = sources["holiday"] == "kasi"
        ys = st.get(str(yr)) or {}
        out.append({
            "year": yr, "sources": sources, "version": _version(yr, st),
            "counts": {k: sum(1 for x in days if x.kind == k) for k in KINDS},
            "off_days": len({x.day for x in days if x.off}),
            "checked_at": ys.get("checked_at"), "changed_at": ys.get("changed_at"), "complete": bool(ys.get("complete")),
            # 공식 출처가 그해 공휴일을 줬을 때만 견준다 — 아직 발표 전이면 다를 수밖에 없다.
            "only_official": [{"date": d.isoformat(), "name": n} for d, n in sorted(theirs.items()) if d not in mine]
            if official_holidays else [],
            "only_builtin": [{"date": d.isoformat(), "name": n} for d, n in sorted(mine.items()) if d not in theirs]
            if official_holidays else [],
        })
    return {"years": out, "last_error": st.get("last_error"), "builtin": builtin_version()}
