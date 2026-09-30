# 30 · Claude Code 계정 풀 (로드밸런싱)

## 왜

`plan/17` 의 claude_code 경로는 **로그인 하나**를 전제로 했다. `~/.claude/.credentials.json` 하나, `providers.claude_code.auth_mode` 하나. 그래서:

- 그 구독 하나의 **레이트리밋이 곧 서비스 전체의 레이트리밋**이다. 동시 대화가 조금만 늘면 전부 `rate_limited` 로 떨어진다.
- 그 로그인 하나가 만료되면 **서비스 전체가 멈춘다**. 관리자가 다시 로그인할 때까지 모든 턴이 실패한다.
- 계정을 하나 더 붙이려면 컨테이너를 하나 더 띄우는 것 말고는 방법이 없다.

계정 풀은 이 세 가지를 한 번에 없앤다. 관리자가 Claude 계정을 **여러 개 인증**해 두면, 세션마다 하나를 배정하고, 한도에 걸리거나 만료된 계정은 스스로 로테이션에서 빠진다.

## 모양

```
claude_accounts (DB, 진실의 원본)          <data_dir>/claude-accounts/<id>/         (CLI 작업 사본)
  label · auth_mode · credentials(암호화)    ├── .claude/.credentials.json  0600     ← HOME
  weight · max_concurrency                   └── (CLI 가 알아서 쓰는 상태 파일들)     ← CLAUDE_CONFIG_DIR
  status · cooldown_until · 카운터
```

**계정마다 별도의 CLI 홈.** `HOME` 과 `CLAUDE_CONFIG_DIR` 을 둘 다 계정 디렉터리로 넘긴다. 하나만 넘기면 CLI 가 `HOME` 에서 config 디렉터리를 유도해 **다른 계정의 토큰을 읽는다** — 격리는 여기서 성립하거나 깨진다.

DB 가 원본, 파일은 사본이다. CLI 는 액세스 토큰을 파일에서 직접 갱신하므로 `claude_creds.backup` 잡(매시간)이 파일 → DB 로 **수확(harvest)** 하고, 컨테이너가 새로 뜨면 DB → 파일로 **물질화(materialize)** 한다. 양쪽 모두 "더 오래된 것이 더 새것을 덮지 않는다" 가드를 건다.

## 배정 (`services/claude_balancer.py` — 순수 함수)

밸런서는 DB도 파일도 시계도 모른다. 스냅샷을 받아 결정을 돌려준다. 그래서 "한도 걸린 계정이 정말 로테이션에서 빠지는가" 를 서브프로세스 없이 테스트할 수 있다.

| 전략 | 규칙 |
|---|---|
| `least_busy` (기본) | `in_flight / max_concurrency` 가 가장 낮은 계정. 절대 세션 수가 아니라 **자기 한도 대비** 여유 |
| `round_robin` | 사용 가능한 계정을 순서대로 |
| `weighted` | nginx 의 smooth weighted round-robin. 3:1 이면 `A A B A` — `A A A B` 로 몰지 않는다(몰면 그게 곧 레이트리밋) |
| `least_recently_used` | 가장 오래 쉰 계정. 일일 한도를 고르게 쓸 때 |

**제외 사유**(콘솔에 그대로 표시): `disabled` · `no_credentials` · `expired` · `cooling_down` · `at_capacity`.

자격 파일을 디스크에 쓰지 못한 계정은 그 계정만의 문제다. 그 자리에서 **건너뛰고 전략에 다시 묻는다**(그리고 일반 실패로 집계해 계속 깨져 있으면 스스로 쉬게 한다). 셋 중 하나가 쓰기 불가라고 설치 전체를 레거시 단일 자격으로 되돌리면, 그때부터 그건 풀이 아니다.

## 건강 상태 (같은 모듈, 순수 함수)

턴의 판정은 `providers/errors.py::classify` 가 이미 내놓는 코드를 그대로 쓴다. 사용자에게 나간 메시지와 계정을 벌하는 근거가 **같은 판정**이어야 한다.

| 코드 | 처리 | 이유 |
|---|---|---|
| `rate_limited` | `cooldown_until = now + 15분` | 기다리면 풀린다 |
| `provider_quota` | `cooldown_until = now + 1시간` | 더 오래 걸린다 |
| `provider_auth` | `status = expired` (쿨다운 아님) | 기다려도 안 고쳐진다. 사람이 다시 로그인해야 한다 |
| `context_limit` · `cancelled` · `credits_exhausted` | **아무것도 하지 않음** | 계정 탓이 아니다. 대화가 길어진 걸로 계정을 빼면 멀쩡한 풀이 스스로 장애를 만든다 |
| 그 외 | 연속 3회부터 쿨다운, 재발할수록 2배 백오프(최대 6시간) | |

성공 한 번이면 전부 초기화된다.

## 같은 리눅스 계정에서 여러 로그인이 되는가 (실측)

된다. 백엔드는 uid 10001 하나로 돌지만 Claude Code 는 `HOME` 과 `CLAUDE_CONFIG_DIR` 을 그대로 따른다.
프로드 컨테이너에서 확인한 것:

```
HOME=/home/memora  CLAUDE_CONFIG_DIR=/home/memora/.claude  claude auth status --json
  → {"loggedIn": true,  "authMethod": "claude.ai", "email": "…"}
HOME=/data/_isotest CLAUDE_CONFIG_DIR=/data/_isotest/.claude claude auth status --json
  → {"loggedIn": false, "authMethod": "none"}
```

같은 OS 계정, 같은 프로세스 권한인데 한쪽은 로그인 상태이고 다른 쪽은 아니다. `claude auth login --claudeai`
도 격리된 홈에서 정상적으로 URL 을 뱉는다. 그리고 `CLAUDE_CONFIG_DIR` 을 주면 CLI 는 `.claude.json` 까지
그 디렉터리 안에 쓴다 — `$HOME/.claude.json` 이 아니라. 즉 계정당 상태가 전부 한 디렉터리에 담긴다.

