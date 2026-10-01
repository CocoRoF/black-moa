"""Mapping a source's own words onto the taxonomy the community already filters by.

The point is that a company and a job posting are findable the same way. A source says
"의료용 기기 제조업" and "경기도"; the community's filters speak in codes. Region is exact —
the exchange's region strings are the same strings ``data/regions`` uses. Industry is not,
so it is a keyword map, and the original text is always kept beside the codes because the
mapping is lossy and a person should be able to see what it was derived from.
"""
from __future__ import annotations

from blackmoa.data.jobs_taxonomy import INDUSTRIES
from blackmoa.data.regions import REGIONS

#: label → 시도 code, built from the taxonomy so the two can never drift apart.
_REGION_BY_LABEL = {r["label"]: r["value"] for r in REGIONS}

#: Industry keywords → taxonomy code. Deliberately coarse: a wrong specific code is worse
#: than a right general one, so these aim at the top level and let the leaf stay empty.
_INDUSTRY_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    # Most specific first: "의료용 기기" must beat the bare "기기" in the machinery rule.
    (("게임",), "it.game"),
    # A maker of telecom equipment is a manufacturer, not a carrier — and the word
    # "통신" appears in both, so this has to come first.
    (("통신 및 방송 장비", "방송 장비", "통신장비"), "mfg.elec"),
    (("통신", "전기통신"), "it.telecom"),
    (("소프트웨어", "정보 서비스", "자료처리", "포털", "컴퓨터 프로그래밍", "정보기술",
      "데이터베이스", "시스템 통합", "온라인"), "it"),
    (("은행",), "fin.bank"),
    (("증권", "자산 운용", "투자", "신탁", "여신"), "fin.securities"),
    (("보험",), "fin.insurance"),
    (("금융", "금융 지원"), "fin"),
    (("의료용 기기", "의료기기"), "bio.device"),
    (("의약품", "제약", "생물학적 제제", "의약"), "bio.pharma"),
    (("병원", "의원", "보건"), "bio.hospital"),
    (("생명과학", "생물", "바이오"), "bio.research"),
    (("반도체", "전자집적회로"), "mfg.semi"),
    (("디스플레이", "표시장치", "전자부품", "전기장비", "영상·음향", "영상 및 음향",
      "컴퓨터 및 주변장치", "가정용 기기", "절연선", "케이블", "전구", "조명",
      "정밀기기", "측정", "제어", "항해", "의료용 기기를 제외", "광학"), "mfg.elec"),
    (("자동차", "차체", "운송장비"), "mfg.auto"),
    (("이차전지", "전지", "축전지"), "mfg.battery"),
    (("화학", "고무", "플라스틱", "비금속", "정제", "석유", "시멘트", "석회", "플라스터",
      "유리", "도자기", "비료", "농약", "살충제", "페인트", "잉크"), "mfg.chem"),
    (("기계", "장비", "금속 가공", "주조", "1차 금속", "철강", "금속", "선박", "보트",
      "항공기", "철도", "자전거"), "mfg.machine"),
    (("식료품", "음료", "담배", "식품", "곡물가공품", "도축", "육류 가공", "사료", "조제식품",
      "수산물", "떡류", "과실", "채소 가공"), "retail.food"),
    (("섬유", "의복", "가죽", "신발", "가방"), "retail.fashion"),
    (("펄프", "종이", "판지", "골판지", "가구", "목재", "인쇄"), "mfg"),
    (("종합 건설", "건설", "토목", "건축", "전문직별 공사", "전문공사", "설치 공사",
      "시설물 축조"), "const.build"),
    (("부동산",), "const.estate"),
    (("도매", "소매", "상품 중개", "유통"), "retail.offline"),
    (("운수", "항공 운송", "해상", "창고", "물류", "육상", "화물 운송", "운송관련",
      "운송 관련", "여객"), "logi.transport"),
    (("교육", "학원"), "edu"),
    (("방송", "출판", "영상", "오디오", "광고", "예술", "콘텐츠"), "media"),
    (("전기", "가스", "증기", "수도", "에너지", "발전"), "etc.energy"),
    (("농업", "어업", "임업", "작물 재배", "축산"), "etc.agri"),
    (("숙박", "음식점", "여행", "유원지", "오락", "스포츠"), "etc.travel"),
    # "연구개발" and "과학기술 서비스", not a bare "시험": that matched the 시험 inside
    # "측정, 시험, 항해, 제어 및 기타 정밀기기 제조업" and filed an instrument maker under
    # 공공·기관.
    (("연구개발", "연구 개발", "과학기술 서비스", "기술 시험", "검사 및 분석"), "public.research"),
    (("사업 지원", "사업지원", "전문 서비스", "컨설팅", "회계", "법무", "인력 공급",
      "경영 컨설팅"), "pro.consulting"),
]

_VALID = {i["value"] for i in INDUSTRIES} | {c["value"] for i in INDUSTRIES for c in i.get("children") or []}


#: Places that are not a Korean province. Foreign-incorporated companies are listed on the
#: Korean exchanges and their stated domicile is a country — two dozen of them, which is
#: two dozen companies no region filter could reach until they had a code.
_OVERSEAS = ("홍콩", "미국", "케이맨", "일본", "영국", "싱가포르", "중국", "버뮤다", "말레이시아",
             "버진", "네덜란드", "캐나다", "대만", "타이완", "룩셈부르크", "호주", "독일", "베트남")
OVERSEAS_CODE = "99"


def region_code_for(text: str) -> tuple[str, str]:
    """(code, cleaned label).

    Unknown text keeps its label and gets no code — better an unfiltered company than one
    filed under the wrong province. Two cases are not unknown though, and both are real:
    sources abbreviate ("서울"), and some listed companies are incorporated abroad.
    """
    t = (text or "").strip()
    if not t:
        return "", ""
    if t in _REGION_BY_LABEL:
        return _REGION_BY_LABEL[t], t
    if any(k in t for k in _OVERSEAS):
        return OVERSEAS_CODE, t
    # Sources abbreviate: "서울" for "서울특별시", "전북" for "전북특별자치도".
    for label, code in _REGION_BY_LABEL.items():
        if label.startswith(t) or t.startswith(label[:2]):
            return code, label
    return "", t


def industry_codes_for(text: str) -> list[str]:
    """A source's industry wording → one taxonomy code, or none.

    Matched with the spaces removed from both sides. The statistical classification writes
    "정보 서비스업" and "사업지원 서비스업" — the same words, spaced differently — and a
    keyword table that cares about that misses a tenth of the directory for no reason.
    """
    t = (text or "").strip()
    if not t:
        return []
    flat = t.replace(" ", "")
    for keywords, code in _INDUSTRY_KEYWORDS:
        if any(k.replace(" ", "") in flat for k in keywords) and code in _VALID:
            return [code]
    # Anything still unrecognised that is plainly manufacturing lands on the parent. A
    # right general answer beats no answer; a wrong specific one would be worse than both.
    if flat.endswith("제조업") and "mfg" in _VALID:
        return ["mfg"]
    return []
