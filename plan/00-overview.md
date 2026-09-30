# 00 · MFSG 마스터플랜 개요

> **MFSG = my-first-secretary-geny**
> "당신의 진짜 비서를 만들어보세요."

이 문서 묶음(`plan/00` ~ `plan/27`)은 Geny 프로젝트를 B2C SaaS 로 개조한 **MFSG** 서비스의
설계 정본이다. 구현은 이 문서들을 근거로 진행하고, 결정이 바뀌면 `plan/25-decision-log.md` 에
기록한 뒤 해당 문서를 수정한다. 문서가 코드와 어긋나면 **코드가 아니라 문서가 틀린 것**으로
간주하고 문서를 고친다 (구현 중 발견된 사실은 즉시 반영).

## 한 문장 정의

사용자가 **자기 정보·지식·인맥·연동 계정**을 주입해 **자기만의 비서 에이전트**를 만들고,
`https://mfsg.hrletsgo.me/{코드}` 같은 **공개 채팅 경로**로 외부 사람들이 그 비서와
대화하게 하는 **크레딧 기반 SaaS**.

## 문서 지도

| # | 문서 | 내용 |
|---|---|---|
| 00 | overview | 이 문서. 지도·원칙·범위 |
| 01 | product-vision | 제품 비전, 페르소나(사용자/방문자/관리자), 핵심 시나리오, 비목표 |
| 02 | architecture | 시스템 아키텍처, 서비스 토폴로지, 데이터 흐름 |
| 03 | repo-layout | 모노레포 구조, 코딩 규약, 버전·릴리스 규칙 |
| 04 | data-model | PostgreSQL 스키마 전체 (테이블·컬럼·인덱스·관계) |
| 05 | accounts-auth | 계정 체계 개편: 최초 생성자=관리자, 가입자=사용자, 세션/JWT/OAuth |
| 06 | agents-persona | 비서 에이전트 모델, 페르소나 프리셋, 공개 경계 정책, 모델 선택 |
| 07 | harness-pipeline | 단일 하네스 파이프라인 (geny-executor 위 MFSG 매니페스트) 상세 |
| 08 | memory | 메모리 체계 (geny-memory-adaptor + Fact Ledger + 방문자 메모리 격리) |
| 09 | knowledge | 사용자 정보 파일/노트/FAQ 주입·색인·검색 (pgvector) |
| 10 | network-graph | 사용자 인맥 네트워크 그래프 (노드·엣지·소스·시각화·에이전트 도구) |
| 11 | integrations | 구글 계정 연동(Gmail/Calendar/Contacts) + 범용 연동 프레임워크 |
| 12 | public-chat-mobile | 공개 채팅 경로 `/{code}` 와 모바일 특화 채팅 UI |
| 13 | owner-console | 사용자(오너) 콘솔 UI: 에이전트 편집·지식·인맥·연동·인박스·크레딧 |
| 14 | admin-console | 관리자 콘솔: 인프라·프로바이더·모델 카탈로그·플랜·사용자·모니터링 |
| 15 | credits-billing | 크레딧 원장, 요금표, 플랜, 충전, 소진 정책, 결제 어댑터 |
| 16 | notifications | 비서 대화 알림: 이메일·웹훅·텔레그램·슬랙·디스코드, 다이제스트 |
| 17 | providers | LLM(claude_code 필수)·STT·TTS·임베딩 프로바이더 — 전부 API, 로컬 서빙 없음 |
| 18 | streaming-api | HTTP/SSE API 계약, 이벤트 봉투, 커서 리플레이, 취소 |
| 19 | security-privacy | 보안·개인정보: 공개 경계, 프롬프트 인젝션, 레이트리밋, 비밀 저장 |
| 20 | deployment | Docker Compose 배포, nginx, Cloudflare 터널 `mfsg.hrletsgo.me`, 운영 서버 절차 |
| 21 | testing-qa | 테스트 전략(단위·계약·E2E·모바일), 게이트 |
| 22 | observability | 로그·스팬·사용량 대시보드·헬스·자가치유 |
| 23 | roadmap | 마일스톤 M0~M8, 산출물, 완료 기준 |
| 24 | glossary | 용어집 |
| 25 | decision-log | 결정 원장 (권장안 채택 근거) |
| 26 | ops-runbook | 운영 런북: 장애·백업·키 교체·마이그레이션 |
| 27 | reference-map | Geny / geny-executor / geny-memory-adaptor / XGeny 에서 무엇을 가져오고 무엇을 버리는지 |

## 지도 원칙 (전 문서 공통)

1. **단일 파이프라인.** Geny 의 환경(environment)/프레임워크/트리거/툴프리셋 다층 구조는 버린다.
   에이전트는 오직 하나의 하네스 파이프라인(`plan/07`)을 탄다. 사용자가 고를 수 있는 것은
   모델·페르소나·프롬프트·능력 토글뿐이다.
2. **로컬 서빙 없음.** LLM·STT·TTS·임베딩 전부 외부 API 프로바이더. GPU 컨테이너 없음.
   LLM 프로바이더는 `claude_code`(필수·기본), `anthropic`, `openai`, `gemini` 로 제한(`plan/17`).
3. **오너/방문자 이중 오디언스.** 같은 비서가 **오너 모드**(주인과 대화, 전권)와
   **방문자 모드**(공개 링크, 공개 경계 정책 적용)로 동작한다. 모든 문맥·도구·메모리는
   오디언스로 스코프된다(`plan/06`, `plan/08`, `plan/19`).
4. **계정 단위 SaaS.** 크레딧은 계정 원장에 쌓이고, 오너의 비서가 방문자와 나눈 대화도
   오너의 크레딧을 쓴다(`plan/15`).
5. **모바일 우선.** 공개 채팅 UI 는 모바일이 1급 시민(`plan/12`). 데스크톱은 그 확장.
6. **관리자 1인.** 최초 가입자가 관리자. 인프라·프로바이더·키·요금표는 관리자만(`plan/05`, `plan/14`).
7. **권장안 채택.** 결정은 미루지 않고 권장안을 택해 진행하며 `plan/25` 에 남긴다.
8. **문서=코드 정본.** 위 첫 단락 참조.

## 범위 요약

**포함**: 계정/권한, 에이전트 CRUD·페르소나, 하네스 파이프라인, 메모리, 지식 주입(RAG),
인맥 그래프, 구글 연동(+범용 연동 뼈대), 공개 채팅(모바일), 오너 콘솔, 관리자 콘솔,
크레딧/플랜, 알림(이메일·웹훅·텔레그램·슬랙·디스코드), STT/TTS(API), 배포(compose, 터널),
테스트, 운영.

**제외(비목표)**: VTuber/아바타/Live2D/3D 도시, 로컬 TTS/STT 서버, GAPT 샌드박스,
다중 환경/트리거 프리셋 시스템, 데스크톱 접속기, VSCode 확장, 워크스페이스 동기화,
코드 실행 샌드박스(비서에겐 필요 없음 → v2 검토).

## 산출물

- `mfsg/` 모노레포 (backend · frontend · deploy · plan) → GitHub `CocoRoF/my-first-secretary-geny`
- `docker compose` 한 번으로 뜨는 스택
- `https://mfsg.hrletsgo.me` 운영 서빙(<서버>, Cloudflare 터널 `<터널>`)
