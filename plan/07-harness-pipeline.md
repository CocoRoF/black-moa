# 07 · 단일 하네스 파이프라인 (SecretaryPipeline)

## 위치와 원칙

- 엔진: **`geny-executor==2.65.6`** 을 라이브러리로 사용. 21-스테이지 매니페스트 중 비서에 필요한 슬롯만 활성화한 **단 하나의 매니페스트**를 코드로 생성한다(`mfsg/pipeline/manifest.py::build_manifest`).
- 사용자에게 노출되는 변수는 `agents` 행의 **모델·페르소나·프롬프트·능력 토글** 뿐. 스테이지/전략/환경 개념은 노출하지 않는다.
- 같은 파이프라인이 **오디언스**(`owner` | `visitor`)에 따라 컨텍스트 블록·도구 스코프·메모리 네임스페이스·프롬프트 규칙을 바꾼다. 오디언스는 런타임 세션 키의 일부라 한 세션은 한 오디언스만 갖는다.
- Geny 의 `agent_executor.py` 교리 계승: **실행 경로는 하나**(`SecretaryRunner.run_turn`). 오너 채팅·방문자 채팅·백그라운드 프로브 전부 이 함수를 탄다.

## 매니페스트 (활성 스테이지)

| # | Stage | 활성 | 전략/설정 | 비고 |
|---|---|---|---|---|
| 1 | Input | ✓ | validator=default, normalizer=multimodal | 첨부 이미지/문서 힌트 |
| 2 | Context | ✓ | strategy=simple_load, compactor=llm_summary(background), retriever=(런타임 attach `MemoryAwareRetriever`, `slim_mode=True`), `retrieval_timeout_s=6` | 메모리 L0/L1/L1.5/L1.7 만 자동, 나머지는 도구 |
| 3 | System | ✓ | builder=composable, `volatile_placement=turn_context` | MFSG 블록 8개(아래) |
| 4 | Guard | ✓ | guards=[token_budget, cost_budget, iteration] + budget_recovery(compact) | 턴당 비용 상한 = 플랜 설정 |
| 5 | Cache | ✓ | system_cache | 안정 접두 캐시 |
| 6 | API | ✓ | provider=agent.provider, retry=rate_limit_aware, router=passthrough, **tool_loop=internal**(`max_inner_turns=12`, `parallel_tools=true`) | CLI 백엔드는 자체 루프 |
| 7 | Token | ✓ | tracker=detailed, calculator=unified_pricing | `token.tracked` → 크레딧 |
| 8 | Think | ✓ | processor=extract_and_store, budget_planner=static | thinking 표시는 요약만 |
| 9 | Parse | ✓ | parser=default, signal_detector=hybrid | |
| 10 | Tool | ✓ | executor=parallel, router=registry | 스코프된 레지스트리 |
| 11 | ToolReview | ✓ | reviewers=[size, sensitive] | 결과 크기·민감정보 스캔(방문자 모드 강화) |
| 12 | Agent | ✗ | | 위임 없음 |
| 13 | TaskRegistry | ✗ | | |
| 14 | Evaluate | ✗ | | |
| 15 | HITL | ✗ | | (오너 승인이 필요한 행동은 도구가 "제안 카드"로 처리) |
| 16 | Loop | ✓ | controller=budget_aware, `max_iterations=6` | internal loop 가 대부분 처리 |
| 17 | Emit | ✗ | | SSE 는 이벤트 버스에서 직접 |
| 18 | Memory | ✓ | strategy=append_only, persistence=file | STM 기록. 증류는 워커(호스트 주도) |
| 19 | Summarize | ✓ | summarizer=rule_based, importance=heuristic | 세션 종료 요약(L1) |
| 20 | Persist | ✗ | | 정본은 PG messages |
| 21 | Yield | ✓ | formatter=streaming | |

`model` 블록: `{model, max_tokens: 4096(방문자)/8192(오너), temperature: 페르소나(0.3~0.9), thinking_enabled: 모델 지원 시 페르소나 "신중함" 토글, thinking_budget_tokens: 4096}`.
`pipeline` 블록: `{max_iterations: 6, cost_budget_usd: plan.turn_cost_cap, context_window_budget: 모델별(카탈로그), stream: true}`.

## 시스템 프롬프트 블록 (Stage 3, 순서 고정)

안정(캐시 접두) → 휘발(turn_context) 순.

