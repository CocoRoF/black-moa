# 25 · 결정 원장

형식: `D-번호 · 날짜 · 결정 · 대안 · 근거 · 영향`. 권장안을 채택하고 진행한다.

| # | 날짜 | 결정 | 대안(기각) | 근거 |
|---|---|---|---|---|
| D-01 | 2026-09-06 | 엔진은 `geny-executor==2.65.6` 를 **라이브러리**로 사용, 단일 매니페스트를 코드로 생성 | ①포크/벤더링 ②xgen-agent-runtime 사용 ③처음부터 작성 | ①유지비 ②회사 사유 저장소를 개인 공개 제품 의존성으로 쓸 수 없음 ③claude_code CLI·MCP·메모리·가격표를 재작성할 이유 없음. 필요한 XGEN 아이디어(논리턴 L0·입력 클램프·검증 게이트 개념)는 호스트 계층에서 재구현 |
| D-02 | 2026-09-06 | DB 는 **PostgreSQL + pgvector + pg_trgm + citext** 단일 | Qdrant 별도 서비스 | 서비스 수 최소화, 한 트랜잭션에서 청크/노드/이메일 벡터 관리, 백업 단일화 |
| D-03 | 2026-09-06 | 워커 큐는 **PG 테이블(SKIP LOCKED)** | Redis+arq/celery | 컴포넌트 1개 줄임, 처리량 요구 낮음(수천 잡/일) |
| D-04 | 2026-09-06 | 스트리밍은 **SSE(fetch 스트림) + 저널 재개** | WebSocket | 모바일 백그라운드/재접속 단순, nginx/CF 친화, 서버는 단방향이면 충분(취소는 POST) |
| D-05 | 2026-09-06 | 메모리 볼트 검색은 **Synapse 로컬 해시 임베딩(0-API)**, 지식/인맥/메일은 **API 임베딩+pgvector** | 볼트도 API 임베딩 | 검색 경로 락 안에서 네트워크 금지(어댑터 설계), 노트는 소량·BM25 지배적, 테넌트당 메모리 ~0 |
| D-06 | 2026-09-06 | 오디언스(owner/visitor)를 **런타임 세션 키·볼트 네임스페이스·도구 레지스트리·프롬프트**의 1차 축으로 | 프롬프트만으로 경계 | 프롬프트만으론 인젝션에 취약, 서버 측 스코프가 필수 |
| D-07 | 2026-09-06 | claude_code 네이티브 도구 **전면 차단**, 호스트 도구는 **loopback MCP 브릿지**로 단일 표면 | 네이티브 fs 허용 | 비서에 파일/셸 불필요, 두 표면 공존 시 모델이 반쪽 도구를 집음(XGEN 교훈) |
| D-08 | 2026-09-06 | 툴루프 `internal`(max_inner_turns 12) + Loop max_iterations 6 | `pipeline` 툴루프 | 라운드트립당 스테이지 오버헤드 불필요, HITL/Eval 미사용 |
| D-09 | 2026-09-06 | 크레딧 = 토큰 × 카탈로그 단가, 원장 append-only, 턴 멱등 차감 | USD 직접 청구 | 관리자가 마진·구독 원가를 반영해 단가 결정 가능, 통화 무관 |
| D-10 | 2026-09-06 | 결제는 **관리자 수동 + Stripe 어댑터(키 있을 때만)** | 정식 결제 v1 | 범위 통제, 부트스트랩 단계 |
| D-11 | 2026-09-06 | 최초 가입자 = admin, 이후 승격 가능, 최소 1명 유지 | env 로 admin 지정 | 제품 요구, 재배포 없이 위임 |
| D-12 | 2026-09-06 | 토큰: access 15분(메모리) + refresh 30일(httpOnly 쿠키, 회전) | 30일 JWT 쿠키(Geny) | B2C 보안 기준 |
| D-13 | 2026-09-06 | 공개 경로는 **루트 `/{code}`**, 예약어 목록으로 충돌 방지 | `/c/{code}` | 제품 요구("도메인/{코드}"), Next 정적 라우트 우선 규칙으로 안전 |
| D-14 | 2026-09-06 | 프론트 Next.js 15 + Tailwind v4 + zustand + react-query, shadcn 스타일 자체 구현 | Next 16(Geny) | 15 가 안정, 16 은 이 시점 로컬 빌드 환경 이슈(oxide) 경험. **구현 중 재검토 가능** |
| D-15 | 2026-09-06 | 인맥 시각화는 `@cocorof/graphier` | d3-force | 오너 소유 라이브러리, 기능 충족 |
| D-16 | 2026-09-06 | 텍스트 추출은 경량 라이브러리(pypdf/python-docx/…) | contextifier | 의존 무게, 위치 메타는 v2 |
| D-17 | 2026-09-06 | 메모리 증류는 **워커에서 턴 후 비동기**(facts→note→proposals), 저비용 모델 | 세션 유휴 틱 | 턴 지연 0, 세션 상주 가정 불필요(XGEN distill 패턴) |
| D-18 | 2026-09-06 | Claude Code 핫스페어 **off** | on | Geny 프로드 인시던트(스페어 사망 → 턴 스톨) |
| D-19 | 2026-09-06 | STT 기본 openai `gpt-4o-mini-transcribe`, TTS 기본 openai `gpt-4o-mini-tts`, 임베딩 `text-embedding-3-small` | ElevenLabs 기본 | 키 1개로 3기능, 관리자 변경 가능 |
| D-20 | 2026-09-06 | 이메일 본문은 저장하지 않고 요약·메타만 캐시 | 본문 저장 | 개인정보 최소화, 실시간 fetch 로 충분 |
| D-21 | 2026-09-06 | 그래프 자동 반영 없음 — 비서 추론은 `proposals` 로 오너 승인 | 자동 반영 | 그래프 오염 방지 |
| D-22 | 2026-09-06 | 단일 백엔드 프로세스(uvicorn 1 워커) + LRU 런타임 세션 | 멀티워커 | SSE 팬아웃·런타임 캐시 프로세스 로컬. 수평 확장은 v2 |
| D-23 | 2026-09-06 | 호스트 포트 58700, 127.0.0.1 바인딩, 터널 <터널> 인그레스 추가 | 새 터널 | 기존 인프라 재사용 |
| D-24 | 2026-09-06 | 저장소명 `CocoRoF/my-first-secretary-geny`, 로컬 `mfsg`, Apache-2.0 | | 제품 요구 |

