# 27 · 레퍼런스 지도 — 무엇을 가져오고 무엇을 버리는가

조사 대상: `project_geny_workspace/{Geny, geny-executor, geny-memory-adaptor, geny-executor-web, project-geny-app}`, `company_xgen_workspace/{xgen-agent-runtime, xgen-workflow, xgen-workflow-sandbox}`(아이디어만, 코드 의존 없음).

## 라이브러리 의존(그대로 사용)
| 패키지 | 버전 | 쓰는 것 |
|---|---|---|
| `geny-executor` | ==2.65.6 | `Pipeline.from_manifest_async`, `EnvironmentManifest`, `ComposablePromptBuilder`+블록, `MemoryAwareRetriever`, `FileMemoryProvider`, `MemoryHooks`, `ClaudeCodeCLIClient`/`_cli` argv, `AnthropicClient/OpenAIClient/GoogleClient`, `CredentialBundle`, `ToolRegistry`/`Tool`/`ToolContext`/`AdhocToolProvider`, `unified_pricing`, `EventTypes`, `security` SSRF 가드, `FactLedger`/`FACT_EXTRACTION_SCHEMA`(증류 스키마 참고) |
| `geny-memory-adaptor` | ==1.11.1 | `SynapseMemory`, `SynapseConfig`, `search/search_join/learn/trust_feedback/contradictions/manifest/index_many/remove` |
| `@cocorof/graphier` | ^1.4.0 | 인맥 그래프 뷰 |

## Geny 백엔드에서 이식(코드 복사 후 개조)
| 원본 | MFSG 위치 | 개조 |
|---|---|---|
| `service/auth/auth_middleware.py`(순수 ASGI, allowlist) | `core/auth_middleware.py` | 역할·방문자 토큰·refresh 추가 |
| `service/config/credentials.py`(키 resolver + 라이브 프로브 캐시) | `providers/verify.py` | DB 설정 소스 |
| `service/executor/credentials.py::CredentialBundleBuilder._build_claude_code` | `providers/llm/credentials.py` | auth 모드 규칙 그대로, 네이티브 도구 차단 |
| `controller/mcp_bridge_controller.py` + `scripts/geny_mcp_bridge.py` | `api/internal_mcp.py` + `pipeline/cli_bridge.py` | 서버명 `mfsg`, list_changed 선행 방출(XGEN) |
| `service/memory/synapse_handle.py`, `usage_tracker.py`, `manager._vector_initialize_and_index` | `memory/synapse_handle.py`, `memory/learning.py`, `memory/reconcile.py` | 네임스페이스 계층 |
| `service/execution/agent_executor.py` 교리(단일 실행 경로·admission lock·cost persist) | `pipeline/runner.py` | 크레딧 정산 결합 |
| `ws/chat_stream.py` 의 "재접속 시 명시적 done" 교훈 | `pipeline/events.py` | SSE |
| `service/observability/loop_watchdog.py`, `main.py` BLAS 핀 | `core/watchdog.py`, `main.py` | |
| `service/knowledge/service.py` 청킹 상수·`KnowledgeUnavailable→409` | `services/knowledge/` | pgvector |
| `controller/llm_backends_controller.py` `ClaudeCodeAuthModal` 서버측(SSE 로그인 잡) | `services/providers/claude_code.py` | pty 중계 |
| `tests/test_blas_threading.py` | `tests/test_blas_threading.py` | |

## Geny 프론트에서 이식
| 원본 | MFSG |
|---|---|
| `components/chat/ChatMarkdown.tsx`(GFM·코드·인증 blob 이미지), `chat-utils.ts` | `components/chat/Markdown.tsx` |
| `components/messenger/MessageList.tsx`(virtuoso 패턴), `MessageInput.tsx`(첨부·드롭·붙여넣기) | `components/chat/MessageList.tsx`, `Composer.tsx` |
| `lib/i18n/index.ts` 엔진 | `lib/i18n.ts` |
| `lib/theme.tsx` + FOUC 스크립트 | `lib/theme.tsx` |
| `lib/audioManager.ts`(iOS WebAudio 전략), `ttsSentenceStream.ts` | `lib/audio.ts` |
| `lib/imageAttachments.ts`(클라이언트 다운스케일) | `lib/image.ts` |
| `components/ChunkReloadGuard.tsx` | 그대로 |
| `CommandTab` 의 visibilitychange 재구독 | `lib/sse.ts` |
| `persona_presets/PersonaPresetsManager`(슬라이더→프롬프트 아이디어) | `PersonaEditor` (단순화) |
| `builder/ModelPicker.tsx` | `ModelPicker`(카탈로그 기반) |
| `user-opsidian/KnowledgePanel.tsx`(업로드·상태 폴링·청크 뷰어) | `knowledge/` |
| `globals.css` 모바일 블록(16px 입력·hover:none·safe-bottom) | `app/globals.css` |

