# 21 · 테스트 전략 · 품질 게이트

## 계층
| 계층 | 도구 | 범위 | 실행 |
|---|---|---|---|
| 단위 | pytest(asyncio auto) | 서비스·크레딧 계산·페르소나 컴파일·경계 필터·토크나이즈·코드 생성·레이트리밋·SSRF | 매 커밋(CI) |
| API 계약 | pytest + httpx `AsyncClient` + 테스트 PG(docker `pgvector`) | 라우터 전체: 인증·권한·소유권·404 은닉·스키마 | CI |
| 파이프라인 계약 | pytest + **FakeLLM 프로바이더**(executor `ClientRegistry.register("fake", …)`) + 도구 스텁 | 매니페스트 빌드, 프롬프트 블록 조립(스냅샷), 오디언스별 도구 표면, 이벤트 정규화, 취소, 크레딧 정산 | CI |
| CLI 브릿지 | fake `claude` 스크립트(stream-json 재생, executor `tests/_fixtures/fake_claude.py` 이식) | argv 계약(`--tools ""`, disallow, settings), MCP 브릿지 RPC 왕복, list_changed | CI |
| 워커 | pytest | 잡 큐 SKIP LOCKED·재시도·데드레터, 각 핸들러 | CI |
| 프론트 | vitest + testing-library | 스토어, SSE 파서, 마크다운 sanitize, 코드 검증, 컴포넌트 스모크 | CI |
| E2E | Playwright(크로미움 + **iPhone 14 에뮬레이션**) | 가입→비서→공개 링크→방문자 대화→인박스→알림 로그; 모바일 키보드/세이프에어리어 스냅샷 | 배포 전 로컬 compose |
| 라이브 스모크 | `scripts/smoke.sh` | 운영 서버: health, 로그인, Claude 프로브 턴, 방문자 1턴 | 배포 후 |
| 성능 | Lighthouse CI(모바일) | 공개 채팅 ≥ 90 | 배포 전 |

## 게이트 (CI `.github/workflows/ci.yml`)
1. backend: `ruff check` + `ruff format --check` + `mypy`(core/pipeline) + `pytest -x`(PG 서비스 컨테이너).
2. frontend: `pnpm lint` + `tsc --noEmit` + `vitest` + `next build`(standalone).
3. compose: `docker compose config` 검증 + backend/frontend 이미지 빌드(캐시).
4. 보안 체크리스트(plan/19) 자동 항목.

## 핵심 테스트 목록 (반드시 존재)
- `test_auth_bootstrap.py`: 최초 admin, 동시 가입 경합, 잠금, refresh 회전/재사용.
- `test_ownership_fuzz.py`: 모든 소유 엔드포인트에 타인 ID → 404.
- `test_audience_tool_surface.py`: 방문자 세션 도구 = 허용 집합과 정확히 일치, `owner/` 볼트 경로 접근 시 `PermissionError`.
- `test_disclosure_filter.py`: private 프로파일 필드·노드·문서가 방문자 도구 결과/응답에 없음(리터럴 마스킹 포함).
- `test_credits.py`: 계산표, 멱등 차감, 잔액 0 경계, 402/휴식 모드, 월 지급 이월.
- `test_turn_stream.py`: 이벤트 정규화 순서, 저널 seq, 재개 `after`, 취소 후 상태.
- `test_cli_argv.py`, `test_mcp_bridge.py`.
- `test_share_links.py`: 코드 생성 알파벳·예약어·핸들 검증·상태 전이.
- `test_network_graph.py`: 경로·이웃·병합·가시성.
- `test_knowledge_chunking.py`: 7,000B 캡, 헤딩 경로, FAQ 우선.
- `test_memory_namespaces.py`: 네임스페이스 검색 범위, 증류 결과 라우팅.
- `test_notifications.py`: 규칙 평가·방해금지·집계·웹훅 서명.
- `test_jobs.py`: 큐 동시성.
- `test_security.py`: SSRF, 업로드 MIME, redact, env 화이트리스트.
- `test_blas_threading.py`(Geny 이식): 포크 후 매트멀 회귀.
- frontend `sse.test.ts`, `markdown.test.tsx`, `codes.test.ts`, `stores/chat.test.ts`.

## 현재 구현된 테스트 (2026-09-07, 27건)
`tests/test_00_bootstrap.py`(최초 admin·권한 게이트) · `tests/test_e2e_core.py`(오너 턴+크레딧+메모리 도구, 공개 링크·방문자 흐름·도구 스코프·카드·인박스, 크로스 사용자 404, refresh 회전/재사용) · `tests/test_units.py`(크레딧 계산, 코드/핸들, 마스킹, 인젝션, 예산 클램프, 청킹, 페르소나, 매니페스트, 에러 분류) · `tests/test_domain.py`(지식 색인·검색·가시성, 그래프 연산·방문자 필터·제안·병합·CSV, 크레딧 멱등/사전검사, 알림 규칙/전달, 잡 큐, 프로파일 가시성, 관리자 설정 마스킹·카탈로그, misc 엔드포인트) · `tests/test_cli_contract.py`(Claude Code argv 3모드, JSON 추출). 가짜 LLM(`MFSG_FAKE_LLM=1`)으로 결정론적 실행. 실제 Claude Code 라이브 검증은 `scratch` 스크립트로 수동(문서화: CHANGELOG).

## 픽스처
- `tests/conftest.py`: 테스트 DB(트랜잭션 롤백), 관리자·사용자·방문자 팩토리, FakeLLM(고정 응답·도구 호출 시나리오), 임베딩 스텁(결정론적 해시 벡터), 시간 고정.
- 시드 스크립트 `scripts/seed_demo.py`: 데모 오너 "한지민"·비서 "지니"·지식 3건·인맥 12노드·링크 1개.

## 수동 QA 체크리스트(배포 전)
plan/20 체크리스트 + iOS Safari 실기기(키보드·PWA 설치·음성)·Android Chrome.
