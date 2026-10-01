"""Job families and industries, as a Korean job seeker would look for them.

Codes are ours, not a public standard: KSCO exists but is written for statistics, not for
picking a job, and its top level puts a backend engineer and a network technician in the
same bucket. The shape is two levels — a family everyone recognises, then the titles that
actually appear in postings.
"""

from __future__ import annotations

JOB_FAMILIES: list[dict] = [
    {"value": "dev", "label": "개발", "keywords": "engineering developer", "children": [
        {"value": "dev.backend", "label": "백엔드", "keywords": "backend server api"},
        {"value": "dev.frontend", "label": "프론트엔드", "keywords": "frontend web react"},
        {"value": "dev.fullstack", "label": "풀스택", "keywords": "fullstack"},
        {"value": "dev.mobile", "label": "모바일(iOS·Android)", "keywords": "mobile ios android"},
        {"value": "dev.devops", "label": "DevOps·인프라", "keywords": "devops sre infra cloud"},
        {"value": "dev.security", "label": "보안", "keywords": "security"},
        {"value": "dev.embedded", "label": "임베디드·펌웨어", "keywords": "embedded firmware"},
        {"value": "dev.game", "label": "게임 개발", "keywords": "game unity unreal"},
        {"value": "dev.qa", "label": "QA·테스트", "keywords": "qa test"},
        {"value": "dev.etc", "label": "기타 개발"},
    ]},
    {"value": "data", "label": "데이터·AI", "keywords": "data ai ml", "children": [
        {"value": "data.ml", "label": "머신러닝·AI 엔지니어", "keywords": "ml ai llm"},
        {"value": "data.scientist", "label": "데이터 사이언티스트", "keywords": "data scientist"},
        {"value": "data.engineer", "label": "데이터 엔지니어", "keywords": "data engineer etl"},
        {"value": "data.analyst", "label": "데이터 분석가", "keywords": "analyst bi sql"},
        {"value": "data.research", "label": "AI 리서치", "keywords": "research"},
    ]},
    {"value": "plan", "label": "기획·PM", "keywords": "product manager planning", "children": [
        {"value": "plan.pm", "label": "프로덕트 매니저", "keywords": "pm product"},
        {"value": "plan.po", "label": "서비스 기획", "keywords": "po service"},
        {"value": "plan.pmo", "label": "PM·PMO(프로젝트)", "keywords": "pmo project"},
        {"value": "plan.biz", "label": "사업기획·전략", "keywords": "strategy bd"},
        {"value": "plan.data", "label": "데이터 기획"},
    ]},
    {"value": "design", "label": "디자인", "keywords": "design", "children": [
        {"value": "design.uiux", "label": "UI·UX 디자인", "keywords": "ui ux product design"},
        {"value": "design.bx", "label": "BX·브랜드 디자인", "keywords": "brand bx"},
        {"value": "design.graphic", "label": "그래픽·편집", "keywords": "graphic"},
        {"value": "design.3d", "label": "3D·모션", "keywords": "3d motion"},
        {"value": "design.product", "label": "제품·산업 디자인"},
    ]},
    {"value": "mkt", "label": "마케팅·광고", "keywords": "marketing", "children": [
        {"value": "mkt.perf", "label": "퍼포먼스 마케팅", "keywords": "performance ads"},
        {"value": "mkt.brand", "label": "브랜드 마케팅"},
        {"value": "mkt.content", "label": "콘텐츠·SNS", "keywords": "content sns"},
        {"value": "mkt.crm", "label": "CRM·그로스", "keywords": "crm growth"},
        {"value": "mkt.pr", "label": "홍보·PR", "keywords": "pr"},
        {"value": "mkt.md", "label": "MD·상품기획", "keywords": "md"},
    ]},
    {"value": "sales", "label": "영업·고객", "keywords": "sales cs", "children": [
        {"value": "sales.b2b", "label": "B2B 영업"},
        {"value": "sales.b2c", "label": "B2C·리테일 영업"},
        {"value": "sales.solution", "label": "솔루션·기술영업", "keywords": "pre-sales se"},
        {"value": "sales.cs", "label": "고객지원(CS)", "keywords": "cs support"},
        {"value": "sales.csm", "label": "고객성공(CSM)", "keywords": "customer success"},
    ]},
    {"value": "hr", "label": "HR·총무", "keywords": "hr people", "children": [
        {"value": "hr.recruit", "label": "채용", "keywords": "recruiting ta"},
        {"value": "hr.hrm", "label": "인사·노무", "keywords": "hrm"},
        {"value": "hr.hrd", "label": "교육·조직문화", "keywords": "hrd"},
        {"value": "hr.ga", "label": "총무·경영지원", "keywords": "ga"},
    ]},
    {"value": "fin", "label": "재무·회계", "keywords": "finance accounting", "children": [
        {"value": "fin.acct", "label": "회계·결산"},
        {"value": "fin.tax", "label": "세무"},
        {"value": "fin.fp", "label": "재무기획(FP&A)", "keywords": "fpa"},
        {"value": "fin.ir", "label": "IR·투자", "keywords": "ir vc"},
        {"value": "fin.audit", "label": "내부감사"},
    ]},
    {"value": "legal", "label": "법무·컴플라이언스", "keywords": "legal", "children": [
        {"value": "legal.corp", "label": "기업법무"},
        {"value": "legal.ip", "label": "특허·IP"},
        {"value": "legal.compliance", "label": "컴플라이언스·개인정보", "keywords": "privacy dpo"},
    ]},
    {"value": "mfg", "label": "생산·제조", "keywords": "manufacturing", "children": [
        {"value": "mfg.process", "label": "생산·공정관리"},
        {"value": "mfg.quality", "label": "품질관리(QA·QC)"},
        {"value": "mfg.equipment", "label": "설비·유지보수"},
        {"value": "mfg.safety", "label": "안전·환경(EHS)", "keywords": "ehs"},
    ]},
    {"value": "eng", "label": "엔지니어링·설계", "keywords": "engineering", "children": [
        {"value": "eng.mech", "label": "기계 설계"},
        {"value": "eng.elec", "label": "전기·전자 설계"},
        {"value": "eng.semi", "label": "반도체 공정·소자", "keywords": "semiconductor"},
        {"value": "eng.chem", "label": "화학·소재"},
        {"value": "eng.civil", "label": "건축·토목", "keywords": "civil"},
    ]},
    {"value": "logi", "label": "물류·유통", "keywords": "logistics supply", "children": [
        {"value": "logi.scm", "label": "SCM·구매", "keywords": "scm purchasing"},
        {"value": "logi.ops", "label": "물류 운영"},
        {"value": "logi.trade", "label": "무역·수출입"},
    ]},
    {"value": "med", "label": "의료·바이오", "keywords": "medical bio", "children": [
        {"value": "med.clinical", "label": "임상·CRA", "keywords": "clinical cra"},
        {"value": "med.ra", "label": "인허가(RA)", "keywords": "ra regulatory"},
        {"value": "med.research", "label": "연구(R&D)"},
        {"value": "med.care", "label": "의료진·간호"},
    ]},
    {"value": "edu", "label": "교육", "keywords": "education", "children": [
        {"value": "edu.teacher", "label": "강사·교사"},
        {"value": "edu.content", "label": "교육 콘텐츠 기획"},
        {"value": "edu.operation", "label": "교육 운영"},
    ]},
    {"value": "media", "label": "미디어·콘텐츠", "keywords": "media content", "children": [
        {"value": "media.editor", "label": "에디터·작가"},
        {"value": "media.video", "label": "영상 제작·편집"},
        {"value": "media.pd", "label": "PD·연출"},
        {"value": "media.translate", "label": "번역·통역"},
    ]},
    {"value": "etc", "label": "기타", "children": [
        {"value": "etc.service", "label": "서비스·매장"},
        {"value": "etc.public", "label": "공공·비영리"},
        {"value": "etc.freelance", "label": "프리랜서·기타"},
    ]},
]

