# 11 · 계정 연동 (구글 우선) · 범용 연동 프레임워크

## 목표
비서가 오너의 **이메일·일정·연락처**를 알고 답한다. v1 은 **Google** 을 완전 구현하고, 다른 공급자는 같은 프레임워크 위에 어댑터만 추가하면 되게 만든다.

## 프레임워크

### `connections` 테이블
`id, owner_id, provider(google|microsoft|notion|slack|github…), account_label(이메일 등), scopes text[], access_token_enc, refresh_token_enc, token_expires_at, status(active|expired|revoked|error), last_sync_at, sync_cursor jsonb, settings jsonb, created_at`.
토큰은 Fernet 암호화(`MFSG_ENCRYPTION_KEY`). 로그 마스킹.

### 어댑터 인터페이스 (`services/integrations/base.py`)
```python
class IntegrationProvider(Protocol):
    id: str
    display_name: str
    scopes: dict[str, list[str]]        # capability -> OAuth scopes  (예: {"gmail_read": [...], "calendar_read": [...], "contacts": [...]})
    def auth_url(self, state, capabilities) -> str
    async def exchange(self, code) -> TokenSet
    async def refresh(self, token_set) -> TokenSet
    async def sync(self, conn, capability, cursor) -> SyncResult   # 증분 동기화 → 캐시 테이블 upsert
    def tools(self, audience) -> list[Tool]                           # 파이프라인에 노출할 도구
```
- OAuth 콜백 `GET /api/integrations/{provider}/callback` (공개 allowlist, `state` 에 사용자·capabilities·nonce 서명).
- 능력(capability) 단위로 동의 증분: 사용자는 "메일 읽기"만 켤 수도 있음.

### 캐시 테이블 (연동 데이터는 원본을 그대로 저장하지 않고 **요약·색인**만)
- `integration_emails(owner_id, conn_id, ext_id, thread_id, from, to[], subject, snippet, received_at, labels[], summary, embedding vector(1536), importance)` — 최근 30일/최대 2,000통. 본문은 저장하지 않음(요청 시 API 로 실시간 fetch, 오너 모드 전용).
- `integration_events(owner_id, conn_id, ext_id, title, start_at, end_at, all_day, location, attendees[], visibility(private|busy-only|public), description_summary)` — 과거 7일~미래 60일.
- `integration_contacts` → 곧바로 `network_nodes(source=google_contacts)` 로 변환(plan/10). 별도 캐시 없음.
- `integration_files`(v2, Drive).

### 동기화
- 워커 잡 `integration.sync(conn_id, capability)`: 최초 전체 → 이후 15분 주기 증분(Gmail `historyId`, Calendar `syncToken`, People `syncToken`). 실패 시 지수 백오프, 401 → `status=expired` + 오너 알림.
- 이메일 요약·중요도는 저비용 모델로 배치(50통/호출) — 크레딧 차감(`usage_kind=integration_summary`, 요금표 별도 항목, 오너에게 예상 비용 표시·끄기 가능).

## Google 어댑터 (v1 완전 구현)
- OAuth 2.0 (웹 서버 플로우, PKCE), 관리자 설정 `google.client_id/client_secret`, 리다이렉트 `{PUBLIC_URL}/api/integrations/google/callback`.
- 능력 → 스코프:
  - `profile`: `openid email profile`
  - `gmail_read`: `https://www.googleapis.com/auth/gmail.readonly`
  - `calendar_read`: `.../calendar.readonly`
  - `calendar_write`(v1.5, 미팅 요청 → 초안 이벤트 생성): `.../calendar.events`
  - `contacts`: `.../contacts.readonly`
  - `gmail_send`(v2 — 비서가 오너 대신 메일 발송, 오너 승인 카드 필요)
- API: Gmail REST `users.messages.list/get(format=metadata)`, `users.history.list`; Calendar `events.list(singleEvents, timeMin/Max, syncToken)`; People `people.connections.list(personFields=names,emailAddresses,organizations,phoneNumbers)`.
- 토큰 갱신은 호출 직전 60초 여유로.

## 파이프라인 노출 (plan/07)

| 도구 | 오너 | 방문자 | 설명 |
|---|---|---|---|
| `email_search(query, days)` | ✓ | ✗ | 캐시 검색(제목/발신/요약 + 임베딩) |
| `email_read(ext_id)` | ✓ | ✗ | 실시간 본문 fetch(≤ 8k자) |
| `calendar_list(from, to)` | ✓ | ✗ | 상세 |
| `calendar_availability(from, to)` | ✓ | ✓ | **busy/free 만**(방문자에겐 제목·참석자 절대 노출 안 함), 오너가 설정한 공개 시간대(`profile.availability_window`) 교집합 |
| `contacts_lookup(name|email)` | ✓ | ✗ (network_search 로 대체) | |
| `meeting_propose(slots, purpose)` | ✗ | ✓ | 인박스 요청 생성(+ v1.5 캘린더 초안) |

컨텍스트 주입(오너 모드만): "오늘/내일 일정 N건 요약", "읽지 않은 중요 메일 상위 5 요약" ≤ 500 토큰. 방문자 모드: 가용성 창만.

## 오너 콘솔 `/app/integrations`
- 공급자 카드(Google 연결됨/미연결, 능력 토글, 마지막 동기화, 오류), [연결 해제](토큰 revoke + 캐시 삭제 확인).
- 연동 데이터 미리보기(최근 메일 요약 10, 다가오는 일정 10)·"비서에게 보이는 범위" 설명.
- 비용 안내: 요약 배치가 쓰는 크레딧 예측.

## 다른 연동(뼈대만, v2)
`microsoft`(Graph: mail/calendar/contacts, 같은 능력 이름), `notion`(페이지 검색 → 지식), `slack`(DM 알림 채널은 plan/16 웹훅으로 충분), `github`(프로필/저장소 → 지식). 어댑터 파일만 추가하면 UI 카드가 자동 생성되도록 레지스트리 기반.

## 보안
- 스코프 최소·증분, 토큰 암호화, 방문자 모드에서 연동 도구 미등록(카탈로그에도 없음), 감사 로그, 연결 해제 시 Google `revoke` 호출.
