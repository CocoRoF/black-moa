# 05 · 계정 체계 개편 · 인증 · 권한

## 문제 (Geny 현재)
- 단일 관리자(`admin_users` 1행), JWT 30일, 쿠키 `httponly=False`, 소유권 검사 fail-open, 역할 없음.
- 누구나 에이전트·전체 설정 조회 가능. B2C 로 부적합 → **전면 재설계**.

## 모델

### 역할
| role | 획득 | 권한 |
|---|---|---|
| `admin` | **최초 가입자 자동**. 이후엔 admin 이 다른 사용자를 승격 가능(항상 ≥1 유지) | 모든 인프라 설정(`/api/admin/*`), 사용자 관리, 크레딧 부여, 전 에이전트 메타 조회(내용은 아님 — 대화 본문은 오너 동의 없인 못 봄, 감사 로그만) |
| `user` | 일반 가입 | 자기 소유 리소스만 |

### 소유권 규칙 (전 리소스 공통)
- 모든 도메인 테이블에 `owner_id`(uuid, FK users) — 예외: `users`, `system_settings`, `model_catalog`, `plans`.
- 서비스 계층 진입점에서 `assert_owner(resource.owner_id == current_user.id or current_user.role == admin_for_meta)`.
  **fail-closed**: owner_id 가 NULL 인 행은 아무도 접근 불가(마이그레이션 버그 감지).
- 리스트 쿼리는 항상 `WHERE owner_id = :uid` — 리포지토리 헬퍼 `owned(query, uid)` 강제, 코드리뷰 체크리스트 항목.

### 가입 정책 (관리자 설정 `signup.mode`)
- `open`(기본) · `invite`(초대 코드 필요 · `invites` 테이블) · `closed`.
- 이메일 인증: `signup.require_email_verification`(기본 off — SMTP 미설정일 수 있음; on 이면 6자리 코드 메일).

## 인증 방식

### 이메일 + 비밀번호
- 비밀번호 해시 **argon2id**(`argon2-cffi`), 최소 8자 + 유출 비밀번호 목록 상위 1만 차단.
- 로그인 실패 5회/15분 → 계정 잠금 15분 + IP 레이트리밋.
- 비밀번호 재설정: 이메일 토큰(30분, 1회).

### Google 로그인 (OAuth 2.0 / OIDC)
- 관리자가 `google.client_id/secret` 등록하면 활성. `openid email profile` 스코프.
- 같은 이메일 계정 존재 시 링크(비밀번호 계정 → google 연결). `auth_identities(provider, subject, user_id)`.
- 로그인용 OAuth 와 **데이터 연동용 OAuth(plan/11)** 는 별도 동의(스코프 증분) — 로그인은 최소 스코프.

### 토큰
- **access JWT**(HS256, 15분, payload `{sub, role, sid, iat, exp}`) — 응답 바디로 전달, 프론트 메모리 보관(zustand). localStorage 금지.
- **refresh 토큰**(불투명 256bit, 30일, 회전·재사용 감지) — `httpOnly; Secure; SameSite=Lax; Path=/api/auth` 쿠키 + DB `sessions_auth` 해시 저장. 회전 시 이전 토큰 재사용 → 세션 패밀리 전체 폐기.
- `POST /api/auth/refresh` 로 access 갱신. 프론트 `api.ts` 가 401 시 1회 자동 refresh 후 재시도(single-flight).
- 로그아웃 = refresh 폐기 + 쿠키 삭제. "모든 기기에서 로그아웃" 지원.
- 방문자 토큰(plan/12)은 별도 서명 키 파생(`visitor` 오디언스), 사용자 API 접근 불가.
- 서명 키: `MFSG_SECRET_KEY` 에서 HKDF 로 `jwt_user`, `jwt_visitor`, `csrf` 파생. 키 고정 → 재배포 시 로그아웃 없음.

### 미들웨어
- 순수 ASGI `AuthMiddleware`(Geny `RequireLoginMiddleware` 패턴): 기본 차단, 공개 allowlist 만 통과:
  `/health*`, `/api/auth/(signup|login|refresh|logout|status|google/*|password/*)`, `/api/public/*`(방문자 토큰 자체 검증), `/static/*`, `/api/admin/bootstrap-status`.
- `require_user`, `require_admin`, `require_visitor` 의존성. 문서 UI(`/docs`)는 admin 만.

## 계정 API

```
POST /api/auth/signup {email, password, display_name, invite_code?}   → 최초면 role=admin
POST /api/auth/login {email, password}                                 → {access_token, user}
POST /api/auth/refresh                                                 → {access_token}
POST /api/auth/logout  · POST /api/auth/logout-all
GET  /api/auth/me
GET  /api/auth/status                                                  → {bootstrap_needed, signup_mode, google_login_enabled}
GET  /api/auth/google/start → 302 · GET /api/auth/google/callback
POST /api/auth/password/forgot · POST /api/auth/password/reset
POST /api/auth/email/verify
GET  /api/users/me · PATCH /api/users/me {display_name, avatar, locale, timezone}
POST /api/users/me/password
DELETE /api/users/me   (전 리소스 연쇄 삭제, 크레딧 잔액 소멸 경고)
```

## 사용자 데이터 모델 (`users`)
`id, email(citext unique), email_verified_at, password_hash nullable, display_name, avatar_url, locale('ko'), timezone('Asia/Seoul'), role, status(active|suspended|deleted), plan_id, onboarding_state jsonb, last_login_at, created_at, updated_at`.

## 관리자 부트스트랩
- 사용자 0명 → 프론트 `/signup` 에 "관리자 계정을 만듭니다" 배너. 첫 가입 트랜잭션에서 `SELECT count(*) FOR UPDATE` 로 경합 차단.
- 최초 로그인 직후 `/admin/setup` 위저드: 프로바이더 키 → 모델 카탈로그 → 플랜 → 도메인 확인.

## 감사 로그
`audit_logs(actor_id, action, target_type, target_id, ip, ua, meta, at)` — 로그인/키 변경/크레딧 부여/역할 변경/에이전트 공개 상태 변경. 관리자 화면에서 조회.

## 테스트 (plan/21)
- 최초 가입 = admin, 두 번째 = user. 동시 가입 경합.
- 다른 사용자의 agent_id 로 모든 엔드포인트 호출 → 404(존재 은닉).
- refresh 회전·재사용 감지. 잠금.
- 방문자 토큰으로 `/api/agents` → 401.
