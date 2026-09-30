# 38. 비서 간 대화 (Relay) — 설계와 규칙

2026-09-13. 한 사람의 비서가 다른 사람의 비서에게 **공개 링크를 통해** 말을 걸고, 두 비서가 사람 대신 몇 마디를 주고받는 기능이다.
원칙: **비서가 사람에게 말할 때와 완전히 같은 길**을 쓴다. 상대 비서는 "방문자"이고, 내 비서가 밖에 나가 말할 때도 "방문자에게 말하는 규칙"(공개 사다리)을 따른다. 새 프롬프트 경로·새 과금 경로를 만들지 않는다.

## 0. 한 줄 요약

| 항목 | 결정 |
|---|---|
| 시작 | 오너가 자기 비서에게 시킴(`secretary_ask` 도구) 또는 [대화 기록]의 "비서에게 문의 보내기". 대상은 **활성 공개 링크 코드/URL** |
| 실행 | 발신 비서 A(오너 X) ↔ 수신 비서 B(오너 Y). 양쪽 모두 `audience=visitor` 대화 — B 쪽에서는 A가 방문자, A 쪽에서는 B가 방문자 |
| 루프 | A 개시문 → B 턴 → A 턴 → B 턴 … 각 턴이 끝나면(`_finalize`) 상대 턴을 잡(`relay.hop`)으로 예약. 잡은 백엔드 내부 엔드포인트로 턴을 시작 |
| 멈춤 | ① 어느 쪽이든 `relay_close` 도구 호출(요약 남김) ② 최대 메시지 수(기본 8, 상한 20) ③ 양쪽 각각 크레딧 상한(기본 40) ④ 짧은 인사말 핑퐁 감지 ⑤ 링크 회수·거부·잔액 0 ⑥ 정체 10분·만료 24시간 ⑦ 오너의 [중단] |
| 표시 | 대화 `kind=agent`, 방문자 `kind=agent`(어느 비서인지 `peer_agent_id`), 릴레이 원장(`agent_relays`, `agent_relay_messages`)에 전 메시지 보존, 화면에는 [비서] 태그 |
| 과금 | 각 턴은 그 비서 오너의 크레딧(방문자 턴과 동일). 릴레이 턴은 기억 증류를 하지 않는다(비용 절감) |
| 거부 | 공개 링크 설정 `allow_agents`(기본 켬)와 `agent_turns_per_day`(기본 20). 꺼져 있으면 개시 즉시 `refused` |

## 1. 데이터 (0035)

```
agent_relays: id, status(open|closed), initiator_{agent,owner,conversation,visitor}_id, target_{agent,owner,link,conversation,visitor}_id,
  origin_conversation_id, origin_turn_id, purpose, opener, max_messages, credit_cap, message_count,
  hop_pending(initiator|target|null), pending_since, in_flight_turn_id, attempts, close_requested_by, summary,
  closed_at, closed_by(initiator|target|system|owner), close_reason, last_message_at, created_at, updated_at
agent_relay_messages: id, relay_id, seq, side, agent_id, kind(open|reply|close|system), content, turn_id, created_at
conversations += kind('human'|'agent'), relay_id
visitors += kind('human'|'agent'), peer_agent_id
share_links.settings += {allow_agents: bool, agent_turns_per_day: int}
```

## 2. 한 번의 홉(hop)

1. `relay.hop {relay_id}` 잡 → 워커가 `POST /internal/relay/hop`(HMAC 헤더) → API 프로세스의 `relay.run_hop`.
2. 가드: 열림·hop_pending·수신 비서 active·수신 오너 잔액·(수신=B면) 링크 active + allow_agents + 일일 상한·메시지 수·크레딧 상한. 막히면 `close(reason)`.
3. `start_turn(audience=visitor, text=마지막 상대 메시지, visitor=상대 비서 방문자행)` → `launch_turn`. 상대 메시지는 이 턴의 user 메시지로 기록된다.
4. `_finalize` 끝에서 `relay.after_turn`: 답을 원장에 기록, 닫힘 요청·핑퐁·상한 판정, 아니면 `hop_pending`을 반대편으로 두고 다음 잡 예약(지연 `relay.hop_delay_s`).
5. 닫힐 때: 마지막 말은 상대 대화에 user 메시지로만 넣고(턴 없음), 두 오너의 인박스(`relay_result` / `relay_visit`)와 시작한 오너의 원래 채팅에 `relay_result` 카드.

## 3. 프롬프트

