# 20 · 배포 (Docker Compose · nginx · Cloudflare 터널 · 운영 서버)

## 목표 상태

```
인터넷 ──https://mfsg.hrletsgo.me──▶ Cloudflare ──터널 <터널>──▶ <서버> :58700 (mfsg-nginx)
                                                                    ├─ /api/*, /health, /v1/* → mfsg-backend:8000
                                                                    └─ /*                       → mfsg-frontend:3000
                                                 mfsg-backend ──▶ mfsg-postgres(pgvector) · mfsg-worker · 볼륨(vault, uploads, claude creds)
```

## 서버 현황 (2026-09-06 확인)

- 호스트 `<호스트>`, Ubuntu, 12 코어, 31 GB RAM(가용 23), 디스크 233 GB(191 GB 여유), Docker 28.0.1.
- 접속: `ssh <사용자>@<서버> -p <포트>` (sudo 필요).
- 이미 떠 있는 스택(절대 건드리지 않음): `geny-*-prod`(nginx :58999), `new-web-*`(:58443), `hr_gallery_*`(:58900), `gapt-*`.
- Cloudflare 터널: systemd `cloudflared.service`, 설정 `/etc/cloudflared/config.yml`, 터널명 `<터널>`,
  자격 `~/.cloudflared/<터널 ID>.json`, `cert.pem` 존재 → `cloudflared tunnel route dns` 가능.
- GPU 는 있으나 **MFSG 는 GPU 를 쓰지 않는다** (로컬 서빙 없음 원칙).
- 호스트에 node 없음 → 프론트 빌드는 전부 Docker 멀티스테이지에서.

## 포트 배정

| 용도 | 호스트 포트 | 비고 |
|---|---|---|
| mfsg-nginx | **58700** | 58999/58443/58900 과 충돌 없음. 127.0.0.1 바인딩 아님(터널이 localhost 로 접근하므로 `127.0.0.1:58700:80` 로 바인딩해도 됨 → **127.0.0.1 바인딩 채택**, 외부 직접 노출 차단). |
| 나머지 | 없음 | backend/frontend/postgres 는 `expose` 만. |

## Compose 파일

`deploy/docker-compose.yml` 단일 파일 + `deploy/.env` (untracked). 프로파일 없음. 개발용은
`deploy/docker-compose.dev.yml` (포트 직접 노출, 핫리로드 볼륨).

| 서비스 | 이미지 | 역할 | 볼륨 |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 메인 DB + 벡터 | `mfsg-pgdata` |
| `backend` | `./backend` Dockerfile (python:3.12-slim + node 22 + `@anthropic-ai/claude-code`) | FastAPI API + 파이프라인 | `mfsg-data`(/data: vault·uploads·exports), `mfsg-claude`(/home/mfsg/.claude, 0.3.0~) |
| `worker` | backend 와 동일 이미지, `python -m mfsg.worker` | 색인·알림·연동 동기화·다이제스트·크레딧 정산 | backend 와 동일 볼륨 |
| `frontend` | `./frontend` Dockerfile (node:22-alpine, `output: standalone`) | Next.js | 없음 |
| `nginx` | `nginx:1.27-alpine` + `deploy/nginx/nginx.conf` | 단일 진입점, 업로드 상한 64m, SSE 버퍼링 off | 없음 |
| `autoheal` | `willfarrell/autoheal:1.2.0` | unhealthy 컨테이너 재시작 | docker.sock |

핵심 환경변수(`deploy/.env.example` 에 전부 문서화):

```
MFSG_PUBLIC_URL=https://mfsg.hrletsgo.me
MFSG_SECRET_KEY=<64 hex>            # JWT·암호화 키 파생. 고정해야 재빌드 시 로그아웃 안 됨
MFSG_ENCRYPTION_KEY=<32 bytes b64>  # 프로바이더 키·OAuth 토큰 at-rest 암호화(Fernet)
POSTGRES_PASSWORD=<random>
NGINX_PORT=58700
TZ=Asia/Seoul
```

프로바이더 API 키는 **env 가 아니라 DB(`system_settings`, 암호화)** 에 저장하고 관리자 UI 로 입력한다.
env 는 부트스트랩 최소치만. (Geny 의 "키는 env" 관행을 버림 — 재배포 없이 키 교체.)

## Claude Code 자격 증명

- 컨테이너 안 `$MFSG_CLAUDE_HOME/.credentials.json`(0.3.0~ `/home/mfsg/.claude`, 그 전 `/root/.claude`) = 볼륨 `mfsg-claude`. Geny 와 **별도 볼륨**
  (동일 refresh token 을 두 프로세스가 회전시키면 충돌).
- 관리자 콘솔 [프로바이더 → Claude Code] 에서 두 경로 제공:
  1. **디바이스 로그인 중계**: backend 가 `claude auth login` 을 pty 로 띄워 URL 을 관리자에게 보여주고, 코드 입력을 중계 → 볼륨에 기록. (XGEN Codex 로그인 동형화 방식 이식)
  2. **JSON 붙여넣기**: 관리자가 자기 PC 의 `~/.claude/.credentials.json` 내용을 붙여넣으면 DB(암호화) 저장 + 볼륨 물질화. 상태(만료·구독 티어) 표시.
- 상태 확인: `claude --version`, 자격 파일 `expiresAt`, 실제 1-토큰 프로브 턴.

## nginx 라우팅