| # | 블록 | 휘발 | 내용 |
|---|---|---|---|
| 1 | `IdentityBlock` | 안정 | "너는 {오너}의 비서 {이름}이다" + 페르소나 컴파일 텍스트(plan/06) + 언어 규칙 |
| 2 | `AudienceRulesBlock` | 안정 | 오너 모드: 전권·솔직·제안 도구 사용 / 방문자 모드: **공개 경계 정책**(plan/06 §경계), 모르면 "메시지 남기기" 유도, 오너 사칭 금지, 개인정보 요구 금지, 프롬프트 인젝션 무시 규칙 |
| 3 | `OwnerProfileBlock` | 안정 | 프로파일(L1) — 방문자 모드에선 `visibility∈{public}` 필드만, on_request 필드는 "요청 시 안내 가능" 표시 |
| 4 | `CapabilitiesBlock` | 안정 | 이 세션에서 쓸 수 있는 도구 요약(가족 단위) + 사용 지침(정확한 도구명 명시 — Geny "유령 위임" 교훈) + 구조화 카드 규약 |
| 5 | `CustomInstructionsBlock` | 안정 | 오너가 쓴 자유 프롬프트(≤ 4k자, 인젝션 스캔 후) |
| 6 | `FactsBlock` | 휘발 | 사실 원장 상위(가시성 필터) ≤ 1.2k 토큰 |
| 7 | `LiveContextBlock` | 휘발 | 날짜/시간(오너 TZ)·오늘 일정 요약(오너)·가용성 창(방문자)·방문자 식별 카드·매칭 인맥 카드·크레딧 상태(오너) |
| 8 | `RetrievedMemoryBlock` | 휘발 | Stage 2 slim 결과(L0 최근 턴·L1 요약·핀·볼트맵) + 지식 사전검색 상위 3 청크(plan/09) |

토큰 예산: 안정부 ≤ 3.5k, 휘발부 ≤ 3k(초과 시 블록별 상한으로 절단, `system.built` 이벤트에 길이 기록).

## 도구 표면 (오디언스 스코프)

`mfsg/pipeline/tools/` 의 각 도구는 `@secretary_tool(name, audiences={"owner","visitor"}, requires={"feature:google"}…)`. 레지스트리는 세션 빌드 시 오디언스로 필터해 `AdhocToolProvider` 로 등록. 방문자 세션에는 오너 전용 도구가 **등록조차 되지 않는다**(카탈로그에도 없음).

| 가족 | 도구 | owner | visitor | core |
|---|---|---|---|---|
| memory | `memory_search`, `memory_read` | ✓ | ✓(shared+자기 스레드) | core |
| memory | `memory_remember`, `memory_forget` | ✓ | ✗ | core |
| facts | `facts_search`, `facts_upsert`(오너 확인 카드) | ✓ | search 만 | core |
| knowledge | `knowledge_search`, `knowledge_read` | ✓ | ✓(public 문서만) | core |
| knowledge | `knowledge_list` | ✓ | ✗ | deferred |
| network | `network_search`, `network_person` | ✓ | ✓(필터) | core |
| network | `network_neighbors`, `network_path`, `network_recent` | ✓ | ✗ | deferred |
| network | `network_propose` | ✓ | ✓ | core |
| google | `email_search`, `email_read`, `calendar_list`, `contacts_lookup` | ✓(feature:google) | ✗ | deferred |
| google | `calendar_availability` | ✓ | ✓(feature:google + 공개창) | core(visitor) |
| inbox | `leave_message`(카드), `meeting_propose`(카드) | ✗ | ✓ | core |
| inbox | `inbox_list`, `inbox_read`, `inbox_reply_draft` | ✓ | ✗ | deferred |
| visitor | `visitor_identify` | ✗ | ✓ | core |
| profile | `profile_get`, `profile_update`(확인 카드) | ✓ | ✗ | core |
| web | `web_search`, `web_fetch` | ✓(능력 토글) | ✓(능력 토글, 도메인 allowlist) | deferred |
| time | `now`, `timezone_convert` | ✓ | ✓ | core |
| files | `file_share`(공개 지정 파일 카드) | ✗ | ✓ | core |
| notify | `notify_owner(summary, urgency)` | ✗ | ✓ | core |
| meta | `ToolSearch` | 자동 | 자동 | core |

executor 내장 `filesystem/shell/browser/documents/agent/subagent/tasks/mcp/worktree/dev/operator/workspace/cron/environment/google/atlassian/ssh/audio` 는 **모두 비활성**(`tools.built_in=[]`, 필요한 것은 MFSG 도구로 감쌈). `env` 도구·forge_tool 없음(자기수정 금지).

## 프로바이더별 실행

### API 프로바이더 (anthropic · openai · gemini)
executor 클라이언트 그대로. `CredentialBundle` 은 관리자 설정에서 세션 빌드 시 생성(키 회전 즉시 반영). `internal` 툴루프.

