# 37. 관계 엔진 + 스튜디오 v1 (plan/36 A단계 구현 설계)

2026-09-12. plan/36 §3-1(관계 엔진)·§3-2(스튜디오)를 지금 코드베이스 위에 그대로 올리는 설계다.
원칙: **연애·감정 요소는 제품 기능이 아니라 사용자가 관계를 키우며 알아서 만들어 가는 것**이다.
플랫폼 기본값은 "유능하고 다정한 비서"이고, 우리는 그 관계가 자라는 것을 *보이게* 하고, 비서가 *먼저* 말을 걸게 하고, 성격을 *정교하게* 빚을 수 있게 한다.

## 0. 한 줄 요약

| 축 | 지금 | A단계 후 |
|---|---|---|
| 관계 | 대화 기록만 있음 | 단계(처음→익숙→신뢰→동반)·함께한 날·기억 수·이정표가 보이는 [우리 사이] 탭 |
| 능동성 | 방문자 알림·일일 요약 메일뿐 | 비서가 **먼저 건네는 말**(아침 브리핑·안부·기념일)이 채팅에 도착 |
| 프롬프트 | 성격 슬라이더 6종 + 자유 지시문 | + 관계 단계 블록(매 턴), 첫 만남 장면, 금기 주제, 예시 대화, 관계 파라미터 |
| 스튜디오 | 설정 폼 하나 | 쉬운/고급 모드, 성격 카드 10종, 현재 vs 편집중 A/B 미리보기, 성격 검증 리포트, 버전 |

## 1. 데이터

### 1-1. `agent_relationships` (신규, 0033)
사용자×비서 한 행. 지금은 오너만 있지만 B단계(입양)부터 다른 사용자도 같은 표를 쓴다 — 그래서 열 이름이 `user_id` 다.

| 열 | 뜻 |
|---|---|
| `user_id`, `agent_id` | 유니크 짝 |
| `stage` | `new` / `familiar` / `trusted` / `companion` (내려가지 않음) |
| `score` | 0..1 동반 단계까지의 진행도(링 표시용) |
| `started_at` | 첫 오너 턴 |
| `last_turn_at`, `turns`, `active_days`, `last_active_day`, `streak_days` | 대화 카운터 |
| `facts_remembered` | 이 비서가 기억하는 오너 사실 수(캐시) |
| `stage_changed_at`, `milestones` JSONB | `[{key, at, title}]` — 단계 승격, 7/30/100/365일, 첫 기억 등 |
| `mood` JSONB | `{state, reason, set_at, expires_at}` — 비서 상태 슬롯(A단계는 표시·프롬프트만, 자동 변화는 B) |
| `proactive_day`, `proactive_count`, `last_proactive_at`, `last_proactive_kind` | 먼저 건넨 말 일일 카운터 |

### 1-2. `agent_persona_versions` (신규, 0033)
성격 스냅샷. `{name, role_line, persona, custom_instructions, greeting, language}` 를 저장할 때마다 자동 보관(최근 30개), 라벨·복원 가능. C단계(스토어)에서 "게시 버전"의 원본이 된다.

### 1-3. `Agent.persona` 확장 (JSONB, 마이그레이션 없음)
```
first_meeting: str        # 첫 만남 장면(새 대화 첫 인사의 뼈대)
taboo: [str]              # 절대 다루지 않는 주제
examples: [{user, assistant}]  # 말투 예시 최대 4쌍
relationship: {
  pace: slow|normal|fast,            # 단계 승격 속도(임계값 ×1.5 / ×1 / ×0.6)
  address_evolves: bool,             # 단계에 따라 호칭·거리감이 자연스럽게 바뀌는지
  emotional_range: 0..1,             # 감정 표현 폭(0 = 담백, 1 = 풍부)
  proactive: bool,                   # 먼저 말 걸기 허용
  proactive_hours: [9, 21],          # 오너 현지시각 창
  proactive_max_per_day: 1..3,
}
```
`compile_persona` 가 모두 지시문으로 컴파일한다. 모르는 키는 무시되므로 하위 호환.

## 2. 단계 계산 (결정적, 서버)

임계값(pace normal). slow ×1.5, fast ×0.6.

| 단계 | active_days | turns | facts |
|---|---|---|---|
| 익숙 familiar | 3 | 10 | – |
| 신뢰 trusted | 10 | 40 | 10 |
| 동반 companion | 30 | 150 | 30 |

