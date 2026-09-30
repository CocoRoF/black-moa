# 26 · 운영 런북

서버: `ssh <사용자>@<서버> -p <포트>`, 스택 `~/docker_web/mfsg/deploy`, compose 프로젝트 `mfsg`. 모든 docker 명령은 `sudo`.

## 운영 계정·최초 설정
- **기본 관리자(0.4.0~)**: 부팅 시 `admin@geny.com` / `admin123` 이 없으면 자동 생성된다(role=admin). `deploy/.env` 의 `MFSG_DEFAULT_ADMIN_EMAIL` / `MFSG_DEFAULT_ADMIN_PASSWORD` 로 바꾸고, `MFSG_DEFAULT_ADMIN_ENABLED=0` 으로 끌 수 있다. 이미 있는 계정은 절대 건드리지 않으므로 비밀번호를 바꾸면 그대로 유지된다. 기본 비밀번호가 그대로면 관리자 콘솔이 붉은 경고를 계속 띄운다 — **공개 도메인에서는 첫 로그인 직후 마이페이지 [비밀번호 변경] 필수**.
- 관리자도 일반 사용자와 같은 `/app` 홈을 쓰고, 좌측 내비의 [관리] 로만 콘솔에 들어간다.
- 관리자: 운영자 계정(비밀번호는 별도 보관). 첫 로그인 후 `/admin/setup` 위저드 또는 `/admin/providers`.
- **Claude Code 로그인(필수, 1회)**: `/admin/providers` → Claude Code → [디바이스 로그인] → URL 열어 로그인 → 코드 붙여넣기 → 상태 카드 `credentials_present: true` → [프로브] 로 `pong` 확인. 자격은 볼륨 `mfsg-claude` 에 저장되고 매시간 DB 로 백업된다. **다른 PC 의 credentials.json 을 붙여넣지 말 것**(refresh token 회전으로 둘 중 하나가 로그아웃됨 — D-31).
- 선택: OpenAI 키(STT/TTS/임베딩·GPT), Gemini 키, SMTP(알림 메일), Google OAuth 클라이언트(구글 로그인/연동), 텔레그램 봇.

## 자주 쓰는 명령
```bash
cd ~/docker_web/mfsg/deploy
sudo docker compose -p mfsg ps
sudo docker compose -p mfsg logs -f --tail 200 backend
sudo docker compose -p mfsg logs -f --tail 200 worker
sudo docker compose -p mfsg exec backend sh -c 'curl -s localhost:8000/health/ready'
sudo docker compose -p mfsg exec backend claude --version
sudo docker compose -p mfsg exec postgres psql -U mfsg -d mfsg -c 'select count(*) from turns;'
```

## 배포 (재배포)
```bash
cd ~/docker_web/mfsg && git pull
cd deploy && sudo docker compose -p mfsg up -d --build backend worker frontend
sudo docker compose -p mfsg ps      # healthy 확인
curl -s https://mfsg.hrletsgo.me/health
```
롤백: `git checkout <이전 태그>` 후 동일 명령. DB 마이그레이션 다운은 `alembic downgrade -1`(백업 후).

## 장애 시나리오
| 증상 | 확인 | 조치 |
|---|---|---|
| 채팅이 "생각 중"에서 멈춤 | `logs backend` 에 `loop watchdog` / `api.error` | Claude 자격 만료면 관리자 [프로바이더]에서 재로그인; 루프 블록이면 `docker compose restart backend`(autoheal 이 보통 먼저 함) |
| `exec.cli.auth_failed` | `exec backend cat "$MFSG_CLAUDE_HOME"/.credentials.json \| jq .claudeAiOauth.expiresAt` | 관리자 콘솔 디바이스 로그인 또는 JSON 임포트. DB 백업본에서 복원: `POST /api/admin/providers/claude-code/restore` |
| 402 크레딧 | 관리자 사용자 화면 잔액 | 부여 |
| 방문자 페이지 "쉬는 중" | 링크 상태·오너 잔액 | 링크 resume / 크레딧 |
| 워커 하트비트 없음 | `logs worker` | `restart worker`; 잡 데드레터 확인 `/admin/jobs` |
| 디스크 85% | `df -h`, `du -sh /var/lib/docker/volumes/mfsg-data` | 오래된 turn_events delta 정리 잡 수동 실행, TTS 캐시 삭제, 백업 정리 |
| 임베딩 실패(409 embedding_key_missing) | 관리자 임베딩 설정 | 키 등록 후 `/admin/embedding` 재색인 |
| DB 연결 실패 | `logs postgres`, `pg_isready` | 재시작; 볼륨 손상 시 백업 복원 |
| 터널 502 | `sudo systemctl status cloudflared`, `curl 127.0.0.1:58700/health` | nginx 컨테이너·cloudflared 재시작 |

## 백업 · 복원 (age 암호화, 0.3.0~)
백업 산출물은 평문으로 남기지 않고 age 로 암호화한다. 호스트 준비는 이미 완료돼 있다.

