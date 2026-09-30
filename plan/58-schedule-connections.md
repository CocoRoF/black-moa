# plan/58 — 스케줄의 [연동] 탭

상태: 구현·배포 (2026-09-25)

## 요청

스케줄 상단 탭을 **[일정] [연락 가능 시간] [연동]** 으로. 지금은 Google 하나지만, 관리 설정에서 Google 연동이
켜져 있으면 그것을 스케줄로 가져오는(sync) 설정을 여기서 한다. 앞으로 다른 연동도 들어온다.

## 원칙

- 스케줄은 Memora 의 원장이고, 바깥 달력은 **붙는 것**이다 (plan/56). 비서는 스케줄만 본다 (plan/57).
- 붙일 수 있는지는 **관리 설정**(Google OAuth)이 정한다. 붙인 뒤 무엇을·얼마나 자주는 **주인이 [연동] 탭**에서.
- 달력은 **공급자 등록표**(`services/calendar_sources.PROVIDERS`)로 붙는다. 화면은 서버 목록을 그대로 그린다 —
  달력이 하나 늘면 카드가 하나 는다.
- 계정 연결·해제는 [관리·설정 → 연동]의 일이다. 한 연결이 메일·연락처도 함께 들고 있어서, 스케줄에서 끊으면
  메일까지 끊긴다.

## 화면 ([연동] 탭, 달력마다 카드 한 장)

- 관리 설정에서 꺼져 있음: "지금은 연결할 수 없어요" (관리자에게는 [관리 설정에서 켜기]).
- 연결 전: [연결하기] → 동의 화면(일정 읽기 + 미팅 넣기) → 이 탭으로 돌아온다.
- 연결됨: 계정 · "N분 전 가져옴 · 일정 N개" · [지금 가져오기]
  - **일정 가져오기** — 끄면 그 달력의 일정이 스케줄에서도, 빈 시간 계산에서도 빠진다(지우지 않고 가린다).
  - **자동으로 가져오기** — 끔 · 1시간마다 · 6시간마다 · 하루에 한 번 (새 연결은 1시간).
  - **수락한 미팅을 그 달력에도 넣기** — 쓰기 권한.
  - 아직 받지 않은 권한을 켜면 바꾸지 않고 그 권한을 청하는 동의 화면으로 보낸다(이미 허락한 메일·연락처는 그대로 청한다).
  - 끊긴 연결: [다시 연결].
- [일정] 탭 위의 Google 안내 줄은 걷는다.

## 구현

- `services/calendar_sources.py`: 공급자(Google) · `sources` · `update`(동의 필요 판정) · `sync_now` · `due` · `reading_ids`.
  설정은 `connections.settings.calendar_auto_every`, 권한은 `connections.capabilities`(calendar_read/calendar_write).
- `services/schedule`: 바깥 일정은 가져오기를 켠 연결의 것만 합친다(events_between · busy_between).
- 작업: `calendar.autosync`(10분마다, 때가 된 연결에 `calendar.sync` 를 건다), `calendar.sync`(연결 하나).
  가져오기를 막 켰는데 한 번도 가져오지 않았으면 바로 한 번.
- API: `GET /api/schedule/sources`, `PATCH /api/schedule/sources/{provider}`, `POST …/{provider}/connect`, `POST …/{provider}/sync`.
  옛 `POST /api/schedule/google/sync` 와 달력 응답의 `google` 은 걷었다.
- 연동 콜백: 돌아갈 주소에 이미 `?` 가 있으면 `&connected=` 로 잇는다(예전에는 `?tab=sync?connected=` 로 깨졌다).
- 테스트: `tests/test_calendar_sources.py` (관리 설정 여부, 가져오기 끄면 스케줄·빈 시간에서 빠짐, 동의 필요, 자동 간격, 돌아오는 주소).

## 운영 확인 (2026-09-25)

- 탭 [일정] [연락 가능 시간] [연동], [일정] 위 Google 줄 없음, 휴대폰 폭 넘침 없음, `calendar.autosync` 가 10분마다 돈다.
- 운영은 관리 설정에서 Google 연동이 꺼져 있어 "지금은 연결할 수 없어요 · 관리 설정에서 켜기(관리자에게만)".
- 연결된 모습은 동기화가 돌지 않게 막은 임시 연결로 확인하고 지웠다: 가져온 때·일정 수·[지금 가져오기], 가져오기 끄기/켜기 동작.
- 그때 찾은 것: 관리 설정이 꺼진 채로 아직 받지 않은 권한을 켜면 설명 없는 오류 → 서버는 `calendar_unavailable` 로 거절, 화면은 그 스위치를 막고 까닭을 적는다.
