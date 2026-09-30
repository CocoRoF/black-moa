# 검사

## 계약 테스트 (`npm test`)

붙일 것이 없어도 도는 것들. CI 가 매번 돈다.

```
npm test
```

## 실제로 띄워 보는 것

화면과 서버가 필요하다. 손으로 돌린다.

```bash
# 이 환경에는 ELECTRON_RUN_AS_NODE 가 켜져 있다. 그대로 두면 Electron 이 순수
# Node 로 돌아 창이 하나도 안 뜬다. 스크립트가 지우고 띄운다.
export PATH=/home/workspace/.tools/node22/bin:$PATH

# 쓰기 위한 앱인지(plan/62): 틀·세 문·앱 모드·링크 규칙·알림·설정·빠른 대화·아바타·먼저 건넨 말·로그아웃.
#   TALK=1 은 실제로 한 마디 묻는다, SIGNOUT=1 은 끝에 로그아웃한다, HOLD_S 는 그만큼 켜 두고 세션을 본다.
#   화면은 xwd 로 통째로 찍는다(틀과 웹 뷰와 아바타가 서로 다른 창·뷰다).
FRESH=1 TALK=1 MEMORA_EMAIL=... MEMORA_PASSWORD=... SHOT_DIR=/tmp/shots \
  xvfb-run -a -s "-screen 0 1440x900x24" node test/shell.mjs

# 아바타: 뜨는지, 접히는지, 제자리에 있는지, 말을 받는지
#   (shell.mjs 를 먼저 돌려 로그인된 프로필을 만들어 둔다)
PROFILE_DIR=/tmp/memora-shell TALK=1 SHOT_DIR=/tmp/shots xvfb-run -a node test/avatar.mjs

# 구워 낸 설치본이 진짜로 뜨는지 (asar 에서만 드러나는 것들)
SHOT_DIR=/tmp/shots xvfb-run -a node test/packaged.mjs <AppRun 또는 실행 파일 경로>
```

`shell.mjs` 만 프로필을 지우고 시작한다(`FRESH=1`). `avatar.mjs` 는 그 프로필을 이어 쓴다.

**`waitForFunction` 은 쓰지 않는다.** 앱의 창은 CSP 가 eval 을 막아서, 기다리지도 않고 그 자리에서 던진다.
그걸 `.catch` 로 받으면 "안 끝났다" 로 읽혀 앱이 멈춘 것처럼 보인다(한 번 그렇게 헛짚었다). 1초 간격으로
직접 물어본다.

**세션이 끊기는지 보는 법.** 앱이 웹과 갱신을 두고 다투면 서버가 도난으로 보고
세션을 끊는다. 운영 DB 에서 이렇게 센다.

```sql
select count(*) from audit_logs where action = 'refresh_reuse_detected';
```

앱을 켜고 껐을 때 이 수가 늘면 안 된다 (plan/46 §2).
