# 19 · 보안 · 개인정보

## 보안 경계 원칙
MFSG의 방문자 경계는 **모델 프롬프트를 신뢰 경계로 사용하지 않는다**. 프롬프트 규칙은 행동 품질을 높이는 보조 수단이고, 실제 권한·공개·과금·네트워크·보존 경계는 서버와 DB가 강제한다.

방문자 응답 경로는 다음 순서를 따른다.

`raw provider stream → internal journal/buffer → disclosure/redaction → public event projection → SSE`

- 방문자에게도 `text.delta`는 계속 흐르지만(모바일 공개 채팅의 핵심 UX — plan/12), **raw 는 절대 나가지 않는다**. runner 가 모든 방문자 delta 를 `guard.StreamRedactor` 에 통과시킨 뒤에야 journal 에 emit 하므로 공개 스트림·`turn_events` 에 남는 것은 이미 마스킹된 텍스트다.
- `StreamRedactor` 불변식: 길이 L 인 매치는 절대 마스킹 없이 방출되지 않는다. 방출 상한은 `len(buf) - HOLD` 이고, 시작점 s < cut 이면 e ≤ s+L < len(buf) 이므로 그 매치는 이미 버퍼 안에서 완성돼 스캔에 걸리고 cut 이 s 로 당겨진다. 길이가 유계인 패턴(전화·주민·카드)과 literal 은 HOLD 로 덮고, 무계 패턴(이메일·API 키)은 공백을 포함하지 않으므로 cut 을 마지막 공백 경계로 스냅해 토큰을 쪼개지 않는다.
- 방문자는 fail-closed allowlist에 포함된 이벤트만 받는다. 새 내부 telemetry/event type은 명시적으로 허용하지 않는 한 자동 비공개다.
- 완료된 응답은 서버에서 disclosure/redaction을 끝내고 DB commit된 `Turn.answer_text`를 `turn.complete.answer`로 전달한다.
- 공개 스트림은 모델/provider, usage, redaction count, tool argument/result preview 같은 내부 메타데이터를 내보내지 않는다.
- `on_request` 프로필 값은 방문자 system prompt/context에 실제 값이 들어가지 않는다. 실제 값은 visitor-only `profile_disclose` tool이 현재 턴의 구체적 요청 사유를 확인한 뒤 release하고, final redactor는 **그 턴에서 tool이 허용한 literal만** 통과시킨다.

