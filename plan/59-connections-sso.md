# plan/59 — 연결(Google·카카오): 로그인(SSO)과 데이터 연동, 관리자 [연결]

상태: 설계 → 구현 (2026-09-25)

## 0. 요청

- 프로덕션 수준으로 **카카오·구글 등** 외부 서비스와 연결한다. 정보를 가져오는 것만이 아니라 **SSO(그 계정으로 로그인)** 도.
- 관리자 설정에 **[연결]** 을 새로 두고, 그 아래 **Google · 카카오** 가 있다. 관리자가 필요한 값을 넣으면 **그대로 작동**해야 한다.
- 앞으로 다른 연결(네이버·애플·회사 IdP 등)도 들어온다.

## 1. 지금 상태 (조사)

| 영역 | 지금 | 문제 |
|---|---|---|
| Google 로그인 | `/api/auth/google/start·callback`, `AuthIdentity` 에 연결, 이메일이 같으면 기존 계정에 붙임 | ① `id_token` 을 **검증하지 않고** base64 로 풀기만 한다(서명·iss·aud·exp) ② `nonce` 없음 ③ `state` 가 브라우저와 묶이지 않아 **로그인 CSRF**(남의 계정으로 로그인시키기)에 열림 ④ **초대제**면 초대 코드를 실어 보낼 길이 없어 가입 실패 ⑤ 로그인된 사람이 계정 설정에서 Google 을 **연결·해제하는 길 없음** |
| Google 데이터 | 메일·일정 읽기/넣기·연락처, `connections` 한 줄에 토큰 암호화 | OAuth 코드가 `services/google.py` 에 Google 전용으로 박혀 있어 다른 공급자가 재사용할 수 없다 |
| 관리자 설정 | [시스템 설정] 안에 "Google OAuth" 두 칸 | 켜고 끄는 스위치·로그인 여부·제공 기능 선택·리디렉트 주소 안내·**설정 확인** 없음 |
| 카카오 | 없음 | — |

## 2. 원칙

1. **공급자 등록표.** 공급자마다 클래스 하나(`services/oauth/<id>.py`): 인가·토큰·갱신·신원·철회·설정 확인. 화면은 서버 목록을 그대로 그린다.
2. **관리자가 값을 넣으면 그대로 작동.** 설정은 DB(시스템 설정, 비밀은 암호화·가림). 켜기 전에 [설정 확인]으로 키가 맞는지 바로 알 수 있다.
3. **로그인(SSO)과 데이터 연동은 따로 켠다.** 같은 앱 키를 쓰되, "로그인에 쓰기"와 "사용자에게 줄 기능(메일·일정·알림…)"을 공급자마다 고른다.
4. **보안은 표준대로.** state(브라우저 쿠키와 묶음, 15분) + nonce(OIDC) + id_token 검증(JWKS 서명·iss·aud·exp·nonce) + 토큰 암호화 저장 + 되돌아갈 주소는 우리 앱 경로만.
5. **계정 연결 규칙.** 공급자가 **검증했다고 말한 이메일**만 기존 계정과 이어 붙인다. 이메일을 주지 않는 카카오 계정은 가입을 마무리하는 한 단계(이메일 입력)를 거친다 — 일반 가입과 같은 규칙(초대제·닫힘·이메일 인증 설정)을 그대로 따른다.
6. **데이터는 [내 정보]의 한 곳을 거친다** (plan/57): Google 캘린더·카카오 톡캘린더 → 스케줄, Google 메일 → 메일, Google 연락처 → 인맥, 카카오톡 "나에게 보내기" → 알림 채널.

## 3. 공급자

### Google
- 로그인: OpenID Connect (`openid email profile`), id_token 검증(JWKS `googleapis.com/oauth2/v3/certs`, iss `accounts.google.com`).
- 기능: 메일 읽기(gmail.readonly) · 일정 읽기(calendar.readonly) · 일정 넣기(calendar.events) · 연락처(contacts.readonly).
- 관리자 값: Client ID, Client Secret.

### 카카오
- 로그인: 카카오 로그인. OpenID Connect 를 켰으면 `openid` 로 id_token(JWKS `kauth.kakao.com/.well-known/jwks.json`, iss `https://kauth.kakao.com`), 아니면 `/v2/user/me`. 신원 = 회원번호(`sub`/`id`).
  이메일은 [카카오계정(이메일)] 동의항목을 설정한 앱에서만 오고, `is_email_valid` · `is_email_verified` 가 참일 때만 믿는다.
- 기능: 톡캘린더 일정 읽기·넣기(`talk_calendar`) → 스케줄, 카카오톡 나에게 보내기(`talk_message`) → 알림 채널.
- 관리자 값: REST API 키, Client Secret(카카오에서 켰을 때만), OpenID Connect 사용 여부, 이메일 동의항목 사용 여부.
- 추가 동의: 기능을 켤 때 그 동의항목만 더 받는다(카카오의 "추가 항목 동의").