INDUSTRIES: list[dict] = [
    {"value": "it", "label": "IT·서비스", "keywords": "it software", "children": [
        {"value": "it.saas", "label": "SaaS·솔루션"},
        {"value": "it.platform", "label": "플랫폼·포털"},
        {"value": "it.si", "label": "SI·SM"},
        {"value": "it.game", "label": "게임"},
        {"value": "it.ai", "label": "AI·데이터"},
        {"value": "it.security", "label": "보안"},
        {"value": "it.telecom", "label": "통신"},
    ]},
    {"value": "fin", "label": "금융", "keywords": "finance bank", "children": [
        {"value": "fin.bank", "label": "은행"},
        {"value": "fin.securities", "label": "증권·자산운용"},
        {"value": "fin.insurance", "label": "보험"},
        {"value": "fin.fintech", "label": "핀테크"},
        {"value": "fin.vc", "label": "VC·PE"},
    ]},
    {"value": "mfg", "label": "제조·화학", "keywords": "manufacturing", "children": [
        {"value": "mfg.semi", "label": "반도체·디스플레이"},
        {"value": "mfg.elec", "label": "전자·전기"},
        {"value": "mfg.auto", "label": "자동차·모빌리티"},
        {"value": "mfg.chem", "label": "화학·소재"},
        {"value": "mfg.machine", "label": "기계·장비"},
        {"value": "mfg.battery", "label": "이차전지·에너지"},
    ]},
    {"value": "bio", "label": "의료·제약·바이오", "keywords": "bio pharma", "children": [
        {"value": "bio.pharma", "label": "제약"},
        {"value": "bio.device", "label": "의료기기"},
        {"value": "bio.hospital", "label": "병원·헬스케어"},
        {"value": "bio.research", "label": "바이오 연구"},
    ]},
    {"value": "retail", "label": "유통·소비재", "keywords": "retail commerce", "children": [
        {"value": "retail.ecommerce", "label": "이커머스"},
        {"value": "retail.offline", "label": "리테일·유통"},
        {"value": "retail.food", "label": "식음료·외식"},
        {"value": "retail.fashion", "label": "패션·뷰티"},
        {"value": "retail.living", "label": "생활·리빙"},
    ]},
    {"value": "logi", "label": "물류·운송", "keywords": "logistics", "children": [
        {"value": "logi.delivery", "label": "택배·배송"},
        {"value": "logi.forward", "label": "포워딩·무역"},
        {"value": "logi.transport", "label": "운송·항공·해운"},
    ]},
    {"value": "const", "label": "건설·부동산", "keywords": "construction", "children": [
        {"value": "const.build", "label": "건설·시공"},
        {"value": "const.estate", "label": "부동산·프롭테크"},
        {"value": "const.plant", "label": "플랜트·엔지니어링"},
    ]},
    {"value": "media", "label": "미디어·광고", "keywords": "media ad", "children": [
        {"value": "media.ad", "label": "광고·마케팅 대행"},
        {"value": "media.content", "label": "콘텐츠·엔터테인먼트"},
        {"value": "media.press", "label": "언론·출판"},
    ]},
    {"value": "edu", "label": "교육", "children": [
        {"value": "edu.edtech", "label": "에듀테크"},
        {"value": "edu.school", "label": "학교·학원"},
    ]},
    {"value": "pro", "label": "전문서비스", "keywords": "consulting", "children": [
        {"value": "pro.consulting", "label": "컨설팅"},
        {"value": "pro.law", "label": "법률·회계"},
        {"value": "pro.hr", "label": "HR·헤드헌팅"},
    ]},
    {"value": "public", "label": "공공·기관", "children": [
        {"value": "public.gov", "label": "공공기관·정부"},
        {"value": "public.npo", "label": "비영리·협회"},
        {"value": "public.research", "label": "연구기관"},
    ]},
    {"value": "etc", "label": "기타", "children": [
        {"value": "etc.energy", "label": "에너지·환경"},
        {"value": "etc.agri", "label": "농림수산"},
        {"value": "etc.travel", "label": "여행·레저"},
        {"value": "etc.other", "label": "그 외"},
    ]},
]

