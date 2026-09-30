# plan/76 — 연결 동기화: 바로바로, 하나씩, 보이게

## 0. 겪은 것 (2026-09-30)

카카오를 잇자 5초 만에 가져왔는데 연동 화면은 새로 고칠 때까지 "마지막 동기화: –" 였다. 들여다보니:

| 무엇 | 전 | 후 |
|---|---|---|
| 끝났다는 소식 | 없음 — 새로 고칠 때까지 옛 화면 | 버스 `connection` 소식 → 연동·스케줄·메일·인맥이 다시 읽음 |
| "마지막 동기화" | 연결 가져오기만 찍음(달력 자동 가져오기는 안 찍음) | 어느 길이든 `CN.synced` 한 곳에서 |
| Google 일정 | 1시간마다 | 변경 알림(푸시)으로 몇 초 — 실측 생성 5.1초·삭제 9.1초 |
| 카카오 일정 | 1시간마다 | 15분마다 + 스케줄을 열거나 비서가 일정·빈 시간을 볼 때 5분 넘었으면 먼저 |
| 메일함(IMAP) | 연결할 때와 버튼뿐 | 10분마다 + 메일 화면을 열 때 3분 넘었으면 |
| Google 연락처 | 처음 한 번만 | 하루에 한 번 |
| Google 일정 250개 넘게 | 첫 쪽에서 잘림 | 다음 쪽까지(10쪽) |
| 권한·설정 실패(400/403/404) | 다섯 번 조용히 되풀이, 화면엔 없음 | 적어 두고(`calendar_error`·`contacts_error`) 화면에 한 줄, 연결은 살아 있음 |
| 같은 연결의 가져오기가 겹침 | 지우고-넣기가 섞일 수 있음 | 연결마다 advisory 잠금 |

## 1. 구조

- `services/connections.py` — `lock`(연결마다 하나씩) · `synced`/`failed`(한 곳에서 찍기) · `announce`(버스 `connection`) ·
  `calendar_part`(권한 실패는 적고 계속) · `due`(메일함 10분·연락처 하루).
- `services/calendar_sources.py` — `sync_connection` 이 모든 달력 가져오기의 입구. `nudge`(10초 칸마다 따로 걸어 도는 중에
  온 변경도 놓치지 않음) · `refresh_if_stale`(화면) · `ensure_fresh`(비서, 6초 안에 못 하면 가진 것으로). 기본 간격 15분.
- `services/google.py` — `ensure_watch`/`stop_watch`: 채널 id `memora-<연결 hex>-<시각>`, 토큰은 secret_key HMAC.
  달력 가져오기마다 하루 안에 끝날 채널을 새로 연다(채널은 일주일). 가져오기를 끄거나 연결을 끊으면 닫는다.
- `api/integrations.py` — `POST /api/integrations/google/push`(관문에 열어 둠): 채널 id·토큰이 맞을 때만 `nudge`.
  새 채널로 바뀌는 사이의 옛 채널 알림도 토큰이 맞으면 받는다. 판단마다 `google push` 로그.
- 워커 주기: `calendar.autosync` 5분, `integrations.autosync` 5분.
- 화면: `useShellLive` 가 `connection` 을 듣는다. 연동 카드는 가져오는 중(스피너)·실패 한 줄, 스케줄 [연동] 탭은
  `sync_error` 한 줄과 15분 간격.

## 2. 검증

- `tests/test_connection_sync.py` — 푸시(위조 토큰·sync 인사·모르는 채널은 무시), 다음 쪽, 권한 실패 기록·복구, 스케줄을 열면
  오래된 달력 가져오기, 연락처 하루·메일함 10분.
- 운영: 사용자 Google 캘린더에 시험 일정을 넣고 지워 푸시 왕복 실측(5.1초/9.1초), 카카오 톡캘린더 조회·나에게 보내기.

## 3. 남은 것

- Google 은 알림마다 -7일~+60일을 통째로 다시 받는다. 사용자가 많아지면 syncToken 증분으로.
- 카카오는 알려 주지 않는다 — 15분 + 볼 때 새로가 한계.