## 구현 중 추가 (계속 갱신)
| # | 날짜 | 결정 | 근거 |
|---|---|---|---|
| D-25 | 2026-09-07 | **메모리는 호스트 측**(마크다운 노트 + 네임스페이스별 Synapse)에서 직접 다루고 executor 의 Stage 2 retriever/18 Memory/19 Summarize 는 비활성 | executor 파일 프로바이더는 세션당 단일 `transcripts/session.jsonl` 을 가정해 대화 다중화가 안 되고, 히스토리 정본은 이미 PG 라 STM 이 불필요. 검색·핀·볼트맵은 `RetrievedMemoryBlock` 에서 호스트가 조립 |
| D-26 | 2026-09-07 | SSE 터미널 이벤트(`usage`/`turn.complete`/`error`/`cancelled`)는 **정산 트랜잭션 커밋 후** 방출 | 클라이언트가 완료 직후 잔액/메시지를 읽으면 옛 값이 보이던 레이스(테스트에서 실측) |
| D-27 | 2026-09-07 | 지식 검색 3레그: pgvector ∪ tsvector('simple') ∪ **ILIKE/트라이그램**(RRF) | 한국어 조사("재택근무를")가 simple 토크나이저와 해시 임베딩을 모두 무력화 → 부분일치 레그 없이는 재현율 0 |
| D-28 | 2026-09-07 | Claude Code 네이티브 도구 차단은 `--tools ""` + `--disallowedTools` 병행, MCP 도구는 `--tools ""` 에서도 노출됨을 실측 | mini MCP 서버로 검증(pong 호출 성공). 브릿지 `tools/list` 는 `registry.list_exposed()` 가 **Tool 객체**를 돌려준다는 점 주의(이름 아님) |
| D-29 | 2026-09-07 | 프론트 패키지 매니저 **npm**(package-lock), Node 22 | 로컬 pnpm/corepack 이 Node 22 에서 깨짐. Docker 도 `npm ci` |
| D-30 | 2026-09-07 | 가드 체인은 매니페스트 `chain_order` 가 아니라 **런타임 `add_to_chain`** 으로 채움; 리뷰어는 `remove_from_chain` 으로 축소 | executor: 기본 guards 체인이 비어 있고 chain_order 는 재정렬만 가능 |
| D-31 | 2026-09-07 | **(정정)** 운영 Claude 자격은 서버에서 **디바이스 로그인(관리자 콘솔 중계)** 으로 자체 계보를 만든다. 다른 CLI 의 `credentials.json` 복사는 금지 | 실측: 로컬 사본을 임포트한 뒤 로컬 CLI 가 16:37Z 에 토큰을 갱신하자 컨테이너의 refresh 가 즉시 실패("OAuth session expired and could not be refreshed"). refresh token 은 **회전**된다. Geny 프로드가 로컬과 공존했던 이유는 컨테이너 안에서 별도 `claude auth login` 을 했기 때문(별도 계보). JSON 임포트는 "다른 곳에서 더 이상 쓰지 않는 자격"에만 유효 |
| D-33 | 2026-09-07 | 방문자 스트리밍은 **유지**하되 delta 를 실시간 마스킹(`guard.StreamRedactor`, hold-back 윈도)한다. PR#1 의 "방문자에게 delta 를 아예 보내지 않는다" 는 채택하지 않음 | 공개 채팅은 모바일 실시간 대화가 제품의 핵심(plan/12)이라 10~30초 무응답 후 완성문 일괄 표시는 받아들일 수 없는 후퇴다. 누출 창은 스트리밍 포기가 아니라 hold-back 으로 닫을 수 있고(불변식은 plan/19), 최종 `turn.complete.answer` 가 여전히 권위본이라 이중 방어가 된다 |
| D-32 | 2026-09-07 | Cloudflare 앞단에서는 Python `urllib` 기본 UA 가 403 으로 차단됨 → 운영 스모크/스크립트는 브라우저형 UA 사용 | 실측(관리자 API 호출이 curl 로는 200, urllib 로는 403) |
| D-34 | 2026-09-07 | 관리자는 **시드된 기본 계정**(`admin@geny.com` / `admin123`, `MFSG_DEFAULT_ADMIN_*` 로 변경·`..._ENABLED=0` 로 비활성)으로 제공하고, 로그인/가입은 관리자를 `/admin` 으로 튕기지 않는다(모두 같은 `/app` 홈) | 사용자 지시. 시드는 멱등이고 기존 계정을 절대 덮어쓰지 않는다(비밀번호를 바꾸면 그대로 유지). 기본 비밀번호가 살아 있는 동안 관리자 콘솔은 헤더 알약 + 개요 배너로 계속 경고하고, `GET /api/admin/overview.default_admin_password_in_use` 가 그 근거다. **공개 배포에서 기본 비밀번호를 그대로 두면 인스턴스 탈취와 같다** — 첫 로그인 후 마이페이지에서 바꾸는 것이 운영 절차 |
| D-35 | 2026-09-08 | Claude Code 디바이스 로그인 릴레이는 **pty 가 아니라 파이프**로 돌리고, 플로우는 `--claudeai`/`--console` 로 명시 지정한다. 출력은 줄 단위가 아니라 **청크 + 300ms 유휴 플러시** | 프로드 이미지에서 실측: 둘 다 코드 제출은 되지만 pty 는 URL 을 OSC-8 로 감싸고 두 번 출력해 콘솔이 이스케이프로 오염된다. `Paste code here …>` 프롬프트에는 개행이 없어 readline 이 잡아두고, 첫 promptish 청크에서 바로 흘리면 단어 중간에서 잘린다(`Paste code here if prompte` + `d >`). UI 는 실행 중 내내 입력창을 열어 둔다 — 예전에는 `input` 이벤트(=이미 보낸 코드의 에코)로만 입력창을 띄워서 로그인 완료가 구조적으로 불가능했다 |