EMPLOYMENT_TYPES = ["fulltime", "contract", "intern", "parttime", "freelance", "dispatch"]


def _index(nodes: list[dict]) -> dict[str, list[str]]:
    """value → the values it covers, itself included. Used to expand a parent pick."""
    out: dict[str, list[str]] = {}

    def walk(n: dict) -> list[str]:
        got = [n["value"]]
        for c in n.get("children") or []:
            got.extend(walk(c))
        out[n["value"]] = got
        return got

    for n in nodes:
        walk(n)
    return out


def _parents(nodes: list[dict]) -> dict[str, str]:
    """child value → its parent's value. Used to roll a count up the tree."""
    out: dict[str, str] = {}

    def walk(n: dict, parent: str) -> None:
        if parent:
            out[n["value"]] = parent
        for c in n.get("children") or []:
            walk(c, n["value"])

    for n in nodes:
        walk(n, "")
    return out


JOB_INDEX = _index(JOB_FAMILIES)
INDUSTRY_INDEX = _index(INDUSTRIES)
JOB_PARENT = _parents(JOB_FAMILIES)
INDUSTRY_PARENT = _parents(INDUSTRIES)


def _labels(nodes: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(n: dict) -> None:
        out[n["value"]] = n["label"]
        for c in n.get("children") or []:
            walk(c)

    for n in nodes:
        walk(n)
    return out


JOB_NAME = _labels(JOB_FAMILIES)
INDUSTRY_NAME = _labels(INDUSTRIES)