## 위협 모델
| 위협 | 대응 |
|---|---|
| 방문자가 비서를 통해 오너의 비공개 정보 추출(프롬프트 인젝션·사회공학) | 프롬프트 규칙 + 서버 도구 스코프 + audience별 memory namespace + server-gated `on_request` 공개 + fail-closed public event projection + 최종 response redaction. 오너 네임스페이스 볼트는 방문자 도구에 노출되지 않음 |
| 스트리밍 중 최종 마스킹 전 비밀 노출 | delta 를 방출 전에 `StreamRedactor` 로 통과(hold-back 윈도) + 완료 시 assembled answer 재검사 + commit 된 sanitized answer 를 `turn.complete.answer` 로 재전달(클라이언트가 최종본으로 대체) |
| 방문자 남용(비용 소진·스팸) | 링크/방문자 레이트리밋, DB credit reservation, 일일 visitor-turn 상한, Turnstile fail-closed, 방문자 차단, 링크 일시정지 |
| 동시 턴으로 credit/daily cap 초과 | `credit_reservations` hold → provider budget → settle/release. `CreditBalance`/`UsageDaily` row lock으로 동시 예약 직렬화. 실행기는 DB commit 이후에만 시작 |
| 중복 턴/idempotency race | conversation row lock + DB partial unique index: `(conversation_id, client_turn_id)`, conversation당 `running` turn 1개 |
| 계정 최초 관리자 선점 | HTTPS production 최초 계정은 별도 `MFSG_BOOTSTRAP_TOKEN` 소유 증명 필요. Google bootstrap 우회 금지 |
| 계정 탈취 | argon2id, 잠금, refresh 회전·재사용 감지, 세션 목록/전체 로그아웃, 감사 로그 |
| 다른 사용자 리소스 접근 | 모든 사용자 리소스 `owner_id` scope, fail-closed 404, notification rule/channel도 write/evaluate/deliver 모두 tenant 재검증, cross-user fuzz 회귀 테스트 |
| 프로바이더 키·OAuth 토큰 유출 | DB Fernet at-rest, 로그 redact, GET 마스킹, 관리자 scope, CLI child env scrub. JWT signing secret과 DB encryption key 분리 가능, staged decrypt-only previous keys 지원 |
| SSRF(URL 지식·웹훅·web_fetch) | http(s)만, URL credential 금지, 기본 destination port 80/443, DNS의 **모든** answer가 globally routable인지 검증, 검증한 IP로 socket을 직접 연결하면서 원 hostname으로 TLS SNI/cert 검증, redirect마다 재-resolve/pin, 응답 byte cap. Slack/Discord/custom webhook도 같은 경로 사용 |
| DNS rebinding(검증 DNS와 실제 연결 DNS 불일치) | validation과 TCP connect 사이 재해석 없음. `safe_http`가 resolve한 IP를 connection target으로 pin |
| 업로드 악성 파일/zip bomb/parser DoS | MIME sniff, allowlist/size limit, Office archive entry·uncompressed size·compression-ratio guard, PDF/PPT/XLSX 구조 상한, parser child process에 wall-time/CPU/address-space/file/FD rlimit, child network connect 차단 |
| XSS(마크다운) | react-markdown + rehype-sanitize, 외부 링크 rel 제한, 카드 payload schema 검증, CSP |
| CSRF | access auth는 Bearer. refresh cookie `SameSite=Lax` + Origin 검사 |
| CLI 프로세스 탈출 | Claude native tools 차단, isolated cwd, env whitelist, strict MCP bridge, 256-bit bridge token, public nginx에서 `/api/internal/mcp/` 차단 |
| 컨테이너 권한 상승 | app은 uid/gid 10001로 실행. root는 기존 named-volume ownership 정리 후 즉시 drop. read-only root FS, `cap_drop: ALL`, 필요한 CHOWN/SETUID/SETGID만 add, no-new-privileges, PID limit. `SYS_PTRACE`와 Docker socket autoheal 제거 |
| 비밀 노출 응답 | private/on-request literal + 전화/이메일/카드/API-key pattern redaction. public 또는 현재 턴에서 server-authorized된 literal만 예외 |
| 백업 유출 | retained backup artifact는 age 암호화. DB custom dump + `/data` + Claude state에 checksum/metadata 포함. 선택적 restic off-site 복제, 별도 verify script |

## 인젝션 방어 상세
- 방문자 입력의 `ignore previous`, `system prompt`, `you are now` 류는 telemetry에 `injection_suspect=true`로 기록한다. 문자열 차단 자체를 보안 경계로 보지 않는다.
- 방문자에게 제공되는 tool set은 audience/capability로 서버에서 구성한다. owner-only tool은 모델이 이름을 만들어도 실행할 수 없다.
- 웹/메일 등 외부 내용은 untrusted source로 취급하고, 외부 텍스트 안의 지시를 system authority로 승격하지 않는다.
- `on_request` 값 자체는 prompt에 존재하지 않으므로 prompt injection만으로 추출할 데이터가 없다.
- public event projection은 blacklist가 아니라 allowlist다.

## 레이트리밋과 비용 한도
| 키 | 한도 |
|---|---|
| 로그인 IP | 10/분 |
| 가입 IP | 5/시간 |
| 사용자 API | 300/분 |
| 오너 턴 | 20/분 |
| 방문자 턴(visitor) | `visitor_settings.rate_per_minute` 기본 8 |
| 링크 턴(link) | 120/분 |
| 공개 STT/TTS | 10/분/방문자 |

인메모리 token bucket은 현재 단일 backend process의 burst/rate 방어다. **금전/일일 상한의 정합성은 rate limiter가 아니라 PostgreSQL credit reservation이 보장**한다. 향후 backend를 수평 확장해도 balance/day row lock과 DB invariant는 동일하게 동작한다.

### Turn credit lifecycle
1. conversation row lock 및 idempotency 확인
2. `CreditBalance` → 당일 `UsageDaily` 순서로 row lock
3. available balance / daily cap / visitor daily-turn cap에서 최대 turn hold 계산
4. `credit_reservations(status=held)` + reserved counters 기록
5. API transaction commit
6. 그 이후 provider/runtime 실행 시작
7. provider budget은 DB hold를 초과하지 않도록 동일 hold에서 계산
8. 완료 시 actual usage만 settle, 남은 hold release
9. 실패·cancel·restart recovery 시 hold release

