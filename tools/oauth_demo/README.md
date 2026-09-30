# Google OAuth 인증 데모 영상 (plan/75)

Google 이 민감한 범위(calendar.readonly · calendar.events · contacts.readonly)마다 요구하는 사용 영상을 찍는다.
진짜 Chrome 을 가상 화면에 띄우고 사람처럼 누른다 — 주소창(client ID)까지 찍혀야 해서 페이지만 찍는 녹화로는 안 된다.

- 화면: `Xvfb :77 -screen 0 1920x1080x24`
- 브라우저: `google-chrome --user-data-dir=~/.memora-demo-chrome --remote-debugging-port=9333 --lang=en-US`
  (LANG=en_US.UTF-8). Google 로그인은 이 창에서 한 번 한다. 자동화 표시가 없도록 Playwright 는 `connectOverCDP` 로 붙는다.
- 누르기·입력: xdotool (실제 입력). 녹화: ffmpeg x11grab.
- 자막·흐림: `postproc.py` — `captions.json`(장면 설명)과 `blurs.json`(다른 사람의 이름·번호, Drive 파일 목록)을 입힌다.

## 찍기

```bash
DEMO_PW=... python3 reset_demo.py        # 나와의 대화 지움 · 미팅 요청 보관 · Google 연결 끊기(권한 회수)
DEMO_PW=... node rec.mjs                 # out/demo-raw.mp4, out/captions.json, out/blurs.json
python3 postproc.py out/memora-oauth-demo.mp4
```

녹화 뒤 운영 백엔드 컨테이너에서 흔적을 지운다: `cal_clean.py "Meeting with Jamie" …`(Google 캘린더 일정),
`drive_clean.py --all`(Memora 가 만든·고른 Drive 파일). 데모 계정에 들어온 연락처(`network_nodes.source = 'google_contacts'`)도 지운다.

## 함정 (2026-09-30 여섯 번 찍으며 겪은 것)

- Google 계정에 이 앱의 옛 권한이 남아 있으면 동의 화면이 "already has some access" 요약만 보인다 — 먼저 연결을 끊는다.
- 권한 화면의 체크박스는 기본 해제다. [Select all] 을 누르지 않으면 받은 기능이 하나도 없다.
- 연락처는 프로젝트에 **People API** 가 켜져 있어야 한다(꺼져 있으면 403).
- 데모 비서는 연락 가능 시간이 있어야 방문자 미팅 요청을 만든다(평일 9–18).
- 파일 선택 창에서 저장한 것과 같은 파일을 다시 고르면 내용이 같아 새 파일이 생기지 않는다 — 다른 Google 문서를 고른다.
