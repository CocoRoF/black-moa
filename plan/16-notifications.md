# 16 · 알림 (비서 대화 → 오너에게)

## 이벤트
| event | 트리거 | 기본 긴급도 |
|---|---|---|
| `visitor_new_conversation` | 방문자 첫 턴 완료 | 1 |
| `visitor_message` | 방문자가 `leave_message` 카드 제출 | 3 |
| `meeting_request` | `meeting_propose` 제출 | 3 |
| `contact_share` | 방문자가 연락처 남김 | 2 |
| `question_unanswered` | 비서가 모른다고 답함 | 1 |
| `credits_low` | 잔액 경고선 | 2 |
| `integration_error` | 연동 토큰 만료/실패 | 2 |
| `agent_model_fallback` | 모델 비활성 폴백 | 2 |
| `digest_daily` | 매일 오너 TZ 09:00 | 0 |

## 채널 (`notification_channels`)
| kind | config | 발송 |
|---|---|---|
| `email` | `{to}` (기본 계정 이메일) | SMTP(관리자 설정) — HTML+텍스트 템플릿(Jinja2), 언어=오너 locale |
| `telegram` | `{chat_id}` | 관리자 봇 토큰(`system_settings.telegram.bot_token`) — 오너가 봇에 `/start <연결코드>` 보내면 `chat_id` 매핑(워커가 getUpdates 폴링 또는 웹훅 `POST /api/notifications/telegram/webhook`) |
| `slack` | `{webhook_url}` | Incoming Webhook, Block Kit |
| `discord` | `{webhook_url}` | 임베드 |
| `webhook` | `{url, secret}` | JSON POST, `X-MFSG-Signature: sha256=HMAC(secret, body)`, 재시도 3회 |

## 규칙 (`notification_rules`)
이벤트 × 채널 배열 × `min_urgency` × `quiet_hours{start,end,tz}`(방해금지엔 digest 로 묶음). 에이전트별 오버라이드 가능. 기본 규칙(가입 시 생성): 이메일로 `visitor_message, meeting_request, credits_low, integration_error`, 일간 다이제스트 on.

## 파이프라인
```
턴 완료/카드 제출 → jobs(kind=notify.evaluate, payload={event, owner_id, agent_id, ref})
 워커: 규칙 조회 → 채널별 notifications(pending) 생성 → jobs(kind=notify.send, id)
 워커: 채널 어댑터 send() → sent/failed(재시도 지수 백오프 3회 → failed + 오너 콘솔 표시)
```
집계(폭주 방지): 같은 방문자 대화의 `visitor_new_conversation` 는 대화당 1회, `question_unanswered` 는 10분 윈도 묶음.

## 다이제스트
워커 잡 `digest.daily`(사용자별 로컬 09:00): 지난 24h 방문자 대화 수·남긴 메시지·미팅 요청·미답변 질문·크레딧 사용·인맥 제안 대기. 내용 없으면 건너뜀.

## 알림 본문 규약
제목 `[비서이름] 방문자 메시지: {요약 40자}` / 본문: 방문자 표시명·시각·요약(비서가 생성한 1문장)·원문(≤ 800자)·[인박스 열기] 딥링크(`/app/inbox?item=`)·수신 거부 링크(이메일).

## 어댑터 인터페이스
```python
class NotificationChannel(Protocol):
    kind: str
    async def send(self, config: dict, message: NotificationMessage) -> SendResult
    async def verify(self, config: dict) -> VerifyResult     # 테스트 발송
```
레지스트리 `services/notifications/channels/{email,telegram,slack,discord,webhook}.py`. executor 의 `channels.build_send_message_channel` 은 이식하지 않고 얇게 재작성(의존 축소).

## API
```
GET/POST/PATCH/DELETE /api/notifications/channels · POST /api/notifications/channels/{id}/test
GET/POST/PATCH/DELETE /api/notifications/rules
GET /api/notifications/log?page=
POST /api/notifications/telegram/link  → {code}  (봇 /start 코드)
POST /api/notifications/telegram/webhook (공개, 봇 시크릿 헤더 검증)
GET  /api/notifications/unsubscribe?token= (공개, 이메일)
```