**초과분 정책.** provider 실사용이 hold를 넘으면 초과분은 **청구하지 않는다**(`charged = min(actual, hold)`).
전체 실사용액은 `credit_reservations.actual_credits` 에 남고 runner 가 ERROR 로그를 남긴다. `usage_events.credits`
와 `credit_ledger.delta` 는 항상 같은 capped 값이므로 `sum(usage_events.credits) == -sum(credit_ledger.delta)`
불변식이 유지되고, 폭주한 턴 하나가 잔액을 음수로 만들 수 없다. plan/15 의 "마지막 턴이 넘칠 수 있음"은 hold 상한
(turn cap) 안에서만 허용되는 초과로 해석한다.

**이미 발생한 사용의 기록은 거절하지 않는다.** `apply(..., allow_reserved=True)` 경로(STT/TTS/embedding/summary
`charge_usage`, 월 rollover expire)는 hold 가 있어도 원장에 반드시 기록된다. reserved 가드는 관리자 수동 차감 같은
재량 차변에만 적용된다. 그렇지 않으면 이미 과금된 작업이 402 로 실패하고 원장이 usage 와 어긋난다.

**hold 누수 회수.** 프로세스가 강제 종료되면 `held` 예약이 남아 available balance 를 영구히 줄인다. API 기동 시
`recover_orphaned_turns` 가 쓸고, 그와 별개로 워커가 10분마다 `credits.reservation_reaper` 를 돌려
`RESERVATION_TTL_MINUTES`(기본 120분)보다 오래된 hold 를 release 하고 해당 턴을 `turn_abandoned` 로 닫는다.
같은 잡이 terminal 예약 audit row 도 30일 후 정리한다.

## 개인정보 수집·보존
- 방문자는 익명 continuation token을 기본으로 사용한다. 이름/이메일은 자발 입력이다.
- IP는 원문이 아니라 일 단위 hash로 저장한다. user-agent는 visitor metadata에 제한 길이로 저장된다.
- `visitor_settings.retention_days`(기본 90일)는 단순 conversation row 보존이 아니라 **해당 visitor의 retained conversation이 모두 만료된 시점의 visitor relationship purge**를 뜻한다.
- purge 대상:
  - visitor conversation/message/turn 및 orphan turn event/tool span
  - `Visitor` row의 이름/이메일/note/IP hash/UA metadata
  - visitor-private facts
  - visitor-linked inbox items
  - visitor 식별자가 남아 있는 notification/job payload
  - visitor에서 파생된 아직 승인되지 않은 network proposal의 원 visitor linkage/data
  - visitors namespace note 파일 및 Synapse index entry
- 다른 retained conversation이 남은 visitor는 조기에 삭제하지 않는다.
- 계정 삭제는 DB cascade에 더해 vault/upload storage를 제거한다.
- 내보내기: `/api/users/me/export`.

## 외부 HTTP / SSRF 상세
`services.safe_http`는 user-controlled URL 전용 transport다.

- parser가 허용하는 scheme은 `http`, `https`뿐이다.
- username/password가 포함된 URL은 금지한다.
- 기본 허용 port는 `80,443`; 변경은 `MFSG_OUTBOUND_ALLOWED_PORTS`에 명시한다.
- hostname DNS answer 중 private/loopback/link-local/reserved/non-global이 하나라도 있으면 전체 요청을 거절한다.
- HTTPS는 TCP destination을 검증된 IP로 고정하고 TLS `server_hostname`은 원 hostname으로 유지해 인증서 검증을 보존한다.
- redirect target은 새 URL로 다시 검증/pin한다.
- trusted fixed vendor API(Turnstile/Telegram/LLM provider)는 user-controlled URL이 아니므로 provider client를 사용한다.
- 가능하면 배포 환경의 egress firewall/ACL도 병행한다. 앱 레벨 방어를 유일한 cloud-control-plane 방어로 간주하지 않는다.

