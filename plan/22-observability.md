# 22 · 관측 · 로그 · 헬스 · 자가치유

## 로그
- 구조화 JSON(`structlog`) stdout → docker 로그. 필드 `ts, level, logger, msg, request_id, user_id?, agent_id?, turn_id?, job_id?`.
- `redact` 프로세서: 키 이름(`api_key, token, password, secret, authorization, refresh`) 값 마스킹, 이메일 부분 마스킹.
- 레벨: 운영 INFO, 관리자 설정으로 DEBUG 토글(재시작 없이).
- 요청 로그: 메서드·경로(파라미터 제거)·상태·ms·바이트. SSE 는 시작/종료 2줄.

## 턴 관측 (제품 기능이기도 함)
- `turns` 행: 토큰·비용·크레딧·ttft·duration·stop_reason·error_code·tool_call_count.
- `turn_events` 저널: 전체 이벤트(재개용 + 디버깅). 30일 후 `text.delta` 는 삭제(요약 유지).
- `tool_spans`: 도구 호출 요약 → 오너 콘솔 "근거" 뷰, 관리자 에러 턴 조사.
- 프로바이더 에러 분류 코드 → `turns.error_code`, 관리자 대시보드 상위 에러.

## 메트릭
Prometheus 형식 `GET /metrics`(관리자 토큰 또는 내부망만): `mfsg_turns_total{audience,provider,status}`, `mfsg_turn_duration_seconds`, `mfsg_ttft_seconds`, `mfsg_credits_charged_total`, `mfsg_jobs{kind,status}`, `mfsg_sse_subscribers`, `mfsg_runtime_sessions`, `mfsg_vault_open`, `mfsg_provider_errors_total{provider,code}`. v1 은 노출만(스크레이퍼 없음), 관리자 개요가 DB 집계로 같은 숫자를 보여줌.

## 헬스
- `/health`: 프로세스 살아있음 + 이벤트루프 지연(100ms 이상이면 `degraded`) — DB 무관(autoheal 오탐 방지).
- `/health/ready`: DB ping, `/data` 쓰기, 워커 하트비트 ≤ 90s, Claude 자격 상태.
- 루프 워치독(Geny `loop_watchdog` 이식): 루프 블록 2s 초과 시 스택 덤프 로그 + 카운터. `SIGUSR1` 스레드 덤프.
- autoheal: backend/worker `healthcheck` 실패 3회 → 재시작. `cap_add: SYS_PTRACE`(py-spy 진단).

## 워커 관측
`worker_heartbeats` 30s, 잡별 처리 시간·실패 사유, 관리자 `/admin/jobs`.

## 알림(운영자)
관리자 이메일로: 워커 하트비트 2분 소실, Claude 자격 만료 24h 전, 디스크 85%, 프로바이더 에러율 10분간 30% 초과(워커 잡 `ops.watch` 5분 주기).

## 프론트
브라우저 콘솔 에러는 `POST /api/telemetry/client-error`(샘플링 10%, 사용자 동의 불필요한 최소 정보) → 관리자 헬스 화면.

## 대시보드 화면
관리자 `/admin/usage`, `/admin/health`. 오너 `/app/agents/[id]/stats`.