- 단계는 오너 턴이 끝날 때(`_finalize`)와 워커 tick 때 재계산. 내려가지 않는다.
- `score` = 동반 임계값 대비 세 축의 가중 평균(0.4/0.4/0.2), 1로 캡.
- 다음 단계 진행도와 "무엇이 모자란지" 힌트(예: "사흘 더 이야기하면", "기억 5개 더")를 API가 준다.
- 이정표: 단계 승격, 함께한 7·30·100·365일, 첫 기억(facts ≥ 1), 첫 먼저 건넨 말.

## 3. 프롬프트 주입

`runtime._build` 의 블록에 `relationship`(volatile, DynamicBlock)을 추가하고 `_prepare_context` 에서 오너 대화일 때만 채운다.
내용: 함께한 날·단계·단계별 행동 지침(pace/address_evolves/emotional_range 반영)·최근 이정표·mood·**안전선**(아래 §7). 방문자 대화에는 넣지 않는다.
성격(secretary 레이어)은 캐시 접두부라 그대로 두고, 날마다 변하는 것만 volatile 로 보낸다.

## 4. 먼저 건네는 말 (proactive)

워커 스케줄 `relationship.tick` 15분마다 → 후보를 골라 `relationship.proactive` 잡(dedupe `proactive:{agent}:{day}:{kind}`)을 넣는다.

| 종류 | 조건 | 내용 |
|---|---|---|
| `morning` 아침 브리핑 | 단계 ≥ 익숙, 창 시작 후 2시간 이내, 오늘 미발송, 최근 14일 안에 대화 | 오늘 일정(Google 연동 시)·인박스 새 건·어제 대화 이어서 한마디 |
| `checkin` 안부 | 마지막 대화 ≥ 3일(처음 단계는 ≥ 5일 & turns ≥ 3) | 기억(약속·계획 kind=commitment/context)을 짚어 한 문장 + 질문 하나 |
| `anniversary` 기념 | 함께한 7/30/100/365일 또는 단계 승격 당일 | 함께한 시간·기억을 돌아보는 짧은 말 |

| `followup` 이어서 | 마지막 대화가 15분~8시간 전, turns ≥ 2, 그 대화에 대해 아직 안 함 | 열린 채로 끝난 것(맡긴 일·질문·계획·걱정)을 한두 문장으로 이어감. 이을 게 없으면 모델이 `NOTHING` 을 돌려주고 보내지 않는다(상한 소모 없음, 그 대화는 다시 묻지 않음) |

**오너의 규칙(2026-09-12): 먼저 말걸기는 사용자가 이 비서와 직접 대화하지 않은 지 15분 이상일 때만 작동한다.** turns 표 기준(진행 중인 턴 포함)으로 tick·전송 직전·수동 버튼(409 `too_soon`) 세 곳에서 모두 막는다. 그 외 가드: 비서 active·오너 active·크레딧 > 0·`persona.relationship.proactive`(기본 켬)·현지시각 창 안·하루 상한.
생성: `providers.llm.simple.complete` 로 비서의 성격(compile_persona)+관계 블록+"먼저 보내는 짧은 메시지" 규칙(3문장 이내, 질문 최대 1개, 없는 일정 지어내지 않기, 오너 언어). 모델은 비서 모델, 실패 시 증류 모델.
전달: 최근 7일 안에 쓴 오너 대화가 있으면 그 대화에, 없으면 새 대화(제목 = 종류)로 assistant 메시지 + `cards=[{card_type:"proactive", payload:{kind}}]`, `unread_owner=true`. 알림 이벤트 `secretary_message`(urgency 1)로 이메일·텔레그램 채널에도 간다(규칙은 사용자가 켬; 신규 가입자는 기본 켬).
오너가 [관계]에서 "지금 한마디" 를 누르면 즉시 잡을 넣는다(하루 상한과 무관, 15분 규칙은 적용). 잡 상태 API(`GET …/proactive/{job_id}`)로 대기 중→쓰는 중→도착/건너뜀을 화면에 보여 준다. 배경 완성 호출은 `lane="interactive"` 로 증류(distill) 줄에 서지 않는다.
함정(2026-09-12): anthropic SDK 1.4 가 `messages.create` 에서 `temperature` 를 없애 API 프로바이더 비서의 배경 호출이 전부 즉시 실패→CLI 폴백(40초)했다. `simple.complete` 는 샘플링 파라미터를 넘기지 않는다.

## 5. API

