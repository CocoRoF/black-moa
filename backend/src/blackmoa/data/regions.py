"""Korean administrative regions, two levels deep.

Codes are the statutory 법정동 prefixes: two digits for a 시·도, five for a 시·군·구. Using
the official codes rather than names means a posting keeps pointing at the same place when
a district is renamed, and it is what any later join against public data will expect.

Seoul, the metropolitan cities and Sejong list their 구/군 directly. The provinces list
their 시/군; the 구 inside a large 시 (수원 장안구 and the like) are folded into their city,
because nobody filters a job search below that.
"""

from __future__ import annotations

REGIONS: list[dict] = [
    {"value": "11", "label": "서울특별시", "keywords": "seoul 서울", "children": [
        {"value": "11680", "label": "강남구", "keywords": "gangnam"},
        {"value": "11740", "label": "강동구"}, {"value": "11305", "label": "강북구"},
        {"value": "11500", "label": "강서구"}, {"value": "11620", "label": "관악구"},
        {"value": "11215", "label": "광진구"}, {"value": "11530", "label": "구로구"},
        {"value": "11545", "label": "금천구"}, {"value": "11350", "label": "노원구"},
        {"value": "11320", "label": "도봉구"}, {"value": "11230", "label": "동대문구"},
        {"value": "11590", "label": "동작구"}, {"value": "11440", "label": "마포구"},
        {"value": "11410", "label": "서대문구"}, {"value": "11650", "label": "서초구"},
        {"value": "11200", "label": "성동구"}, {"value": "11290", "label": "성북구"},
        {"value": "11710", "label": "송파구"}, {"value": "11470", "label": "양천구"},
        {"value": "11560", "label": "영등포구"}, {"value": "11170", "label": "용산구"},
        {"value": "11380", "label": "은평구"}, {"value": "11110", "label": "종로구"},
        {"value": "11140", "label": "중구"}, {"value": "11260", "label": "중랑구"},
    ]},
    {"value": "26", "label": "부산광역시", "keywords": "busan", "children": [
        {"value": "26440", "label": "강서구"}, {"value": "26410", "label": "금정구"},
        {"value": "26290", "label": "남구"}, {"value": "26170", "label": "동구"},
        {"value": "26260", "label": "동래구"}, {"value": "26230", "label": "부산진구"},
        {"value": "26320", "label": "북구"}, {"value": "26530", "label": "사상구"},
        {"value": "26380", "label": "사하구"}, {"value": "26140", "label": "서구"},
        {"value": "26500", "label": "수영구"}, {"value": "26470", "label": "연제구"},
        {"value": "26200", "label": "영도구"}, {"value": "26110", "label": "중구"},
        {"value": "26350", "label": "해운대구"}, {"value": "26710", "label": "기장군"},
    ]},
    {"value": "27", "label": "대구광역시", "keywords": "daegu", "children": [
        {"value": "27200", "label": "남구"}, {"value": "27140", "label": "동구"},
        {"value": "27230", "label": "북구"}, {"value": "27170", "label": "서구"},
        {"value": "27260", "label": "수성구"}, {"value": "27290", "label": "달서구"},
        {"value": "27110", "label": "중구"}, {"value": "27710", "label": "달성군"},
        {"value": "27720", "label": "군위군"},
    ]},
    {"value": "28", "label": "인천광역시", "keywords": "incheon", "children": [
        {"value": "28245", "label": "계양구"}, {"value": "28710", "label": "강화군"},
        {"value": "28177", "label": "미추홀구"}, {"value": "28237", "label": "부평구"},
        {"value": "28185", "label": "연수구"}, {"value": "28200", "label": "남동구"},
        {"value": "28140", "label": "동구"}, {"value": "28260", "label": "서구"},
        {"value": "28110", "label": "중구"}, {"value": "28720", "label": "옹진군"},
    ]},
    {"value": "29", "label": "광주광역시", "keywords": "gwangju", "children": [
        {"value": "29200", "label": "광산구"}, {"value": "29155", "label": "남구"},
        {"value": "29170", "label": "동구"}, {"value": "29140", "label": "북구"},
        {"value": "29110", "label": "서구"},
    ]},
    {"value": "30", "label": "대전광역시", "keywords": "daejeon", "children": [
        {"value": "30230", "label": "대덕구"}, {"value": "30110", "label": "동구"},
        {"value": "30170", "label": "서구"}, {"value": "30200", "label": "유성구"},
        {"value": "30140", "label": "중구"},
    ]},
    {"value": "31", "label": "울산광역시", "keywords": "ulsan", "children": [
        {"value": "31140", "label": "남구"}, {"value": "31170", "label": "동구"},
        {"value": "31200", "label": "북구"}, {"value": "31110", "label": "중구"},
        {"value": "31710", "label": "울주군"},
    ]},
    {"value": "36", "label": "세종특별자치시", "keywords": "sejong", "children": []},
    {"value": "41", "label": "경기도", "keywords": "gyeonggi 경기", "children": [
        {"value": "41281", "label": "고양시"}, {"value": "41290", "label": "과천시"},
        {"value": "41210", "label": "광명시"}, {"value": "41610", "label": "광주시"},
        {"value": "41310", "label": "구리시"}, {"value": "41410", "label": "군포시"},
        {"value": "41570", "label": "김포시"}, {"value": "41360", "label": "남양주시"},
        {"value": "41250", "label": "동두천시"}, {"value": "41190", "label": "부천시"},
        {"value": "41130", "label": "성남시"}, {"value": "41110", "label": "수원시"},
        {"value": "41390", "label": "시흥시"}, {"value": "41270", "label": "안산시"},
        {"value": "41550", "label": "안성시"}, {"value": "41170", "label": "안양시"},
        {"value": "41630", "label": "양주시"}, {"value": "41830", "label": "양평군"},
        {"value": "41670", "label": "여주시"}, {"value": "41800", "label": "연천군"},
        {"value": "41150", "label": "의정부시"}, {"value": "41430", "label": "의왕시"},
        {"value": "41500", "label": "이천시"}, {"value": "41220", "label": "평택시"},
        {"value": "41650", "label": "포천시"}, {"value": "41450", "label": "하남시"},
        {"value": "41590", "label": "화성시"}, {"value": "41461", "label": "용인시"},
        {"value": "41480", "label": "파주시"},
    ]},
    {"value": "51", "label": "강원특별자치도", "keywords": "gangwon 강원", "children": [
        {"value": "51110", "label": "춘천시"}, {"value": "51130", "label": "원주시"},
        {"value": "51150", "label": "강릉시"}, {"value": "51170", "label": "동해시"},
        {"value": "51190", "label": "태백시"}, {"value": "51210", "label": "속초시"},
        {"value": "51230", "label": "삼척시"}, {"value": "51720", "label": "홍천군"},
        {"value": "51730", "label": "횡성군"}, {"value": "51750", "label": "영월군"},
        {"value": "51760", "label": "평창군"}, {"value": "51770", "label": "정선군"},
        {"value": "51780", "label": "철원군"}, {"value": "51790", "label": "화천군"},
        {"value": "51800", "label": "양구군"}, {"value": "51810", "label": "인제군"},
        {"value": "51820", "label": "고성군"}, {"value": "51830", "label": "양양군"},
    ]},
    {"value": "43", "label": "충청북도", "keywords": "chungbuk 충북", "children": [
        {"value": "43110", "label": "청주시"}, {"value": "43130", "label": "충주시"},
        {"value": "43150", "label": "제천시"}, {"value": "43720", "label": "보은군"},
        {"value": "43730", "label": "옥천군"}, {"value": "43740", "label": "영동군"},
        {"value": "43745", "label": "증평군"}, {"value": "43750", "label": "진천군"},
        {"value": "43760", "label": "괴산군"}, {"value": "43770", "label": "음성군"},
        {"value": "43800", "label": "단양군"},
    ]},
    {"value": "44", "label": "충청남도", "keywords": "chungnam 충남", "children": [
        {"value": "44131", "label": "천안시"}, {"value": "44150", "label": "공주시"},
        {"value": "44180", "label": "보령시"}, {"value": "44200", "label": "아산시"},
        {"value": "44210", "label": "서산시"}, {"value": "44230", "label": "논산시"},
        {"value": "44250", "label": "계룡시"}, {"value": "44270", "label": "당진시"},
        {"value": "44710", "label": "금산군"}, {"value": "44760", "label": "부여군"},
        {"value": "44770", "label": "서천군"}, {"value": "44790", "label": "청양군"},
        {"value": "44800", "label": "홍성군"}, {"value": "44810", "label": "예산군"},
        {"value": "44825", "label": "태안군"},
    ]},
    {"value": "52", "label": "전북특별자치도", "keywords": "jeonbuk 전북", "children": [
        {"value": "52111", "label": "전주시"}, {"value": "52130", "label": "군산시"},
        {"value": "52140", "label": "익산시"}, {"value": "52180", "label": "정읍시"},
        {"value": "52190", "label": "남원시"}, {"value": "52210", "label": "김제시"},
        {"value": "52710", "label": "완주군"}, {"value": "52720", "label": "진안군"},
        {"value": "52730", "label": "무주군"}, {"value": "52740", "label": "장수군"},
        {"value": "52750", "label": "임실군"}, {"value": "52770", "label": "순창군"},
        {"value": "52790", "label": "고창군"}, {"value": "52800", "label": "부안군"},
    ]},
    {"value": "46", "label": "전라남도", "keywords": "jeonnam 전남", "children": [
        {"value": "46110", "label": "목포시"}, {"value": "46130", "label": "여수시"},
        {"value": "46150", "label": "순천시"}, {"value": "46170", "label": "나주시"},
        {"value": "46230", "label": "광양시"}, {"value": "46710", "label": "담양군"},
        {"value": "46720", "label": "곡성군"}, {"value": "46730", "label": "구례군"},
        {"value": "46770", "label": "고흥군"}, {"value": "46780", "label": "보성군"},
        {"value": "46790", "label": "화순군"}, {"value": "46800", "label": "장흥군"},
        {"value": "46810", "label": "강진군"}, {"value": "46820", "label": "해남군"},
        {"value": "46830", "label": "영암군"}, {"value": "46840", "label": "무안군"},
        {"value": "46860", "label": "함평군"}, {"value": "46870", "label": "영광군"},
        {"value": "46880", "label": "장성군"}, {"value": "46890", "label": "완도군"},
        {"value": "46900", "label": "진도군"}, {"value": "46910", "label": "신안군"},
    ]},
    {"value": "47", "label": "경상북도", "keywords": "gyeongbuk 경북", "children": [
        {"value": "47110", "label": "포항시"}, {"value": "47130", "label": "경주시"},
        {"value": "47150", "label": "김천시"}, {"value": "47170", "label": "안동시"},
        {"value": "47190", "label": "구미시"}, {"value": "47210", "label": "영주시"},
        {"value": "47230", "label": "영천시"}, {"value": "47250", "label": "상주시"},
        {"value": "47280", "label": "문경시"}, {"value": "47290", "label": "경산시"},
        {"value": "47730", "label": "의성군"}, {"value": "47750", "label": "청송군"},
        {"value": "47760", "label": "영양군"}, {"value": "47770", "label": "영덕군"},
        {"value": "47820", "label": "청도군"}, {"value": "47830", "label": "고령군"},
        {"value": "47840", "label": "성주군"}, {"value": "47850", "label": "칠곡군"},
        {"value": "47900", "label": "예천군"}, {"value": "47920", "label": "봉화군"},
        {"value": "47930", "label": "울진군"}, {"value": "47940", "label": "울릉군"},
    ]},
    {"value": "48", "label": "경상남도", "keywords": "gyeongnam 경남", "children": [
        {"value": "48121", "label": "창원시"}, {"value": "48170", "label": "진주시"},
        {"value": "48220", "label": "통영시"}, {"value": "48240", "label": "사천시"},
        {"value": "48250", "label": "김해시"}, {"value": "48270", "label": "밀양시"},
        {"value": "48310", "label": "거제시"}, {"value": "48330", "label": "양산시"},
        {"value": "48720", "label": "의령군"}, {"value": "48730", "label": "함안군"},
        {"value": "48740", "label": "창녕군"}, {"value": "48820", "label": "고성군"},
        {"value": "48840", "label": "남해군"}, {"value": "48850", "label": "하동군"},
        {"value": "48860", "label": "산청군"}, {"value": "48870", "label": "함양군"},
        {"value": "48880", "label": "거창군"}, {"value": "48890", "label": "합천군"},
    ]},
    {"value": "50", "label": "제주특별자치도", "keywords": "jeju 제주", "children": [
        {"value": "50110", "label": "제주시"}, {"value": "50130", "label": "서귀포시"},
    ]},
    {"value": "99", "label": "해외·원격", "keywords": "remote overseas 재택", "children": [
        {"value": "99001", "label": "전국 원격"}, {"value": "99002", "label": "해외"},
    ]},
]


def _index(nodes: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n in nodes:
        got = [n["value"], *[c["value"] for c in n.get("children") or []]]
        out[n["value"]] = got
        for c in n.get("children") or []:
            out[c["value"]] = [c["value"]]
    return out


def _parents(nodes: list[dict]) -> dict[str, str]:
    return {c["value"]: n["value"] for n in nodes for c in n.get("children") or []}


REGION_INDEX = _index(REGIONS)
REGION_PARENT = _parents(REGIONS)


def _names(nodes: list[dict]) -> dict[str, str]:
    """value → a short readable name: "서울 강남구" rather than "서울특별시 강남구"."""
    short = {"특별시": "", "광역시": "", "특별자치시": "", "특별자치도": "", "도": ""}
    out: dict[str, str] = {}
    for n in nodes:
        head = n["label"]
        for suffix in short:
            if head.endswith(suffix) and len(head) > len(suffix):
                head = head[: -len(suffix)]
                break
        out[n["value"]] = n["label"]
        for c in n.get("children") or []:
            out[c["value"]] = f"{head} {c['label']}"
    return out


REGION_NAME = _names(REGIONS)