## 4. 관리자 [연결] (`/admin/connections`)

사이드 메뉴 [서비스] 묶음에 **[연결]**. 위쪽 탭으로 공급자(Google · 카카오 …). 공급자마다:

- **사용** 스위치 — 끄면 로그인 버튼·연동 카드가 모두 사라진다(이미 연결된 것은 그대로 두되 새로 받지 않는다).
- **로그인에 쓰기** 스위치 — 로그인·가입 화면에 "Google로 계속하기 / 카카오 로그인".
- **사용자에게 줄 기능** — Google: 메일·일정 읽기·일정 넣기·연락처 / 카카오: 톡캘린더·나에게 보내기.
- **앱 키** — 공급자마다 필요한 칸(비밀은 입력 후 가려짐, 비워 두면 그대로).
- **등록할 주소** — 공급자 콘솔에 넣을 리디렉트 URI 두 개(로그인·연동)와 카카오는 사이트 도메인, 복사 버튼.
- **설정 확인** — 서버가 공급자 토큰 창구에 가짜 코드를 보내 응답으로 키를 판정(키가 틀리면 invalid_client, 맞으면 invalid_grant). "키가 맞아요 / 앱 키가 틀려요 / Secret 이 틀려요 / 주소가 등록되지 않았어요".
- **현황** — 이 공급자로 로그인하는 사람 수, 데이터 연결 수.
- 짧은 설정 안내(공급자 콘솔에서 할 일 순서)와 콘솔 바로가기.

[시스템 설정]의 옛 "Google OAuth" 칸은 걷는다(값은 새 자리로 옮긴다).

## 5. 사용자 화면

- **로그인·가입**: 로그인에 쓰기가 켜진 공급자마다 버튼. 초대제면 입력한 초대 코드를 실어 보낸다.
- **가입 마무리**(`/signup/complete`): 이메일을 주지 않은 카카오 계정 — 이메일·이름을 받아 가입. 그 이메일이 이미 있으면 "그 계정으로 로그인한 뒤 계정 설정에서 연결하세요".
- **계정 설정 › 로그인 방법**: 비밀번호(없으면 만들기) · Google · 카카오 — 연결/해제. 마지막 남은 로그인 방법은 해제할 수 없다.
- **연동**(`/app/integrations`): 공급자 카드(관리자가 켠 것만), 기능 선택 후 연결, 권한 켜고 끄기, 가져오기, 해제.
- **스케줄 [연동]**: Google 캘린더 · 카카오 톡캘린더 카드(같은 틀, plan/58).
- **알림**: "카카오톡 나에게 보내기" 채널.

## 6. 데이터

- 시스템 설정: `oauth.<provider>.<field>` — enabled · login · features · client_id · client_secret(비밀) · (카카오) oidc · email.
  마이그레이션 0077: `google_oauth.client_id/secret` → `oauth.google.*`, 값이 있었으면 enabled·login·모든 기능 켬(지금 동작 그대로).
- `auth_identities`(있음): provider · subject · email · raw_profile.
- `connections`(있음): provider 별, 토큰 암호화, capabilities, scopes, settings.
- `notification_channels`: kind `kakao` (config: connection_id).

## 7. 단계

1. 백엔드: 설정·0077 → `services/oauth`(base·google·kakao·state·registry·id_token 검증) → `services/connections`(공통 토큰 갱신·철회) →
   `api/auth` SSO(시작·콜백·가입 마무리·신원 목록·연결·해제) → `api/integrations` 공통화 → 카카오 톡캘린더·나에게 보내기 →
   스케줄 연동·미팅 넣기 공통화 → 알림 채널 → 관리자 API(목록·저장·설정 확인) → 테스트(공급자 HTTP 흉내).
2. 프론트: 관리자 [연결] · 로그인/가입 버튼 · 가입 마무리 · 계정 설정 로그인 방법 · 연동 화면 공통화 · 알림 채널.
3. 배포·확인: 관리자 화면에서 값 저장·설정 확인(틀린 키 → 정확한 오류), 로그인 버튼 노출 규칙, 가입 마무리 화면, 계정 설정.
   실제 공급자 로그인은 운영 키가 있어야 해서 테스트(흉내)로 확인하고, 관리자가 키를 넣으면 바로 동작한다.

## 구현

- 공급자 틀 `services/oauth/`: `base.py`(설정 `oauth.<id>.*` · 인가 주소 · 코드 교환 · 갱신 · 철회 · [설정 확인]) ·
  `google.py` · `kakao.py` · `idtoken.py`(JWKS 서명 · iss · aud · exp · nonce, 모르는 kid 면 한 번 다시 받음) ·
  `state.py`(서명한 state + 흐름을 시작한 브라우저의 HttpOnly 쿠키 `memora_oauth`, path=/api, 15분).
  공급자를 더하려면 이 모양의 클래스 하나를 `PROVIDERS` 에 넣으면 관리자·로그인·연동 화면이 그대로 그린다.
