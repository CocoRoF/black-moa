# 04 · 데이터 모델 (PostgreSQL 16 + pgvector + pg_trgm + citext)

관례: PK `id uuid`(uuid7), `created_at/updated_at timestamptz` 기본, 소유 테이블은 `owner_id uuid NOT NULL REFERENCES users ON DELETE CASCADE` + 인덱스. JSON 은 `jsonb`. 열거형은 `text` + CHECK(마이그레이션 단순화). 벡터는 `vector(1536)`(OpenAI text-embedding-3-small 기본; 차원은 `system_settings.embedding_dim` 과 함께 마이그레이션으로 변경).

## 계정·권한
```
users(id, email citext UNIQUE, email_verified_at, password_hash, display_name, avatar_url, locale, timezone,
      role CHECK(admin|user), status CHECK(active|suspended|deleted), plan_id → plans, onboarding_state jsonb,
      last_login_at, created_at, updated_at)
auth_identities(id, user_id, provider CHECK(google), subject, email, raw_profile jsonb, UNIQUE(provider,subject))
auth_sessions(id, user_id, family_id uuid, refresh_hash text UNIQUE, ua, ip, expires_at, revoked_at, replaced_by, created_at)
password_resets(id, user_id, token_hash, expires_at, used_at)
email_verifications(id, user_id, code_hash, expires_at, used_at)
invites(id, code UNIQUE, created_by, max_uses, used, expires_at)
audit_logs(id, actor_id null, actor_kind CHECK(user|admin|system|visitor), action, target_type, target_id, ip, ua, meta jsonb, created_at)
```

## 시스템 설정 · 프로바이더 · 카탈로그 (관리자)
```
system_settings(key text PK, value jsonb, is_secret bool, updated_by, updated_at)
   -- 예: providers.anthropic.api_key(secret, Fernet), providers.openai.api_key, providers.google.api_key,
   --     providers.claude_code.{auth_mode, credentials_json(secret), status}, providers.elevenlabs.api_key,
   --     embedding.{provider, model, dim}, stt.{provider, model}, tts.{provider, model, default_voice},
   --     google_oauth.{client_id, client_secret(secret)}, smtp.{host,port,user,password(secret),from},
   --     signup.{mode, require_email_verification}, credits.{usd_per_credit, default_grant, low_watermark},
   --     memory.{distill_model, distill_enabled}, public.{turnstile_site_key, turnstile_secret(secret)},
   --     branding.{service_name, logo_url}
model_catalog(id, provider CHECK(claude_code|anthropic|openai|gemini), model_id text, display_name, cli_alias,
      context_window int, max_output int, supports_thinking bool, supports_vision bool,
      credit_per_1k_input numeric(12,4), credit_per_1k_output numeric(12,4), credit_per_1k_cache_read numeric(12,4),
      enabled bool, is_default bool, sort_order int, UNIQUE(provider, model_id))
plans(id, code UNIQUE(free|pro|custom), name, monthly_credits int, max_agents int, max_share_links int,
      max_knowledge_mb int, max_network_nodes int, turn_cost_cap_credits int, daily_credit_cap int,
      visitor_turns_per_day int, features jsonb, is_default bool)
```

## 에이전트
```
agents(id, owner_id, name, handle citext UNIQUE null, avatar_url, status CHECK(active|paused|archived),
       provider, model_id, persona jsonb, custom_instructions text, capabilities jsonb,
       disclosure_policy jsonb, greeting text, suggested_questions text[], language CHECK(auto|ko|en),
       theme jsonb, voice jsonb, visitor_settings jsonb, stats jsonb, created_at, updated_at)
   -- persona: {preset, tone, formality, warmth, humor, verbosity, emoji, catchphrases[], self_reference, extra}
   -- capabilities: {web_search, knowledge, network, google_email, google_calendar, voice, leave_message, meeting_request, file_share}
   -- disclosure_policy: {profile_fields:{field: public|on_request|private}, topics_private[], topics_public[], allow_contact_share, calendar_mode: none|busy_only, network_default: private|on_request}
   -- visitor_settings: {continue_conversations, retention_days, rate_per_minute, require_turnstile, collect_identity: never|ask|require}
share_links(id, owner_id, agent_id, code citext UNIQUE, label, status CHECK(active|paused|expired|revoked),
       expires_at, max_conversations, conversation_count int, turn_count int, last_visit_at, settings jsonb, created_at)
```