- 방문자 규칙(5장)은 그대로. 방문자 소개 노트에 "다른 회원의 비서(자동 응답)"가 들어간다.
- `relay` 블록(volatile, 릴레이 대화에서만): 누구의 비서와 무엇 때문에 이야기 중인지, n/최대 메시지, 남은 수, **닫는 규칙**("목적이 해결됐거나 상대가 인사로 마쳤으면 `relay_close`; 인사말만 되돌려 보내지 말 것; 약속은 제안만, 확정은 오너"), 마지막 메시지 예고.
- 도구: `secretary_ask`(오너 대화 전용, 개시), `relay_close`(릴레이 대화 전용, 요약과 함께 종료 요청).

## 4. API

```
POST /api/agents/{id}/relays        {target, message, purpose?, max_messages?, credit_cap?}
GET  /api/relays?agent_id=&role=    내가 어느 쪽이든 관여한 릴레이
GET  /api/relays/{id}               원장 전체(양쪽 메시지)
POST /api/relays/{id}/stop          오너 중단(진행 중 턴 취소)
PATCH /api/links/{id}               settings.allow_agents / agent_turns_per_day
GET  /api/agents/{id}/conversations?kind=agent
POST /internal/relay/hop            워커 전용
```

## 5. 안전·비용 규칙(요약)

- 개시: 오너 잔액 > 0, 하루 개시 상한(`relay.threads_per_day`=10), 자기 비서끼리 금지, 상대 링크 active + allow_agents + 상대 오너 잔액 > 0.
- 개시문은 발신 오너의 **비공개 리터럴을 지운 뒤** 보낸다(방문자에게 말할 때와 같은 규칙).
- 홉마다 상한 재검사. 상대 링크가 도중에 회수되면 `link_closed`.
- 릴레이 턴은 `memory.distill`을 건너뛴다. 관계(relationship) 카운터는 오너 턴만 세므로 영향 없음.

함정(2026-09-13 배포 때): `/internal/relay/hop` 은 인증 게이트(`core/auth_middleware.PUBLIC_PREFIXES`)에 넣어야 워커의 HMAC 요청이 핸들러까지 간다 — 빠뜨리면 잡은 "done" 인데 결과가 401 이고 릴레이는 pending 으로 멈춘다(sweep 이 10분 뒤 재시도).
실측(2026-09-13, haiku·CLI 양쪽): 홉 하나 10~20초, 4메시지 릴레이 약 40초. 상대 비서가 `relay_close` 를 스스로 호출해 요약을 남겼고, 오너 채팅에서 자연어 지시만으로 `secretary_ask` 가 호출됐다.

## 5-1. 불변식: 양쪽 대화 내역 = 원장 (2026-09-13 보강)

상대 메시지는 보통 "그쪽 턴이 시작될 때" 그쪽 대화의 user 메시지로 들어간다. 턴이 시작되기 전에 닫히면(링크 회수·크레딧 상한·오너 중단·정체·만료) 원장에만 남는 구멍이 있었다.
`agent_relays.delivered_seq_{initiator,target}`(0036)로 각 쪽 대화가 이미 담은 원장 seq 를 추적하고, **어떤 사유로 닫히든 `_close` 가 `_sync_transcripts` 로 빠진 상대 메시지를 그쪽 대화에 채워 넣는다.** 닫힌 뒤 끝난 턴(오너 중단으로 취소된 부분 답)도 원장에 `partial` 로 남기고 상대에게 미러링한다.
테스트 `_assert_transcripts` 가 상한·도구 종료·링크 회수·일일 예산·오너 중단(대기 중/진행 중)·만료·크레딧 상한 시나리오마다 "A 대화 = 원장(A 는 assistant, B 는 user)", "B 대화 = 원장(반대)" 를 메시지 단위로 대조한다. 원장과 전달 텍스트는 2000자(방문자 턴 입력 상한)로 맞춘다.

## 6. 실확인 항목

1. 링크 설정에서 "다른 비서의 문의" 끄기 → 개시가 `refused`로 즉시 닫히고 턴 0.
2. 켠 상태로 개시 → 홉이 번갈아 진행, [대화 기록]에 양쪽 대화가 [비서] 태그로 보이고 원장에 전 메시지.
3. 최대 메시지 4로 개시 → 4개에서 닫힘, 두 오너 인박스에 결과, 시작한 채팅에 결과 카드.
4. 개시문에 `relay_close` 를 유도하는 문장 → 상대가 첫 답에서 닫음.
5. [중단] → 진행 중 턴 취소, 닫힘 사유 owner.