- 연결 한 줄 `services/connections.py`: 이 사람의 이 공급자 연결은 한 줄(계정 번호 `settings.subject`).
  다른 계정으로 다시 이으면 앞 계정에서 가져온 메일·일정은 지운다. 토큰은 여기서만 나오고, 관리자가 끈
  공급자면 여기서 막힌다(메일·일정·알림 어느 길로도 닿지 않음). 끊을 때 공급자 쪽 권한도 거둔다(카카오는
  데이터 동의항목만, 만료된 토큰이면 갱신한 뒤).
- 로그인 `api/auth.py`: `GET /api/auth/{p}/start`(next · invite) → `GET /api/auth/{p}/callback`.
  연결된 계정 → 로그인 / 공급자가 검증한 이메일 → 기존 계정에 이음(인증 안 된 계정이면 먼저 가입해 둔 사람의
  비밀번호와 세션을 거둔다) / 새 이메일 → 가입 규칙(닫힘 · 초대제 · 첫 관리자) 그대로 / 이메일 없음 →
  `/signup/complete`(30분 토큰, 가입이 닫혔으면 거기까지 보내지 않음). 데이터 연동의 state 로는 로그인하지 않는다.
  `GET /api/auth/identities`, `POST /api/auth/identities/{p}/start`, `DELETE /api/auth/identities/{id}`(마지막 방법은 못 뗌).
- 데이터 연동 `api/integrations.py`: `POST /{p}/start` · `GET /{p}/callback`(동의 화면에서 뺀 기능은 `partial=`) ·
  `PATCH /{id}`(아직 받지 않은 권한이면 `consent_url`).
- 카카오 데이터 `services/kakao.py`: 톡캘린더 가져오기(31일 창 · after_url), 넣기(5분 단위), 나에게 보내기.
  알림 채널 `kakao`(연결 + 메시지 권한 필요, 받는 이는 늘 본인이라 따로 인증하지 않음, 링크는 알림의 화면).
- 관리자 `api/admin_connections.py`: `GET /api/admin/connections`, `PUT /{p}`(비밀은 비우면 유지, 필수 키 없이는
  못 켬, 켜 둔 채로는 필수 키를 못 지움, 기능을 거두면 이미 켠 사용자에게서도 끔), `POST /{p}/check`.
- 수락한 미팅: "넣기"를 켠 바깥 달력(Google · 카카오)에 → 결과 `calendar.external{provider,label,status}`.
  스케줄의 가져온 일정은 `source` 가 공급자 이름. 비서 도구도 가져온 일정은 거기서 고치라고 답한다.
- 화면: 관리자 [서비스 → 연결], 로그인·가입의 버튼(카카오 #FEE500), `/signup/complete`, 계정 설정 [로그인 방법]
  (비밀번호가 없으면 "비밀번호 만들기"), 연동 화면(공급자 카드 · 기능 스위치 · 다시 연결), 알림 [+ 카카오톡].
- 설정 키 `google_oauth.*` → `oauth.google.*` (alembic 0077). 시스템 설정의 Google OAuth 칸은 걷었다.
- 테스트: `tests/test_sso.py`(20), 기존 달력·미팅·감사 테스트를 새 규칙(꺼 둔 공급자의 데이터는 보이지 않음)에 맞춤. 전체 580 통과.

## 운영 확인 (2026-09-25)

- 0077 적용(운영에는 Google 설정·연결이 없어 옮길 것이 없었다). 배포 전 `~/backups/memora-before-0077-*.dump`.
- 실제 공급자 응답으로 [설정 확인]: 가짜 Google 키 → "The OAuth client was not found." → 앱 키가 맞지 않음,
  가짜 카카오 REST 키 → "Not exist client_id" → 앱 키가 맞지 않음.
- 카카오를 가짜 키로 잠시 켜서: 로그인·가입 화면에 노란 버튼, 누르면 `kauth.kakao.com`(닉네임만 청함) → 카카오 로그인
  화면까지 간다. 연동의 [카카오 연결하기]는 `profile_nickname,talk_calendar,talk_message` 로 데이터 콜백에,
  계정 설정의 [카카오 연결]은 로그인 콜백에. 쿠키는 HttpOnly · Secure · Path=/api.
- 휴대폰 폭 넘침 없음(로그인 · 가입 · 가입 마무리 · 관리자 [연결]). 확인 뒤 카카오를 끄고 가짜 키를 지웠다.
- 운영 관리자가 할 일: 각 콘솔에서 앱을 만들고 [연결]의 "콘솔에 등록할 값"을 등록 → 키 입력 → [설정 확인] → [사용하기].