## 오너 정보 · 사실 · 지식
```
owner_profiles(owner_id PK, data jsonb, visibility jsonb, updated_at)
   -- data: {full_name, preferred_name, title, company, bio, location, languages[], links{}, contact{email, phone}, availability_window{tz, weekly[]}, contact_rules, extra{}}
facts(id, owner_id, agent_id null, subject, predicate, object text, kind CHECK(identity|preference|relationship|commitment|context|knowledge),
      confidence real, visibility CHECK(public|on_request|private|visitor_private), visitor_id null,
      source_turn_id null, superseded_by null, status CHECK(active|superseded|rejected), embedding vector, created_at, updated_at)
   INDEX (owner_id, status), GIN trgm(subject||predicate||object)
knowledge_documents(id, owner_id, agent_id null, kind CHECK(file|note|faq|url), title, filename, mime, size_bytes,
      storage_path, sha256, status CHECK(processing|ready|failed), error, visibility CHECK(public|private),
      chunk_count int, embedding_model, meta jsonb, created_at, updated_at)
knowledge_chunks(id, document_id → knowledge_documents CASCADE, owner_id, ordinal int, text, tokens int, heading, page int,
      embedding vector, tsv tsvector GENERATED)  INDEX hnsw(embedding vector_cosine_ops), GIN(tsv)
knowledge_faqs(id, owner_id, question, answer, visibility, embedding vector)
```

## 인맥 그래프 (plan/10)
```
network_nodes(id, owner_id, kind, name, aliases text[], attrs jsonb, tags text[], visibility, importance int,
      last_contact_at, source, external_ref text, embedding vector, created_at, updated_at)
   INDEX GIN trgm(name), (owner_id, kind), UNIQUE(owner_id, source, external_ref) WHERE external_ref IS NOT NULL
network_edges(id, owner_id, src_id, dst_id, rel, direction, strength real, since date, until date, attrs jsonb, visibility, source, created_at)
   UNIQUE(owner_id, src_id, dst_id, rel)
network_interactions(id, owner_id, node_id, kind, at, summary, ref jsonb)
network_proposals(id, owner_id, agent_id, kind, payload jsonb, confidence real, source_turn_id, status, created_at, decided_at)
```

## 연동 (plan/11)
```
connections(id, owner_id, provider, account_label, scopes text[], access_token_enc, refresh_token_enc, token_expires_at,
      status, last_sync_at, sync_cursor jsonb, settings jsonb, error text, created_at, updated_at)  UNIQUE(owner_id, provider, account_label)
integration_emails(id, owner_id, connection_id, ext_id, thread_id, from_addr, to_addrs text[], subject, snippet,
      received_at, labels text[], summary, importance int, embedding vector, UNIQUE(connection_id, ext_id))
integration_events(id, owner_id, connection_id, ext_id, title, start_at, end_at, all_day, location, attendees jsonb,
      status, description_summary, UNIQUE(connection_id, ext_id))
```