## XGEN 에서 아이디어만 이식(재구현)
| 아이디어 | MFSG 구현 |
|---|---|
| `tool_exposure.TURN_ONE_TOOLS` 화이트리스트(문=가족) | 도구 표 `core` 플래그 + `SKILL_GATEWAYS` 대신 ToolSearch |
| `memory/transcript.py` 논리 턴 L0 + 도구 한 줄 요약 | `state.messages` 를 PG 에서 논리 턴 단위로 복원(도구 결과는 한 줄 요약으로 치환) |
| `host/context_budget.fit_input_to_budget`(RAG 먼저 절단, reserved) | `pipeline/budget.py` |
| `core/compaction.reconcile_recorded_index` | executor 2.65.6 에 이미 포함 확인 |
| 검증 후 등록(forged tool) | 비서엔 forged tool 없음 — 대신 **알림 채널 테스트 발송 후 verified** 에 같은 원칙 |
| `classify_llm_error_message` 코드표 | `providers/errors.py` |
| 로그인 중계 동형화(Codex) | Claude Code 디바이스 로그인 중계 |
| CHANGELOG 규율(증상·원인·불변식) | `CHANGELOG.md` |
| `SandboxUnavailable` "대신 실행하지 않는다" | 방문자 세션에 오너 도구 폴백 없음, Claude 자격 없으면 턴 거부(다른 프로바이더로 몰래 폴백 안 함 — 관리자가 명시한 폴백만) |

## 버리는 것 (명시적 비목표)
Geny: VTuber/Live2D/Spine/MMD/3D 도시/2D 플레이그라운드, omnivoice/whisper 로컬, GAPT, 환경 매니페스트 편집 UI(43k LOC), 트리거/툴프리셋/샌드박스 팩/스킬 편집, 데스크톱 접속기·오버레이·VSCode 확장, 워크스페이스 동기화/WebDAV/Drive, 인바운드 게이트웨이(텔레그램 봇 채팅 — v2 검토), 다중 에이전트 룸/위임/서브에이전트, 크리처 상태, 보이스 스튜디오, 블로그 에이전트, Opsidian 큐레이터, 커스텀 도구 CRUD, MCP 커넥터 카탈로그(Notion/GitHub 등 — v2), 슬래시 커맨드, 크론 도구, 훅 자동화.
executor: filesystem/shell/browser/documents/agent/subagent/tasks/mcp 도구 패밀리, `env`/forge_tool, HITL/Evaluate/Emit/Persist 스테이지, 세션 퍼시스턴스, 크론, 게이트웨이, 슬래시 커맨드, 스킬 시스템(전부 미사용).

## 알려진 함정(재발 방지 목록)
1. Next standalone 에서 `NEXT_PUBLIC_API_URL` 빌드타임 인라인 → 런타임 same-origin 만 사용.
2. OpenBLAS 포크 웨지 → 스레드 1 핀 + 가드 테스트.
3. 동기 SQLite/파일 스캔을 루프에서 → `to_thread`.
4. 클로드 CLI stdout 파이프 EOF(자식 MCP) → executor 2.65.2+ 포함, `exit_drain_grace_s` 유지.
5. Claude 핫스페어 사망 스톨 → off.
6. asyncio StreamReader 64KiB 한계 → executor 가 32MiB 설정(2.59.1+) 확인.
7. STM 워터마크 vs 컴팩션 → executor 포함.
8. 구독 OAuth 모드에 API 키 전달 → 401 폭풍. 절대 금지.
9. `remove_many` 가 본문 params 를 남김 → `remove()` 루프.
10. AsyncSession gather 공유 금지 → 세션 스코프 명확히(요청당 1 세션, 워커 잡당 1 세션).
11. Cloudflare 100s 응답 제한 → SSE ping 15s.
12. sudo + heredoc 조합 금지(서버 배포 스크립트) — ssh 원격 실행에 파이썬 heredoc 을 넣으면 따옴표가 깨진다. **스크립트를 scp 로 올린 뒤 실행**할 것(2026-09-07 터널 인그레스 추가 때 실제로 헛돌았음).
13. `ToolRegistry.list_exposed()` 는 이름이 아니라 Tool 객체 목록 — MCP `tools/list` 에서 이름으로 다시 조회하면 빈 배열이 된다(실측).
14. `pkill -f "<패턴>"` 은 자기 자신의 bash 명령줄에도 매치돼 세션이 죽는다 — 포트 기준(`fuser -k`)으로 종료.