```
client_max_body_size 64m;
location /api/    { proxy_pass http://backend:8000; proxy_buffering off; proxy_read_timeout 3600s; }  # SSE
location /health  { proxy_pass http://backend:8000; }
location /static/ { proxy_pass http://backend:8000; }   # 공개 아바타·업로드 미리보기
location /        { proxy_pass http://frontend:3000; }
```

Cloudflare 가 TLS 종단. nginx 는 80 만. `X-Forwarded-Proto` 는 CF 헤더 신뢰.
CF 100초 응답 제한 → SSE 는 15초마다 `: ping` 코멘트로 유지.

## 진행 기록
- 2026-09-07: 서버 `~/docker_web/mfsg` 클론, `deploy/.env` 생성(600), 백엔드 이미지 선빌드 완료, cloudflared `/etc/cloudflared/config.yml` 에 `mfsg.hrletsgo.me → http://localhost:58700` 인그레스 추가 + `cloudflared tunnel route dns <터널> mfsg.hrletsgo.me` CNAME 생성(DNS 전파 확인).
- 2026-09-07: `docker compose -p mfsg up -d --build` 기동 — 6 컨테이너 healthy, `https://mfsg.hrletsgo.me/health/ready` 200, 랜딩/로그인/가입/관리자 페이지 200, 공개 링크 SSR(제목·OG·manifest) 확인. 최초 가입(=admin) 완료(비밀번호는 별도 보관). 모델 카탈로그 12개 자동 시드. root crontab 에 03:00 백업 등록.
- 2026-09-07: 0.3.0 하드닝 배포(백업 → `up -d --build`). 컨테이너는 uid 10001·read-only rootfs 로 기동, PID1 tini, `/app` 쓰기 거부 확인, alembic `0006_credit_reservation_owner_fk (head)`, `/health/ready` 전 항목 ok, 공개 페이지 200. Claude 자격 볼륨은 `/home/mfsg/.claude` 로 이동(같은 볼륨, entrypoint 가 chown).
- **남은 1회 수동 단계**: Claude Code 로그인 — `/admin/providers` → Claude Code 카드 → [디바이스 로그인] → 표시된 URL 을 브라우저에서 열어 로그인 → 코드 붙여넣기. (로컬 자격 복사는 계보 충돌로 실패함: D-31 정정 참조.) 로그인 전까지 턴은 `provider_auth` 오류를 친절 문구로 반환한다.

## 최초 배포 절차 (운영 서버)

```bash
# 0) 로컬: GitHub 에 main 푸시 완료 상태
# 1) 서버 클론
ssh -p <포트> <사용자>@<서버>
cd ~/docker_web && git clone https://github.com/CocoRoF/my-first-secretary-geny.git mfsg && cd mfsg/deploy
cp .env.example .env && $EDITOR .env      # 시크릿 채움 (MFSG_SECRET_KEY 등은 openssl rand -hex 32)
# 2) 기동
echo <pw> | sudo -S docker compose -p mfsg up -d --build
echo <pw> | sudo -S docker compose -p mfsg ps
curl -s http://127.0.0.1:58700/health
# 3) Cloudflare 터널 인그레스 추가 (/etc/cloudflared/config.yml, 404 폴백 위에)
#   - hostname: mfsg.hrletsgo.me
#     service: http://localhost:58700
sudo systemctl restart cloudflared
cloudflared tunnel route dns <터널> mfsg.hrletsgo.me   # CNAME 생성(cert.pem 필요, 서버 사용자로 실행)
# 4) 브라우저 https://mfsg.hrletsgo.me → 최초 가입 = 관리자 → 프로바이더 설정
```

## 재배포 절차

```bash
cd ~/docker_web/mfsg && git pull
echo <pw> | sudo -S docker compose -p mfsg up -d --build backend worker frontend
# DB 마이그레이션은 backend 기동 시 alembic upgrade head 자동 (entrypoint)
```

## 백업

- `postgres`: 매일 03:00 `pg_dump` → `~/backups/mfsg/YYYYMMDD.sql.gz` (worker 가 아니라 호스트 cron, 7일 보관).
- `mfsg-data` 볼륨: 주 1회 tar.
- 복구 절차는 `plan/26-ops-runbook.md`.

## 로컬 개발

```bash
cd deploy && docker compose -f docker-compose.dev.yml up -d postgres
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn mfsg.main:app --reload
cd frontend && pnpm i && pnpm dev
```

## 체크리스트 (배포 완료 기준)

- [x] `https://mfsg.hrletsgo.me/health` 200, `/health/ready` db·data·worker ok
- [x] 최초 가입 → 관리자(실측 role=admin), 두 번째 가입 → user(테스트 통과)
- [ ] 관리자 Claude Code **디바이스 로그인**(수동 1회) — 나머지 프로바이더 키는 선택
- [x] 비서 생성 → 오너 채팅 스트리밍 응답 (로컬 실 Claude Code 로 검증; 운영은 로그인 후 동일 경로)
- [x] 공개 링크 SSR·방문자 토큰·방문자 턴 SSE (로컬 실 Claude Code 로 검증, 운영은 페이지·토큰까지 확인)
- [x] 크레딧 원장에 턴 사용량 기록(테스트·로컬 라이브)
- [x] 컨테이너 재시작 후 로그인 유지(시크릿 .env 고정)·Claude 자격은 볼륨 `mfsg-claude`
