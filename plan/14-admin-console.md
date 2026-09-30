# 14 · 관리자 콘솔 (`/admin`)

관리자(`role=admin`)만. 라우트 그룹 `app/(admin)/admin/**`. 서버 컴포넌트 가드 + API `require_admin`.

## 화면

| 라우트 | 화면 | 내용 |
|---|---|---|
| `/admin` | 개요 | 시스템 헬스(DB·워커 하트비트·볼륨 사용량·Claude 자격 상태), 오늘 턴/크레딧/에러, 최근 가입, 프로바이더 상태 카드 |
| `/admin/setup` | 초기 설정 위저드 | ①Claude Code 로그인/키 ②다른 프로바이더 키 ③임베딩·STT·TTS ④모델 카탈로그 확인 ⑤플랜 ⑥가입 정책·도메인 확인 |
| `/admin/providers` | 프로바이더 | 카드별: Anthropic API 키, **Claude Code**(상태·구독 티어·만료·[디바이스 로그인]·[JSON 붙여넣기]·[프로브 실행]), OpenAI, Gemini, ElevenLabs, Voyage. 키는 입력 후 마스킹(끝 4자), [검증] 버튼(라이브 프로브: models 목록 GET), 마지막 검증 시각 |
| `/admin/models` | 모델 카탈로그 | 표: 프로바이더·모델·표시명·컨텍스트·단가(입력/출력/캐시)·thinking·vision·활성·기본·정렬. [프로바이더에서 가져오기](라이브 모델 목록 → 추가 후보), 프리셋 시드(Anthropic/OpenAI/Gemini 최신 공개 가격 기반 크레딧 단가 자동 계산 = usd × credits_per_usd × 마진) |
| `/admin/audio` | 음성 | STT 프로바이더/모델(openai `gpt-4o-mini-transcribe`/`whisper-1`, google, elevenlabs), TTS 프로바이더/모델/기본 음성, 음성 카탈로그(테스트 재생), 단가 |
| `/admin/embedding` | 임베딩 | 프로바이더/모델/차원, 변경 시 재임베딩 잡 트리거·진행률 |
| `/admin/plans` | 플랜 | free/pro/custom 편집(월 크레딧·한도들), 기본 플랜, `credits.usd_per_credit`, 신규 가입 지급량, 저잔액 경고선 |
| `/admin/users` | 사용자 | 표(이메일·이름·역할·플랜·잔액·비서 수·최근 로그인·상태), 상세: 크레딧 부여/차감(사유 필수), 플랜 변경, 정지/해제, 역할 승격/강등(마지막 admin 보호), 비밀번호 재설정 메일, 비서 메타 목록(대화 본문은 미노출), 삭제 |
| `/admin/usage` | 사용량 | 일별 크레딧/턴/방문자 턴/프로바이더별 토큰 그래프, 상위 사용자, 모델별 분포, 비용(usd) 대 크레딧 |
| `/admin/invites` | 초대 | 초대 코드 생성·만료·사용량 |
| `/admin/settings` | 시스템 | 서비스명·로고·공개 URL, 가입 정책·이메일 인증, SMTP(테스트 발송), Google OAuth 클라이언트(로그인/연동 공용, 리다이렉트 URI 표시), Turnstile 키, 방문자 기본 정책(레이트·보존), 메모리 증류 모델·on/off, 로그 레벨 |
| `/admin/jobs` | 워커 | 큐 상태(대기/실행/실패/데드), 재시도·폐기, 핸들러별 처리량, 워커 하트비트 |
| `/admin/audit` | 감사 로그 | 필터·검색 |
| `/admin/health` | 진단 | `/health/ready` 상세, 프로바이더 프로브 일괄 실행, Claude CLI 버전, 디스크, 최근 에러 턴 목록(오너 미노출 스택 포함) |

## Claude Code 로그인 중계 (핵심 관리자 기능)
백엔드 `services/providers/claude_code.py`:
- `status()`: 볼륨 `.credentials.json` 파싱(만료·티어·스코프), `claude --version`, 마지막 프로브 결과.
- `start_login()` → 잡 `claude_login`(백엔드 프로세스 내, pty 로 `claude auth login` 실행; `HOME=/root`). stdout 을 SSE `/api/admin/providers/claude-code/login/events` 로 중계(URL·코드 입력 프롬프트 감지). `POST …/login/input {text}` 로 stdin 전달. 완료 시 자격 파일 생성 확인 → 상태 갱신. (Geny `ClaudeCodeAuthModal` + Codex 로그인 동형화 이식.)
- `import_credentials(json)`: 스키마 검증(`claudeAiOauth.accessToken/refreshToken/expiresAt`) → DB 암호화 저장 + 볼륨 물질화(`0600`).
- `probe()`: 파이프라인으로 1턴("ping" → 1단어) 실행, TTFT·버전·에러 기록. 크레딧 미차감(system).
- 자격 갱신은 CLI 가 파일에 직접 함. 워커 잡 `claude_creds.backup` 이 매시간 파일 → DB 로 백업(볼륨 유실 대비).

## API (`/api/admin/*`, 전부 require_admin)
```
GET  /api/admin/overview
GET/PUT /api/admin/settings            (키별 마스킹; 시크릿은 PUT 만, GET 은 has_value)
GET  /api/admin/providers · PUT /api/admin/providers/{id} · POST /api/admin/providers/{id}/verify
POST /api/admin/providers/claude-code/login/start · GET …/login/events (SSE) · POST …/login/input · POST …/import · POST …/probe
GET  /api/admin/providers/claude-code/accounts · PUT …/claude-code/pool
POST/PATCH/DELETE /api/admin/providers/claude-code/accounts[/{id}] · POST …/{id}/import · /probe · /cooldown/clear
POST …/accounts/{id}/login/start · GET …/login · GET …/login/events (SSE) · POST …/login/input · /login/cancel
GET/POST/PATCH/DELETE /api/admin/models · POST /api/admin/models/discover?provider= · POST /api/admin/models/seed
GET/POST/PATCH /api/admin/plans
GET /api/admin/users?q=&page= · GET/PATCH /api/admin/users/{id} · POST …/credits {delta, note} · POST …/role · POST …/suspend · DELETE
GET /api/admin/usage?from=&to=&group=
GET/POST/DELETE /api/admin/invites
GET /api/admin/jobs?status= · POST /api/admin/jobs/{id}/retry · /discard
GET /api/admin/audit?…
GET /api/admin/health
POST /api/admin/embedding/reindex
POST /api/admin/smtp/test
```

## 부트스트랩 UX
최초 로그인 → `/admin/setup` 강제(완료 플래그 `system_settings.setup_completed`). 위저드는 건너뛰기 가능하되 "Claude Code 미설정" 배너가 개요에 남는다.
