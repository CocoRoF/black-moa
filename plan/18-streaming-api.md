# 18 · API 계약 · 스트리밍 프로토콜

## 공통
- Base `/api`. JSON UTF-8. 에러 `{"error":{"code":"…","message":"…","detail":{}}}` + HTTP 상태. 코드는 `snake_case` 안정 문자열(예 `credits_exhausted`, `link_paused`, `rate_limited`, `not_found`, `validation_error`).
- 인증: `Authorization: Bearer <access>`(사용자) / `Bearer <visitor_token>`(공개 API). refresh 는 쿠키.
- 페이지네이션: 커서 `?after=<id>&limit=` (기본 50, 최대 200) → `{items, next_cursor}`.
- 시간: ISO-8601 UTC.
- 레이트리밋 헤더 `X-RateLimit-Remaining`, 429 시 `Retry-After`.
- OpenAPI `/docs`(admin 만).

## 턴 실행 (오너·방문자 공통 형태)

### 시작
```
POST /api/agents/{agent_id}/conversations/{cid}/turns           (오너)
POST /api/public/conversations/{cid}/turns                       (방문자)
Body: {"text": "...", "attachments": [{"upload_id": "..."}], "client_turn_id": "uuid(멱등)"}
Accept: text/event-stream
→ 200 SSE  (헤더 X-Turn-Id: <turn_id>)
```
`client_turn_id` 중복이면 기존 턴 스트림에 재접속(멱등).

### SSE 봉투
```
id: <seq>
event: <type>
data: {"seq": 12, "type": "text.delta", "at": "...", "data": {...}}

: ping   (15초 간격 코멘트, CF 100s 방어)
```
`id` = seq 이므로 브라우저 `EventSource` 의 `Last-Event-ID` 와도 호환(단, 클라이언트는 fetch 스트림 사용).

### 이벤트 타입 (프론트 계약, executor 이벤트를 정규화)
| type | data | 비고 |
|---|---|---|
| `turn.start` | `{turn_id, conversation_id, model, provider}` | 첫 이벤트 |
| `text.delta` | `{text}` | 답변 토큰. 저널에는 64자 단위로 병합 저장 |
| `thinking.delta` | `{text}` | 오너 모드만 전달(방문자에겐 `thinking.status` 로 축약) |
| `thinking.status` | `{active: bool}` | |
| `tool.start` | `{call_id, name, label, input_preview}` | `label` 은 사람이 읽는 한 줄("일정을 확인하는 중") |
| `tool.end` | `{call_id, name, is_error, duration_ms, output_preview}` | |
| `card` | `{card_type, payload, message_id}` | 구조화 카드(plan/12) |
| `memory.retrieved` | `{count, chars}` | 오너 모드 표시용 |
| `guard.redacted` | `{count}` | 후처리 마스킹 발생 |
| `usage` | `{input_tokens, output_tokens, cache_read, credits, balance_after}` | 완료 직전, 오너 모드만 |
| `turn.complete` | `{turn_id, message_id, stop_reason, duration_ms, ttft_ms}` | 정상 종료 |
| `turn.error` | `{code, message, retryable}` | |
| `turn.cancelled` | `{}` | |
| `notice` | `{kind: memory_warming\|model_fallback\|input_clamped, message}` | 사용자 안내 |

### 재개
```
GET /api/agents/{agent_id}/turns/{turn_id}/events?after=<seq>      (오너)
GET /api/public/turns/{turn_id}/events?after=<seq>                 (방문자)
→ SSE: 저널의 seq>after 이벤트를 즉시 방출 후, 턴이 아직 진행 중이면 라이브 팬아웃에 합류, 종료됐으면 `turn.complete|error|cancelled` 후 종료
```
### 취소
`POST …/turns/{turn_id}/cancel` → 202. 러너가 태스크 cancel, 부분 텍스트 저장, `turn.cancelled`.

### 진행 상태 확인
`GET …/conversations/{cid}/active-turn` → `{turn_id, seq, started_at}|null` (재접속·탭 복귀 시 사용).

## 서버 구현
- `pipeline/events.py::TurnJournal`: 인메모리 링(턴당 최대 5,000 이벤트) + PG `turn_events` 비동기 배치 flush(200ms). 구독자 팬아웃은 `asyncio.Queue`(큐 상한 1,000, 느린 소비자는 끊고 재개 URL 로).
- SSE 응답은 `StreamingResponse` + `X-Accel-Buffering: no`, nginx `proxy_buffering off`.
- 순수 ASGI 미들웨어(스트리밍 통과), 요청 본문 상한 2 MB(첨부는 별도 업로드).

## 업로드
```
POST /api/uploads (multipart, kind=attachment|avatar|knowledge) → {upload_id, url, mime, size}
GET  /static/u/{owner_id}/{upload_id}  (오너 인증 or 서명 URL)
```
이미지는 서버에서 1568px 리사이즈(vision 토큰 절약).

## 채팅 히스토리
```
GET /api/agents/{id}/conversations?audience=&after=
POST /api/agents/{id}/conversations {title?}
GET /api/agents/{id}/conversations/{cid}/messages?before=&limit=
PATCH /api/agents/{id}/conversations/{cid} {title|status}
DELETE …
```

## 클라이언트 (`frontend/lib/sse.ts`)
```ts
streamTurn({url, body, token, onEvent, signal}) // fetch → ReadableStream → 라인 파서(id/event/data) → onEvent
resumeTurn({url, after, ...})
```
- 네트워크 오류 시 지수 백오프(0.5s→8s, 최대 6회) 로 `resumeTurn(after=lastSeq)`.
- `visibilitychange` 복귀 시 `active-turn` 조회 → 진행 중이면 resume.
- 취소는 AbortController + cancel API.

## 방문자 공개 API 요약 (plan/12) · 관리자(plan/14) · 도메인 API 는 각 문서 참조.

## 버전
헤더 `X-MFSG-API: 1`. 하위호환 깨는 변경은 `/api/v2`.