- 도구: `age`, `age-keygen`, `pg_restore`(apt: `age`, `postgresql-client`)
- 키: `/root/.config/mfsg/backup-age.key` (root, 600). **이 파일이 없으면 백업은 복호화 불가** — 호스트 밖(비밀번호 관리자/다른 머신)에도 반드시 사본을 둔다.
- 설정: `deploy/backup.env` (root, 600) — `MFSG_BACKUP_DIR`, `MFSG_BACKUP_AGE_RECIPIENT`(공개키), `MFSG_BACKUP_AGE_IDENTITY`, `MFSG_BACKUP_RETENTION_DAYS=28`
- cron: **root** crontab, 매일 03:00 `deploy/scripts/backup.sh`
```bash
sudo ~/docker_web/mfsg/deploy/scripts/backup.sh          # 수동 백업
sudo ~/docker_web/mfsg/deploy/scripts/backup-verify.sh   # 최신 아카이브 복호화·구조 검증
# 복원(예시): age -d -i /root/.config/mfsg/backup-age.key < mfsg-YYYYmmdd.tar.age | tar x -C /restore
#   → db.dump 은 pg_restore, data.tar 는 mfsg-data 볼륨에 풀기
```
⚠️ **개발자 PC 의 `~/.claude` 나 그 사본을 컨테이너에 마운트하지 말 것.** 컨테이너 entrypoint 가 uid 10001 로 chown 하고, CLI 가 토큰을 회전시키면 사람이 쓰던 로그인이 끊긴다. 컨테이너 자격은 항상 관리자 콘솔 [디바이스 로그인] 으로 그 컨테이너 안에서 새로 만든다(D-31).

## 키 교체
- `MFSG_SECRET_KEY` 변경 = 전원 로그아웃(refresh 무효). 방문자 토큰도 무효.
- **순서 주의**: 예전 설치는 Fernet 키를 `MFSG_SECRET_KEY` 에서 파생했다. 서명 키를 먼저 돌리면 DB 의 프로바이더 키·OAuth 토큰이 전부 복호화 불가가 된다. 먼저 현재 파생값을 고정하라:
  `sudo docker compose -p mfsg run --rm --no-deps backend python -m mfsg.core.keytool legacy` → 출력값을 `MFSG_ENCRYPTION_KEY` 에 넣고 재배포·검증한 뒤에 서명 키를 교체한다.
- Fernet 교체는 새 키를 `MFSG_ENCRYPTION_KEY`, 이전 키를 `MFSG_ENCRYPTION_KEY_PREVIOUS`(복호화 전용)에 둔다.
- 프로바이더 키는 관리자 콘솔에서 교체(재시작 불필요, 다음 세션 빌드부터).

## Cloudflare 터널 변경
`/etc/cloudflared/config.yml` 인그레스 편집 → `sudo systemctl restart cloudflared`. DNS 라우트 `cloudflared tunnel route dns <터널> <host>`.

## 데이터 삭제 요청
사용자 스스로 `/app/settings` 삭제 또는 관리자 `/admin/users/{id}` 삭제 → 즉시 연쇄. 백업본은 7일 후 자동 소멸(보관 정책).

## 업그레이드 노트
- `geny-executor` 핀 변경 시: 이벤트 카탈로그 변화 확인(`known_event_types`), CLI 버전 호환(`claude --version`), 테스트 전체.
- `@anthropic-ai/claude-code` 버전은 Dockerfile ARG. 변경 후 관리자 [프로브] 필수.
- PG 메이저 업그레이드는 `pg_dump/restore`.

## 연락처·리소스
- GitHub: https://github.com/CocoRoF/my-first-secretary-geny
- 서비스: https://mfsg.hrletsgo.me
- 관리자 계정: 최초 가입자(비밀번호는 별도 보관)

## 알림 채널은 증명한 곳으로만 간다 (2026-09-21)

메일 채널의 받는 주소를 아무 주소로나 지정할 수 있었고, [테스트 발송]에 제한이 없었다.
채널 하나 만들고 반복해서 누르면 **우리 서버 이름으로 제3자에게 메일이 나간다.** 보내는
도메인의 평판이 걸리는 일이다.

처음엔 발송 횟수에 천장을 뒀는데 그건 증상만 가린다. 문을 잠그는 쪽이 맞다.

- 주소는 여전히 어디든 적을 수 있다. 다만 **그 주소로 간 여섯 자리를 가져와야** 열린다.
  계정 자기 주소면 증명할 것이 없으니 그대로 열려 있다.
- `verified_at` 칸은 이미 있었는데 **보내는 자리에서 아무도 보지 않았다.** 채널을 고르는
  곳과 실제로 내보내는 곳 두 군데 모두에서 본다. 칸만 있고 집행이 없으면 없는 것과 같다.
- 메일 채널은 [테스트 발송]으로 확인될 수 없다. 그 길이 곧 통로였다.
- 0060 이주: 이미 자기 주소로 가던 채널 11개는 확인된 것으로 둔다. 쓰던 알림이 조용히
  멈추면 안 된다.
- 남은 제한은 인증 코드를 보내는 간격 하나뿐이다(10분에 3번). 계정 메일 인증과 같다.
