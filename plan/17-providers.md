# 17 · 프로바이더 (LLM · STT · TTS · 임베딩) — 전부 API, 로컬 서빙 없음

## LLM

| id | 백엔드 | 인증 | 필수 | 비고 |
|---|---|---|---|---|
| `claude_code` | geny-executor `ClaudeCodeCLIClient`(`@anthropic-ai/claude-code` npm, 이미지에 고정 버전 설치) | OAuth 자격 파일(볼륨) 또는 API 키 모드 | **필수·기본** | 구독 기반 → 운영 원가 최소. 도구는 MCP 브릿지 |
| `anthropic` | `AnthropicClient` | API 키 | 선택 | thinking·캐시 |
| `openai` | `OpenAIClient` | API 키 | 선택 | gpt-4.1 계열, o-시리즈(샘플링 파라미터 자동 드롭) |
| `gemini` | `GoogleClient` | API 키 | 선택 | executor 의 provider id 는 `google` — MFSG 표시 id `gemini` ↔ 내부 `google` 매핑 |

미채택: bedrock/vertex(executor 에 없음, v2), codex CLI(도구 개별 차단 불가·read-only 샌드박스 필요, v2), ollama/lmstudio/vllm/custom(로컬 서빙 금지 원칙).

### 카탈로그 시드 (관리자 [시드] 시 생성, 가격 USD/1M tok → 크레딧 단가 계산)
| provider | model_id | cli_alias | ctx | in / out / cache_read (USD/1M) | 기본 |
|---|---|---|---|---|---|
| claude_code | claude-sonnet-4-6 | sonnet | 200k | 3 / 15 / 0.3 | ✓ |
| claude_code | claude-opus-4-7 | opus | 200k | 5 / 25 / 0.5 | |
| claude_code | claude-haiku-4-5-20251001 | haiku | 200k | 1 / 5 / 0.1 | |
| anthropic | 위 3종 | — | | 동일 | |
| openai | gpt-4.1 / gpt-4.1-mini / gpt-4.1-nano | — | 1M | 2/8, 0.4/1.6, 0.1/0.4 | |
| gemini | gemini-2.5-pro / gemini-2.5-flash / gemini-2.5-flash-lite | — | 1M | 1.25/10, 0.3/2.5, 0.1/0.4 | |
(가격은 executor `pricing.py` 표와 동기, 관리자 편집 가능. 최신 모델은 [프로바이더에서 가져오기] 로 추가.)

### 증류·요약용 저비용 모델
`system_settings.memory.distill_model = {provider: claude_code, model: haiku}` 기본. 관리자 변경 가능.

### 자격 번들 빌드 (`providers/llm/credentials.py`)
세션 빌드마다 `system_settings` 에서 복호화해 `CredentialBundle` 생성. claude_code:
- `auth_mode=oauth`(기본): `ProviderCredentials(binary_path, extras={mcp_config, settings(inline), disallow_tools, extra_args:("--tools",""), default_permission_mode:"default", max_budget_usd, timeout_s, workspace_root, bare_mode:False})`, **API 키 미전달**.
- `auth_mode=api_key`: `api_key=anthropic key`, `bare_mode=True`.
- `auth_mode=setup_token`: `env_extras={CLAUDE_CODE_OAUTH_TOKEN}`(관리자가 `claude setup-token` 결과 붙여넣기) — 볼륨 불필요, 서버 친화. **권장 2순위**.
- 규칙(Geny/XGEN 계약): 구독 모드에서 API 키 절대 전달 금지, `--bare` 는 api_key 모드에서만.
- **계정 풀**(`plan/30`): 관리자가 Claude 계정을 여러 개 인증해 두면 세션마다 하나를 임대하고 `env_extras` 의 `HOME`·`CLAUDE_CONFIG_DIR` 을 그 계정 디렉터리로 돌린다(`build_bundle(..., lease=)`). 풀이 비어 있으면 위의 단일 자격 경로 그대로.

### 이미지 요구
`backend/Dockerfile`: `python:3.12-slim` + `nodejs 22`(nodesource) + `npm i -g @anthropic-ai/claude-code@<pinned>` + `DISABLE_AUTOUPDATER=1`. 관리자 [업데이트] 는 v2(이미지 재빌드 배포로 갈음).

## STT (음성 → 텍스트)
| id | 모델 | 비고 |
|---|---|---|
| `openai` | `gpt-4o-mini-transcribe`(기본) / `whisper-1` | multipart `audio/transcriptions`, 언어 힌트 |
| `google` | Speech-to-Text v2 `chirp_2` | 서비스계정 JSON 필요 → v1.5 |
| `elevenlabs` | `scribe_v1` | |
인터페이스 `STTProvider.transcribe(audio_bytes, mime, language) -> {text, duration_s, language}`. 입력 ≤ 25 MB, ≤ 5분. 크레딧: 분당 단가.

## TTS (텍스트 → 음성)
| id | 모델/음성 | 비고 |
|---|---|---|
| `openai` | `gpt-4o-mini-tts`(기본) / `tts-1`, voices alloy·nova·shimmer… | `audio/speech`, mp3/opus 스트리밍 |
| `elevenlabs` | `eleven_multilingual_v2`, 음성 카탈로그 | 한국어 품질 우수, 스트리밍 |
| `google` | Neural2/Wavenet ko-KR | v1.5 |
인터페이스 `TTSProvider.synthesize(text, voice, speed, fmt) -> AsyncIterator[bytes]` + `voices()`. 문장 단위 분할 후 순차 합성(첫 문장 재생 빠르게). 캐시: `sha(text+voice+model)` → `/data/tts-cache`(LRU 2 GB). 크레딧: 1k자 단가.

## 임베딩
| id | 모델 | 차원 |
|---|---|---|
| `openai` | `text-embedding-3-small`(기본) / `-large` | 1536 / 3072 |
| `gemini` | `text-embedding-004` | 768 |
| `voyage` | `voyage-3` | 1024 |
인터페이스 `EmbeddingProvider.embed(texts) -> list[vector]`, 배치·재시도·토큰 상한. 차원 변경 시 마이그레이션 잡(plan/09).

## 공통
- 모든 프로바이더 호출은 `httpx.AsyncClient` 타임아웃(연결 10s/읽기 120s), 429/5xx 지수 백오프 3회, 에러 분류(`auth`, `quota`(크레딧 소진 — 429 이지만 대기로 해결 안 됨), `rate_limit`, `context_limit`, `unknown`) → 사용자 문구 매핑(XGEN `classify_llm_error_message` 이식).
- 키 검증 프로브: Anthropic `GET /v1/models`, OpenAI `GET /v1/models`, Gemini `GET /v1beta/models?key=`, ElevenLabs `GET /v1/user`, Voyage 소형 embed 호출. 결과 캐시 `(provider, sha(key))`.
- 상태 카드: `configured / verified / failed(detail)`.