## 대화 · 턴 · 이벤트
```
visitors(id, owner_id, agent_id, share_link_id, token_hash, display_name, email, note, matched_node_id null,
      first_seen_at, last_seen_at, turn_count int, blocked bool, meta jsonb)
conversations(id, owner_id, agent_id, audience CHECK(owner|visitor), visitor_id null, share_link_id null, title,
      status CHECK(active|archived), summary text, last_message_at, message_count int, unread_owner bool, created_at)
messages(id, conversation_id, owner_id, role CHECK(user|assistant|system|card), content text, content_blocks jsonb,
      attachments jsonb, turn_id null, created_at)  INDEX(conversation_id, created_at)
turns(id, conversation_id, owner_id, agent_id, audience, status CHECK(running|completed|failed|cancelled),
      provider, model_id, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd numeric(12,6),
      credits numeric(14,4), duration_ms, ttft_ms, stop_reason, error_code, error_message, tool_call_count, started_at, ended_at)
turn_events(turn_id, seq int, type text, data jsonb, at timestamptz, PRIMARY KEY(turn_id, seq))
tool_spans(id, turn_id, owner_id, name, input jsonb, output_preview text, is_error bool, duration_ms, started_at)
```

## 인박스 (방문자가 남긴 것)
```
inbox_items(id, owner_id, agent_id, conversation_id, visitor_id, kind CHECK(message|meeting_request|contact_share|question_unanswered),
      payload jsonb, status CHECK(new|read|replied|archived|accepted|declined), owner_reply text, created_at, updated_at)
```

## 크레딧 (plan/15)
```
credit_ledger(id, owner_id, delta numeric(14,4), balance_after numeric(14,4), kind CHECK(grant|monthly_grant|purchase|turn|integration|refund|adjust|expire),
      ref_type, ref_id, note, created_by null, created_at)  INDEX(owner_id, created_at DESC)
credit_balances(owner_id PK, balance numeric(14,4), updated_at)     -- 캐시(원장이 정본, 트랜잭션 내 갱신)
usage_events(id, owner_id, agent_id, turn_id null, kind CHECK(llm|stt|tts|embedding|summary), provider, model_id,
      input_tokens, output_tokens, cache_read_tokens, units numeric, cost_usd numeric(12,6), credits numeric(14,4), created_at)
usage_daily(owner_id, day date, credits numeric, turns int, visitor_turns int, PRIMARY KEY(owner_id, day))
purchases(id, owner_id, provider CHECK(manual|stripe), external_id, credits, amount_cents, currency, status, created_at)
```

## 알림 (plan/16)
```
notification_channels(id, owner_id, kind CHECK(email|webhook|telegram|slack|discord), config_enc, label, enabled, verified_at, last_error, created_at)
notification_rules(id, owner_id, agent_id null, event CHECK(visitor_new_conversation|visitor_message|meeting_request|question_unanswered|credits_low|digest_daily|integration_error),
      channel_ids uuid[], enabled, quiet_hours jsonb, min_urgency int)
notifications(id, owner_id, event, payload jsonb, channel_id, status CHECK(pending|sent|failed|skipped), error, attempts int, created_at, sent_at)
```

## 워커
```
jobs(id, kind, payload jsonb, status CHECK(queued|running|done|failed|dead), priority int, run_at, attempts int, max_attempts int,
     last_error, locked_by, locked_at, created_at, finished_at)  INDEX(status, run_at, priority)
worker_heartbeats(worker_id PK, last_seen_at, info jsonb)
```

## 업로드
```
uploads(id, owner_id, kind CHECK(avatar|attachment|knowledge|export), filename, mime, size_bytes, storage_path, sha256, created_at)
```

## 마이그레이션
Alembic, 초기 리비전 1개(`0001_initial`), 이후 기능별 리비전. 확장 생성 `CREATE EXTENSION IF NOT EXISTS vector, pg_trgm, citext` 는 0001 에서. 컨테이너 entrypoint 가 `alembic upgrade head` 실행(advisory lock 으로 동시 기동 보호).

## 보존·삭제 연쇄
users 삭제 → 전부 CASCADE. agents 삭제 → conversations/turns/inbox/share_links/visitors CASCADE, 볼트 디렉터리는 서비스 계층에서 삭제. 방문자 보존 스윕은 `visitor_settings.retention_days` 기준(워커 `retention.sweep`).