**OS 계정을 나눌 필요가 없다.** 나눴다면 파일 소유권·볼륨 권한·프로세스 전환이라는 문제가 새로 생겼을 뿐이다.

## 임대(lease) 수명

- **세션**: 파이프라인 빌드에서 1개 임대 → 런타임이 닫힐 때까지 유지. CLI 클라이언트가 그 계정의 자격으로 만들어지고 프롬프트 캐시도 그 계정 것이므로, 턴마다 계정을 바꾸는 것은 이득이 아니라 손해다. 턴마다 **건강만** 보고한다(`release=False`).
- 임대한 계정이 로테이션에서 빠지면 그 런타임을 **버린다**. 다음 턴은 건강한 계정으로 다시 빌드된다.
- **백그라운드**(증류·요약): 호출 1건 = 임대 1건. 짧고 잦으므로 계정을 붙들지 않는다.
  건강 보고는 **자기 세션**으로 쓴다. 워커는 핸들러가 예외를 던지면 세션을 롤백하므로(`worker/__main__.run_job`), 호출자 세션에 쓴 쿨다운은 실패한 그 순간 같이 사라진다 — 풀이존재하는 바로 그 경로에서 판정을 잃는 셈이다.
- **프로브**: 풀이 살아 있으면 프로브도 임대해서 돈다. 실제 턴이 쓰는 경로가 아닌 것을 검증해 초록불을 켜는 것이 가장 나쁘다.

동시성 카운터는 **프로세스 로컬**이다(워커가 여러 개면 각자 자기 몫을 분배한다). 로테이션에서 빠졌는지 아닌지를 결정하는 값 — 쿨다운·상태·실패 카운터 — 는 DB 에 있으므로 전역이다.

## 하위 호환

풀이 **비어 있으면 아무것도 바뀌지 않는다.** `acquire()` 가 `None` 을 돌려주고 모든 호출부는 기존 단일 자격 경로로 떨어진다. 마이그레이션은 테이블만 만들고, 기존 로그인·설정·볼륨은 손대지 않는다.

## API (`/api/admin/*`, 전부 require_admin)

```
GET    /providers/claude-code/accounts                     계정 + 풀 상태 + 라이브 카운터
PUT    /providers/claude-code/pool                         {enabled, strategy}
POST   /providers/claude-code/accounts                     {label, email, auth_mode, weight, max_concurrency}
PATCH  /providers/claude-code/accounts/{id}                enabled·weight·concurrency·setup_token·api_key…
DELETE /providers/claude-code/accounts/{id}                자격 파일도 함께 삭제
POST   /providers/claude-code/accounts/{id}/import         {credentials_json}
POST   /providers/claude-code/accounts/{id}/probe          그 계정만으로 1턴
POST   /providers/claude-code/accounts/{id}/cooldown/clear
POST   /providers/claude-code/accounts/{id}/login/start  · GET …/login · GET …/login/events (SSE)
POST   /providers/claude-code/accounts/{id}/login/input  · POST …/login/cancel
```

로그인 중계는 단일 계정 것과 **같은 코드**다. 릴레이가 계정별 홈을 향할 뿐이고, 대상마다 하나씩 돌 수 있으므로 첫 계정이 코드 입력을 기다리는 동안 두 번째 계정을 로그인할 수 있다.

## 콘솔

`/admin/providers`. **자기 메뉴를 갖지 않는다** — Claude Code 카드 바로 아래, 같은 페이지에 있다.
별도 메뉴에 두면 "이 프로바이더의 로그인이 여러 개" 가 아니라 "다른 기능" 으로 읽히고, 실제로 그렇게
읽혔다. 구성은 요약(계정 수·로테이션 중·진행 세션) + 전략 선택 + `[계정 추가]` + 계정 카드(상태 배지·
제외 사유·세션/실패 카운터·쿨다운 해제·로그인·JSON 가져오기·프로브·가중치/동시성). 옛 `/admin/claude-pool`
경로는 리다이렉트로 남겨 둔다.

## 설정

| 키 | 기본 | 뜻 |
|---|---|---|
| `providers.claude_code.pool.enabled` | `true` | 끄면 즉시 단일 계정 경로 |
| `providers.claude_code.pool.strategy` | `least_busy` | |
| `providers.claude_code.pool.failure_threshold` | `3` | 원인 불명 연속 실패 몇 번에 쉬게 할지 |
| `providers.claude_code.pool.failure_cooldown_s` | `120` | |
| `providers.claude_code.pool.rate_limit_cooldown_s` | `900` | |
| `providers.claude_code.pool.quota_cooldown_s` | `3600` | |

## 운영

- 자격증명은 `system_settings` 와 같은 Fernet 키로 **행 안에서 암호화**된다. DB 덤프가 살아 있는 세션 묶음이 되어서는 안 된다.
- 파일은 `0600`, 디렉터리는 `0700`. 계정을 지우면 파일도 지운다 — 아무도 감사하지 않는 잔여물이 정확히 이런 것이다.
- `ops.watch` 는 풀이 서빙 중이면 풀을 본다: 로테이션 0개면 즉시 경고, 일부가 빠졌으면 이름과 함께, 로그인 만료 3일 전에 계정별로. `at_capacity` 는 경고하지 않는다 — 그건 풀이 제 일을 하고 있다는 뜻이다.
- 감사 로그: `claude_account_create` · `_update` · `_delete` · `_import` · `_cooldown_clear` · `_login_start` · `claude_pool_settings`. 시크릿은 "교체됨" 여부만 남는다.
