# 02 · 시스템 아키텍처

## 토폴로지

```
                         ┌──────────────────────── Cloudflare (TLS, WAF) ───────────────────────┐
                         │                    https://mfsg.hrletsgo.me                           │
                         └───────────────────────────────┬───────────────────────────────────────┘
                                                         │ cloudflared 터널 <터널> → 127.0.0.1:58700
┌────────────────────────────────────────────────────────▼───────────────────────────────────────┐
│ docker compose -p mfsg                                                                          │
│                                                                                                 │
│  ┌──────────┐   /api,/health,/static   ┌──────────────────────────────────────────────────┐    │
│  │  nginx   │ ───────────────────────▶ │ backend (FastAPI, uvicorn 1 worker, asyncio)      │    │
│  │  :80     │   /*                     │  ├ api/        라우터                              │    │
│  └────┬─────┘                          │  ├ pipeline/   MFSG 하네스 (geny-executor 위)     │    │
│       │                                │  ├ memory/     볼트·Synapse·사실원장              │    │
│       ▼                                │  ├ providers/  llm·stt·tts·embedding 어댑터       │    │
│  ┌──────────┐                          │  └ claude CLI (npm, $MFSG_CLAUDE_HOME 볼륨)  ─ MCP 브릿지(stdio→loopback RPC)  │
│  │ frontend │                          └───────┬───────────────────────────┬──────────────┘    │
│  │ Next.js  │                                  │ asyncpg                   │ /data 볼륨          │
│  │ :3000    │                          ┌───────▼────────┐          ┌───────▼────────┐          │
│  └──────────┘                          │ postgres 16    │          │ mfsg-data      │          │
│                                        │ + pgvector     │          │ vaults/uploads │          │
│  ┌──────────┐   PG 잡 큐(SKIP LOCKED)  │ + pg_trgm      │          │ exports/og     │          │
│  │ worker   │ ◀────────────────────────┤                │          └────────────────┘          │
│  │ (same    │  색인·알림·연동동기화·   └────────────────┘                                        │
│  │  image)  │  증류·다이제스트·정산                                                             │
│  └──────────┘                                                                                   │
│  ┌──────────┐                                                                                   │
│  │ autoheal │                                                                                   │
│  └──────────┘                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
        │ 외부 API (전부 HTTPS, 로컬 서빙 없음)
        ▼
  Anthropic(API·Claude Code OAuth) · OpenAI(LLM·STT·TTS·임베딩) · Google(Gemini·OAuth·Gmail·Calendar·People)
  · ElevenLabs(TTS) · SMTP/Resend(메일) · Telegram/Slack/Discord(웹훅)
```

## 컴포넌트 책임

| 컴포넌트 | 책임 | 하지 않는 것 |
|---|---|---|
| **nginx** | 단일 진입, 업로드 상한, SSE 버퍼링 off, 정적 캐시 | TLS(Cloudflare 담당) |
| **frontend** | 오너 콘솔·관리자 콘솔·공개 채팅 UI. RSC 로 공개 페이지 메타 생성 | 비즈니스 로직·비밀 보관 |
| **backend** | 인증·도메인 API·파이프라인 실행·SSE 스트리밍·크레딧 즉시 차감 | 장시간 배치(워커로) |
| **worker** | 지식 색인, 이메일/일정 동기화, 알림 발송, 메모리 증류, 일간 다이제스트, 보존 스윕, 백업 | 사용자 요청 처리 |
| **postgres** | 모든 구조화 데이터 + 벡터(지식·인맥·메일 요약) + 잡 큐 | 볼트 노트(파일) |
| **mfsg-data 볼륨** | `/data/vaults/{agent}/…`(노트+synapse.db), `/data/uploads/{owner}/…`, `/data/exports` | |
| **mfsg-claude 볼륨** | `$MFSG_CLAUDE_HOME/.credentials.json`(OAuth) | |

## 요청 흐름 3종

### A. 오너 채팅 턴
```
POST /api/agents/{id}/conversations/{cid}/turns  (Bearer user JWT)
 → 소유권·크레딧 잔액 사전검사(잔액 ≤ 0 → 402)
 → turns 행 생성(status=running) → SecretaryRunner.run_turn(agent, conversation, audience=owner, text, attachments)
 → 파이프라인 이벤트 → 이벤트 저널(PG turn_events, seq) + 인메모리 팬아웃 → SSE 응답
 → pipeline.complete: 토큰·비용 → usage_events + credit_ledger(차감) → turns 완료
 → 워커 잡 enqueue: memory.distill(turn_id)
```

### B. 방문자 채팅 턴
동일하되 `audience=visitor`, 방문자 JWT, 링크 상태·레이트리밋 검사, 오너 크레딧 차감, 도구 스코프 축소, 완료 후 `notify.visitor_turn` 잡(오너 알림 규칙 평가).

### C. 백그라운드
워커가 `jobs` 테이블을 `FOR UPDATE SKIP LOCKED` 로 폴링(1s), 핸들러 실행, 재시도(지수 백오프, 최대 5), 데드레터.

## 파이프라인 위치
`backend/src/mfsg/pipeline/` 가 geny-executor 를 **라이브러리로** 사용한다. 매니페스트는 코드에서 생성(`build_manifest(agent, audience)`), 사용자에게 매니페스트 개념은 노출되지 않는다. 상세 `plan/07`.

## 세션 모델
- **에이전트 런타임 세션**(`AgentRuntime`)은 `(agent_id, audience, conversation_id)` 키로 프로세스 내 LRU 캐시(최대 300, 유휴 15분 evict). 파이프라인 객체 + `PipelineState`(메시지 히스토리) + 메모리 프로바이더 보유.
- 히스토리의 정본은 PG `messages`. 런타임 evict 후 복원 시 최근 N 메시지(≤ 40) 를 `state.messages` 로 재구성.
- 단일 백엔드 프로세스 가정(수평 확장은 v2: 세션 친화 라우팅 또는 상태 외부화).

## 스트리밍
SSE(`text/event-stream`), `fetch` + ReadableStream 로 소비. 이벤트 저널(`turn_events`) 에 seq 순으로 저장해 `?after=seq` 재개. 상세 `plan/18`.

## 실패 격리 원칙
- 메모리·지식·연동 조회 실패는 **턴을 죽이지 않는다**(타임아웃 후 빈 컨텍스트로 진행 + 관측 이벤트).
- 이벤트루프 블로킹 금지(동기 SQLite/파일/CPU 는 `to_thread`).
- 워커 잡 실패는 재시도·데드레터, API 경로에 영향 없음.
- 헬스: `/health`(liveness, DB 무관) · `/health/ready`(DB·볼륨·워커 하트비트).

## 확장 포인트
- 프로바이더 레지스트리(LLM/STT/TTS/임베딩) — 어댑터 파일 추가.
- 연동 레지스트리 — `IntegrationProvider` 구현 추가.
- 알림 채널 레지스트리 — `NotificationChannel` 구현 추가.
- 도구 — `mfsg.pipeline.tools` 에 `@secretary_tool(audiences=…)` 데코레이터.
