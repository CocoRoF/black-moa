# 15 · 크레딧 · 요금표 · 플랜 · 결제

## 원칙
1. **원장이 정본.** 모든 잔액 변화는 `credit_ledger` 1행(append-only). `credit_balances` 는 캐시이며 같은 트랜잭션에서 갱신.
2. **턴 = 청구 단위.** 턴 종료 시 실제 토큰 사용량 × 카탈로그 단가 → `usage_events` + `credit_ledger(kind=turn)` 을 **하나의 트랜잭션**으로.
3. **오너가 지불.** 방문자 턴도 오너 크레딧. 방문자에겐 비용 개념 노출 없음.
4. **사전검사 → 사후정산.** 턴 시작 전 잔액 > 0 & 일일 상한 미달 & 턴 상한 확인; 사후 실제 사용분 차감(음수 잔액 허용 — 마지막 턴이 넘칠 수 있음, 다음 턴은 402).
5. **크레딧은 정수 감각의 소수**(numeric(14,4)), UI 는 소수점 1자리.

## 단가 계산
```
credits_llm = (in_tok/1000 * cpk_in) + (out_tok/1000 * cpk_out) + (cache_read/1000 * cpk_cache_read) + (cache_write/1000 * cpk_in)
credits_stt = seconds/60 * cpm_stt ;  credits_tts = chars/1000 * cpk_tts ;  credits_embed = tokens/1000 * cpk_embed
```
`cpk_*` 는 `model_catalog` / `system_settings`(audio·embedding). 관리자 시드는 `usd_price × credits_per_usd(기본 1000) × margin(기본 1.0)`; **claude_code 는 API 정가 기준으로 시드하되 관리자가 낮출 수 있음**(구독 실비 0 이므로 운영자 재량 — 제품 요구사항 "저렴").
최소 청구 0.1 크레딧/턴(0 토큰 실패 턴은 0).

## 플랜
| 필드 | free | pro |
|---|---|---|
| monthly_credits | 300 | 5,000 |
| max_agents | 1 | 3 |
| max_share_links | 2 | 10 |
| max_knowledge_mb | 50 | 500 |
| max_network_nodes | 300 | 5,000 |
| turn_cost_cap_credits | 30 | 100 |
| daily_credit_cap | 100 | 1,000 |
| visitor_turns_per_day | 200 | 3,000 |
| features | `{web_search:false, voice:true, google:true}` | 전부 |

월 지급: 워커 잡 `credits.monthly_grant`(매일 00:10 KST, 사용자별 `plan_cycle_anchor` 기준 30일 경과 시 지급, 미사용 잔액 이월 상한 = 월 지급 × 2, 초과분 `expire`).

## 소진 정책
- `balance ≤ low_watermark(기본 월 지급의 10%)` → 알림 `credits_low`(1회/사이클).
- `balance ≤ 0`: 오너 턴 402 `credits_exhausted`(콘솔 충전 안내), 방문자 링크는 **"잠시 쉬는 중" 모드**(LLM 없이 메시지 남기기만 동작), 연동 요약 잡 중단, 색인 잡 중단.
- 관리자 수동 부여로 즉시 복구.

## 충전
- v1: **관리자 수동 부여**(`/admin/users/{id}/credits`) + 오너 콘솔 [충전 요청] 버튼(관리자에게 알림 이메일).
- Stripe 어댑터(`services/billing/stripe.py`): 관리자가 `stripe.secret_key/webhook_secret/price_ids` 설정하면 [충전] 버튼이 Checkout 세션 생성 → 웹훅 `checkout.session.completed` → `purchases` + `credit_ledger(purchase)`. 키 없으면 버튼 비노출. 패키지: 1,000/5,000/20,000 크레딧.

## API
```
GET /api/credits/balance              → {balance, plan, cycle_ends_at, monthly_credits, low}
GET /api/credits/ledger?page=         → 원장
GET /api/credits/usage?from=&to=      → 일별 집계 + 모델별
POST /api/credits/topup-request       → 관리자 알림
POST /api/billing/checkout {package}  → {url}   (stripe 활성 시)
POST /api/billing/webhook              (stripe 서명 검증, 공개 allowlist)
```

## 정산 트랜잭션 (`services/credits/charge_turn`)
```sql
BEGIN;
INSERT usage_events(...);
UPDATE credit_balances SET balance = balance - :credits WHERE owner_id=:o RETURNING balance;  -- 행 잠금
INSERT credit_ledger(delta=-credits, balance_after=..., kind='turn', ref_type='turn', ref_id=turn_id);
UPDATE turns SET credits=:credits, ...;
UPSERT usage_daily;
COMMIT;
```
멱등: `credit_ledger UNIQUE(ref_type, ref_id) WHERE kind='turn'` — 재시도해도 이중 차감 없음.

## 테스트
- 토큰→크레딧 계산 표(캐시 포함), 잔액 0 경계, 동시 턴 2개 경합(행 잠금), 월 지급 이월 상한, 402/휴식 모드 전환, 멱등 차감.