## 업로드·문서 파싱
- 업로드 크기/MIME/extension을 intake에서 제한한다.
- Office ZIP은 entry 수, 총 uncompressed size, 비정상 compression ratio를 검증한다.
- PDF page, PPT slide, XLSX sheet/row/column 수에 상한이 있다.
- 문서 내용 파싱은 worker 본 프로세스가 아니라 별도 Python child에서 수행한다.
- POSIX에서는 child에 CPU/address-space/output file/open-FD/core rlimit을 적용하고, parent는 wall-clock timeout과 stdout byte cap을 적용한다.
- child의 socket connect는 차단하며 최소 env만 전달한다.

## 헤더·전송
Cloudflare가 외부 TLS/HSTS를 담당하고 nginx는 host loopback에만 bind한다. nginx에서 `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, CSP를 설정한다. `/api/internal/mcp/`는 public nginx route에서 차단한다.

## 비밀·키 관리
- `deploy/.env`는 host에서 mode 600으로 관리하고 git에 commit하지 않는다.
- `MFSG_SECRET_KEY`: JWT/session/state signing. HTTPS production에서 dev default/32-byte 미만을 startup에서 거절한다.
- `MFSG_ENCRYPTION_KEY`: DB at-rest Fernet 전용 키. 새 production은 signing key와 독립 생성한다.
- 기존 설치는 `MFSG_SECRET_KEY`를 회전하기 **전에** 현재 legacy Fernet derivation을 `MFSG_ENCRYPTION_KEY`로 pin한다. 정확한 절차는 `deploy/README.md`.
- `MFSG_ENCRYPTION_KEY_PREVIOUS`: staged rotation 중 decrypt-only fallback. 신규 write는 primary key만 사용한다.
- 기동 시 `services.keycheck.verify_encryption_keys` 가 실제 at-rest ciphertext(system_settings secret,
  notification channel config, Google 토큰)를 표본으로 복호화해 본다. 표본이 하나도 열리지 않으면 API/worker 는
  **기동을 거부**하고, 복구 절차(이전 `MFSG_SECRET_KEY` 복원 → `keytool legacy` → `MFSG_ENCRYPTION_KEY` 고정)를
  그대로 담은 메시지를 출력한다. 신규 설치(표본 0건)와 정상 staged rotation 은 통과한다.
- `MFSG_BOOTSTRAP_TOKEN`: HTTPS 최초 admin 생성용이며 첫 admin 이후 제거/회전 가능하다.

## 백업·복구
- `deploy/scripts/backup.sh`는 DB custom dump, `/data`(rebuildable cache 제외), Claude state를 임시 root-only workspace에 모으고 checksum을 생성한 뒤 age recipient로 암호화한다.
- 평문 백업 artifact는 retention 디렉터리에 남기지 않는다.
- 선택적으로 restic repository에 encrypted archive를 off-site 복제한다.
- `backup-verify.sh`는 decrypt, checksum, tar parse, `pg_restore --list`를 검증한다.
- 정기적으로 격리 환경의 full restore drill을 수행한다. 백업 키 자체는 backup과 같은 위치에 보관하지 않는다.

## 릴리스 게이트
- [x] 방문자 tool scope에 owner-only tool이 없음(자동 테스트)
- [x] visitor raw `text.delta`가 public SSE/DB replay에 없음
- [x] `on_request` 실제 값이 visitor prompt에 없음
- [x] server-authorized disclosure만 final redactor를 통과
- [x] 크로스 사용자/notification channel tenant boundary 테스트
- [x] 전화/이메일/private literal response redaction 테스트
- [x] Turnstile misconfiguration fail-closed 테스트
- [x] turn idempotency / one-running DB invariant
- [x] atomic credit hold/settle/release 테스트 (동시 예약 경합·초과분 capped·stale hold reaper 포함)
- [x] DNS mixed-answer/private-address SSRF 테스트
- [x] isolated document parser smoke 테스트
- [x] visitor retention identity/inbox/memory purge 테스트 (retained conversation 이 남은 visitor 보존 포함)
- [x] encryption key 불일치 startup fail-closed 테스트
- [x] production container build / compose validation을 CI에서 수행
- [x] frontend production dependency high-severity audit를 CI gate로 수행
- [ ] 배포 후 age-encrypted backup + 별도 identity로 verify (운영 secret/host 필요)
- [ ] 배포 후 실제 provider/Google OAuth smoke (운영 credential 필요)
