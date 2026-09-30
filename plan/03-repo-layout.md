# 03 · 저장소 구조 · 규약 · 릴리스

## 저장소

GitHub `CocoRoF/my-first-secretary-geny` (공개, Apache-2.0). 로컬 작업 경로 `/home/workspace/mfsg`.
단일 모노레포. 브랜치 `main` 하나(배포 = main). 태그 `vX.Y.Z`.

```
mfsg/
├── plan/                    # 이 설계 문서 묶음 (정본)
├── backend/                 # FastAPI + 파이프라인 + 워커 (Python 3.12, uv)
│   ├── pyproject.toml
│   ├── alembic/             # 마이그레이션
│   ├── src/mfsg/
│   │   ├── main.py          # app factory, lifespan, 라우터 등록
│   │   ├── config.py        # Settings(pydantic-settings) — env 부트스트랩만
│   │   ├── db/              # engine, session, base, pgvector 타입
│   │   ├── models/          # SQLAlchemy 모델 (도메인별 파일)
│   │   ├── schemas/         # pydantic 요청/응답
│   │   ├── api/             # 라우터: auth, users, agents, chat, public, knowledge, network,
│   │   │                    #   integrations, inbox, credits, notifications, admin, health
│   │   ├── core/            # security(jwt/argon2/fernet), deps, errors, ratelimit, ids
│   │   ├── services/        # 도메인 서비스 (accounts, agents, share_links, knowledge, network,
│   │   │                    #   integrations/google, credits, notifications, settings, providers)
│   │   ├── pipeline/        # 하네스: manifest, prompt sections, tools, runner, events, audience
│   │   ├── memory/          # 볼트 관리, 사실 원장, 증류
│   │   ├── providers/       # llm/ stt/ tts/ embedding/ 어댑터 + 카탈로그 + 단가
│   │   ├── worker/          # 잡 큐(PG SKIP LOCKED), 핸들러(index, notify, sync, digest)
│   │   └── utils/
│   ├── tests/               # pytest (unit · api · pipeline contract · e2e-lite)
│   ├── Dockerfile
│   └── entrypoint.sh        # alembic upgrade head → uvicorn
├── frontend/                # Next.js 15 App Router, TS, Tailwind v4, zustand (pnpm)
│   ├── app/
│   │   ├── (marketing)/     # / 랜딩, /login, /signup
│   │   ├── (owner)/app/...  # 오너 콘솔
│   │   ├── (admin)/admin/...# 관리자 콘솔
│   │   ├── [code]/          # 공개 채팅 (모바일 우선)
│   │   └── api/             # 없음 — 모든 API 는 backend. (라우트 핸들러는 헬스 프록시만)
│   ├── components/          # ui/ (프리미티브), chat/, agent/, network/, admin/, layout/
│   ├── lib/                 # api client, sse client, auth, i18n, utils
│   ├── stores/              # zustand
│   ├── public/              # manifest.webmanifest, icons
│   ├── Dockerfile
│   └── next.config.ts       # output: 'standalone'
├── deploy/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   ├── .env.example
│   ├── nginx/nginx.conf
│   └── scripts/ (backup.sh, remote-deploy.sh, tunnel-add.sh)
├── scripts/                 # 개발 유틸 (seed, e2e)
├── README.md · README_ko.md · LICENSE · NOTICE · CHANGELOG.md
└── .github/workflows/ci.yml # backend ruff+pytest, frontend lint+typecheck+build, compose config
```

## 규약

### Python (backend)
- Python 3.12, `uv` 로 의존성/락(`uv.lock` 커밋). 린트 `ruff`(select/ignore 고정), 타입 `mypy` 는 `pipeline/`·`core/` 만 strict.
- SQLAlchemy 2.x async + asyncpg. 모든 ID 는 `uuid7`(시간순 정렬) 문자열 → PG `uuid`.
- 라우터는 얇게: 검증(pydantic) → 서비스 호출 → 응답. 비즈니스 규칙은 `services/`.
- 예외: `MfsgError(code, status, message_ko, message_en)` 단일 계층. API 에러 응답 `{error:{code,message}}`.
- 시간은 전부 UTC aware `datetime`. 표시 TZ 는 사용자 설정.
- 비밀은 `SecretBox`(Fernet) 로 at-rest 암호화; 로그에 절대 출력 금지(`redact()` 헬퍼).
- 이벤트루프 규칙: 동기 I/O·CPU 작업은 `asyncio.to_thread`. (Geny 의 루프 블록 인시던트 3건 교훈.)
- `OPENBLAS_NUM_THREADS=1` 등 BLAS 스레드 1 고정을 `main.py` 최상단에서(numpy import 전).

### TypeScript (frontend)
- Next.js 15.x App Router, React 19, TypeScript strict, Tailwind v4, `lucide-react` 아이콘.
- 상태: zustand(세션·채팅), 서버 상태는 `@tanstack/react-query`.
- 컴포넌트 프리미티브는 `components/ui`(shadcn 스타일, 직접 작성 — 의존 최소).
- i18n: ko 기본, en 보조. `lib/i18n.ts` 딕셔너리 + `useT()`. 방문자 UI 는 브라우저 언어 자동.
- API 호출은 `lib/api.ts` 한 곳. 서버 컴포넌트는 `INTERNAL_API_URL`(컨테이너 내부), 클라이언트는 same-origin `/api`.
  (Geny standalone `API_URL` 함정: 빌드타임 인라인 금지 → 런타임 env 만.)
- 접근성: 모든 인터랙티브 요소 aria-label, 포커스 링, `prefers-reduced-motion` 존중.

### 커밋/릴리스
- Conventional Commits(`feat:`, `fix:`, `docs:`, `chore:`…). 문서 변경도 커밋.
- `CHANGELOG.md` Keep-a-Changelog. 마일스톤 완료마다 태그 `v0.M.0`.
- CI 통과 없이 main 머지 금지(자기 저장소이므로 규율로).

## 버전 정책
- backend/frontend 는 동일 버전(모노레포 단일 버전 `VERSION` 파일).
- 외부 엔진 `geny-executor`, `geny-memory-adaptor` 는 pyproject 에 **정확 핀**(`==`).