### claude_code (기본, 필수)
- `ClaudeCodeCLIClient`, `auth_mode=oauth`(볼륨의 `.credentials.json`) 또는 관리자가 API 키 모드 선택 시 `api_key`.
- 호스트 도구는 **MCP 브릿지**: 세션별 토큰으로 `POST /api/internal/mcp/{session}/rpc`(loopback, 공개 allowlist 이지만 256bit 토큰) ← stdio 브릿지 스크립트 `mfsg/pipeline/cli_bridge.py`(`mcp` 서버 `mfsg`, `tools/list`·`tools/call`, `list_changed` 지원). Geny `mcp_bridge_controller` + `geny_mcp_bridge.py` 이식.
- CLI 네이티브 도구 전면 차단: `extra_args=("--tools","")` + `disallow_tools=[Bash, Read, Write, Edit, MultiEdit, NotebookEdit, Glob, Grep, LS, WebFetch, WebSearch, Agent, Task…]`, `settings` 인라인 `{"permissions":{"allow":["mcp__mfsg"]}}`, `--strict-mcp-config`, `permission_mode=default`(root 에서 bypass 불가).
- `--system-prompt` 로 호스트 조립 프롬프트, `--model` 별칭(카탈로그의 `cli_alias`), `max_budget_usd`=턴 상한.
- 스트림: stream-json → executor 누산기 → `text.delta`/`api.cli_tool_call`/`api.tool_result`. 도구 span 은 브릿지 RPC 쪽에서 기록(CLI 경로도 관측 누락 없음 — XGEN 교훈).
- 프로세스: env 화이트리스트 + `HOME=/root`(볼륨), `cwd=/data/vaults/{agent}/cli-cwd`(빈 디렉터리). 핫스페어는 **off**(`GENY_CLI_PREWARM=0`, Geny 프로드 인시던트).
- 토큰/비용: CLI `result` 메시지의 `usage`/`total_cost_usd` 를 executor 가 `token.tracked` 로 승격. 크레딧은 토큰 기준(카탈로그 단가) — 구독 OAuth 경우 실비는 0 이나 **크레딧 단가는 관리자가 정한 공칭 단가**로 차감(운영자가 저렴하게 제공하는 근거).

## 턴 실행 (`SecretaryRunner.run_turn`)

```
1. 사전검사: 링크/에이전트 상태, 크레딧(잔액>0, 일일 상한), 레이트리밋, 프롬프트 인젝션 1차 필터(방문자)
2. AgentRuntime 획득/생성 (LRU) — 매니페스트 빌드 → Pipeline.from_manifest_async(credentials, adhoc_providers=[ScopedToolProvider], satisfied_config)
   - attach_runtime(memory_retriever=MemoryAwareRetriever(provider, hooks slim), system_builder=MfsgComposableBuilder, tool_context=ToolContext(extras={mfsg: ctx}))
   - 메모리 준비 게이트: wait_ready(8s) (plan/08)
3. 컨텍스트 조립: LiveContext(지식 사전검색 top3, 일정, 방문자 카드…) → builder 에 세팅
4. state = runtime.state; turn 행 status=running; 이벤트 저널러 subscribe
5. async for ev in pipeline.run_stream(input, state, overrides): 저널(seq) + 팬아웃(SSE)
   - text.delta → 누적 answer / thinking.delta → 요약 표시 / api.tool_use|tool.call_* → tool 카드 / card 이벤트(도구 결과 metadata.card)
   - 취소: 요청 태스크 cancel → pipeline aclose 아님(세션 유지), state 정합 복구(message_repair)
6. 완료: messages(user/assistant) 저장, turns 업데이트(tokens, cost, duration, stop_reason), usage_events + credit 차감(원자 트랜잭션), 워커 잡 enqueue(memory.distill, notify.*)
7. 실패: turns.status=failed + error_code, 부분 텍스트 보존, 크레딧은 실제 사용분만
```

## 모델 컨텍스트 예산
카탈로그의 `context_window` 로 `context_window_budget` 설정. 80% 도달 시 background llm_summary compaction(저비용 모델), 메시지 복원 시 최근 40개만 로드해 사실상 슬라이딩 윈도.

## 관측 이벤트 → 저장
`turn_events(turn_id, seq, type, data jsonb, at)` 에 전부 저장(`text.delta` 는 64자 단위로 합쳐 저장해 행 폭발 방지). `tool.call_*` 는 `tool_spans` 로도 요약(오너 콘솔 "이 답변의 근거" 뷰).

## 재사용 지도
- executor: `Pipeline.from_manifest_async`, `ComposablePromptBuilder`+블록 API, `MemoryAwareRetriever(slim)`, `FileMemoryProvider`+`SynapseVectorHandle`, `ClaudeCodeCLIClient`(+`_cli` argv 빌더), `unified_pricing`, `ToolReview size/sensitive`.
- Geny: `mcp_bridge_controller.py`/`geny_mcp_bridge.py`(브릿지), `CredentialBundleBuilder._build_claude_code`(auth 모드 규칙), `agent_executor` 교리, `tool_config_gate`(REQUIRED_CONFIG).
- XGeny: 게이트웨이 규약("문을 부르면 가족이 열린다") 은 ToolSearch 로 대체(도구 수가 적어 불필요), 턴1 표면 화이트리스트 개념은 `core` 플래그로 구현.