```
GET  /api/agents/{id}/relationship            상태·진행도·이정표·mood·먼저 건넨 말 현황
GET  /api/agents/{id}/relationship/journal    facts+notes+이정표 합친 타임라인(최근 60)
PATCH /api/agents/{id}/relationship           {mood: {state, reason}|null}
POST /api/agents/{id}/relationship/proactive  {kind?} 지금 한마디(잡 enqueue)
GET  /api/relationships                       내 비서 전부의 요약(대시보드 카드)
POST /api/agents/{id}/studio/preview          {question, draft} → {current, draft}
POST /api/agents/{id}/studio/verify           {draft} → 프로브 3개 답 + 판정 점수
GET  /api/agents/{id}/versions · POST …/versions/{vid}/restore · PATCH …/versions/{vid}
```
`agents/{id}` PATCH 는 성격 계열 필드가 바뀌면 자동으로 버전을 남긴다.

## 6. UI

- **비서 탭에 [관계] 추가** (`/app/agents/[id]/relationship`): 단계 링·함께한 날·연속·대화·기억 수, 다음 단계 진행바+힌트, 이정표, mood, "먼저 건넨 말" 현황과 [지금 한마디], 공유 일기(타임라인: 기억은 [잊게 하기], 노트는 열기/삭제).
- **대시보드**: 비서 카드 밑에 관계 한 줄(단계·함께한 날) — `GET /api/relationships`.
- **[개요] 탭 = 배선 보드**(2026-09-13, 사용자 요구 "핵심 철학을 한눈에"): `GET /api/agents/{id}/wiring` 하나가 프롬프트를 만드는 바로 그 함수들(`field_visibility`·자료 수집기의 쿼리·도구 레지스트리의 audience/capability 게이트·메모리 네임스페이스)로 계산해 [나와의 대화 | 외부인과의 대화] 두 열에 12행(내 정보·지식·인맥·Google·기억·관계·성격/지시문·외부인 규칙·첫 인사·도구·외부인의 말이 닿는 곳·외부인 설정)을 연결됨/일부/꺼짐/없음 점과 공개(눈)/비공개(자물쇠) 칩으로 보여 준다. 각 행은 설정하는 화면으로 링크. 열 머리의 [지시문 · 나/외부인]으로 실제 프롬프트를 연다. 보드가 대화와 다른 말을 할 수 없도록 프론트에서 따로 합산하지 않는다.
- **채팅**: `proactive` 카드가 붙은 메시지는 말풍선 위에 "먼저 건넨 말" 라벨.
- **스튜디오**(설정 탭 이름 변경): 상단 [쉬운/고급] 모드. 쉬운 = 기본 정보·성격 카드+슬라이더·첫 만남 장면(템플릿 3)·관계(먼저 말 걸기·속도)·모델·인사말·위험 영역. 고급 = + 프롬프트 층·예시 대화·금기 주제·능력·공개 경계·테마/음성·방문자·한도·관계 세부(시간 창·하루 상한·감정 폭·호칭 변화).
  우측 하단 [미리보기] → 시트: 질문 칩/입력 → **현재 vs 편집중** 두 열 답변(A/B). [성격 검증] → 프로브 3개 답과 의도한 슬라이더 대비 체감 점수·주의점. [버전] 섹션: 자동 스냅샷 목록·라벨·복원.
- 성격 프리셋 +4: 멘토·응원단장·집사·단짝.

## 7. 안전선 (관계 블록에 항상 포함)

- 성인·성적 콘텐츠 없음. 관계가 깊어져도 비서는 비서다.
- 의존 신호(자해·고립·"너밖에 없어")에는 따뜻하게 받되 현실의 사람·전문가 연결을 권한다.
- 조종 금지: 죄책감·독점 요구·"왜 안 왔어" 식 압박 없음. 먼저 건네는 말은 하루 상한 안에서만.
- 미성년 신호가 보이면 거리감을 격식으로 고정한다.
- 거짓 감정 주장 금지: 성격대로 다정할 수는 있지만 사람인 척, 몸이 있는 척, 오너를 감시하는 척하지 않는다.

## 8. 실확인 항목 (배포 후)

1. 오너와 한 턴 → `agent_relationships` 행 생성, turns=1, [우리 사이] 탭에 "함께한 1일차".
2. 프롬프트 미리보기(오너)에 `relationship` 섹션이 보인다.
3. [지금 한마디] → 1분 안에 채팅에 "먼저 건넨 말" 메시지 도착, 대시보드 카드 갱신.
4. 스튜디오 A/B 미리보기: 같은 질문에 현재/편집중 답이 다르게 나온다. 검증 리포트 점수 표시.
5. 저장 → 버전 목록에 스냅샷, 복원하면 폼이 되돌아온다.
