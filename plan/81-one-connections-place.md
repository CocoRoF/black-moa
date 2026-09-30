# plan/81 — 연결은 [인증 및 연결] 한 곳

## 0. 지시 (2026-09-30)

[관리·설정]에 [인증 및 연결]이 있는데 [연동]이 같은 연결 카드를 한 번 더 보였다. 하나로.

## 1. 한 것

- 메뉴에서 [연동] 제거. 연결 카드(`ConnectionCards`, 옛 `IntegrationsPage`)는 [인증 및 연결]의 "연결" 칸에만 놓인다.
  - 카드가 그 자체로 카드라 "연결" 칸은 한 겹 더 싸지 않고 제목·설명 + 카드들(`<section id="connections">`).
  - 설명은 plan/77 흐름대로: "바깥 서비스를 이으면 가져온 것이 [내 정보]에 모이고, 비서는 거기서 봐요."
  - `#connections` 이거나 연결을 마치고 돌아왔으면(`?connected=` · `?error=`) 그 칸으로 내려간다.
- 옛 주소 `/app/integrations` 는 질의를 그대로 들고 `/app/account?…#connections` 로 넘긴다(북마크·옛 알림).
- 다른 화면에서 오던 곳은 `/app/account#connections`: 홈 체크리스트(Google 연결하기), 인맥 출처 [연결에서 관리],
  클라우드 관리 Drive [연결하러 가기], 스케줄 동기화 [인증 및 연결로 가기].
- 서버: 연결 흐름이 돌아오는 기본 주소 `/app/account`(OAuth 콜백의 `next` 가 없거나 밖일 때).
  `#` 는 넣지 않는다 — 뒤에 `?connected=` 가 붙으면 조각 뒤로 들어가 버린다.
- 알림 `integration_error` 가 [비서 설정 열기](/app/agents)로 가던 것을 [연결 확인하기](/app/account#connections)로.
- 문구: "연동" → "연결"(연결 오류, 인맥 그래프의 나-출처 선 이름). 쓰지 않게 된 `nav.integrations`·`integ.desc` 삭제.
  스케줄의 [연동] 탭(달력 가져오기 설정)은 다른 것이라 그대로.

## 2. 검증

- `test_calendar_sources.py`(콜백 기본 주소), `test_units.py::test_a_connection_problem_opens_the_connections`.
