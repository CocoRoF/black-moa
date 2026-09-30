# plan/75 — Google Drive 와 [파일] (drive.file 하나로)

## 0. 배경 (2026-09-29)

Google OAuth 인증 제출에서 Drive 를 쓰겠다고 적었다(사용자: "drive 기능도 파일이랑 연동해서 사용할거야"). 처음 등록한
`auth/docs` 는 Drive API 의 `files.list` 가 받지 않는 범위이고, Drive 전체를 보는 범위(`drive`, `drive.readonly`,
`drive.metadata*`)는 Gmail 처럼 **제한 범위**라 매년 보안 평가(CASA)를 요구한다. 그래서 **`drive.file`** 하나로 간다.
민감하지 않은 범위라 정당화 문구도, 데모 영상의 장면도 필요 없다. Google 이 권하는 방식이다.

`drive.file` 은 이 앱이 만든 파일과, 사용자가 Google 의 파일 선택 창(Picker)에서 고른 파일만 연다. 비서가 Drive 를
훑는 일은 없다. 사용자가 건넬 파일을 고른다 — [파일]이 원래 그런 곳이다.

## 1. 한 것

- `services/gdrive.py`
  - **가져오기**: Picker 에서 고른 파일(한 번에 10개, 한 파일 25MB)을 비서의 [파일]로(`source="drive"`). Google 문서·
    시트·슬라이드는 Word·Excel·PowerPoint 로, 그림은 PDF 로 바꿔 받는다(비서가 읽는 형식). 폴더·그 밖의 Google 형식·
    없는 파일·저장 공간 부족은 그 파일만 건너뛰고 까닭을 돌려준다.
  - **저장하기**: [파일]의 파일 하나를 사용자의 Drive "Memora" 폴더에 올린다(폴더는 이 앱이 만든다 — `drive.file` 은
    이 앱이 만든 것만 보이므로 이름으로 찾아도 남의 폴더를 잡지 않는다). 지우거나 고치지 않는다.
  - Picker 는 브라우저에서 돈다 — 사용자 자신의 접근 토큰과 관리자가 넣은 브라우저용 API 키·프로젝트 번호를 건넨다.
    프로젝트 번호(`setAppId`)가 있어야 고른 파일이 이 앱에 허락된다.
- `api/drive.py`: `GET /api/drive/status` · `GET /api/drive/picker` · `POST /api/drive/import` · `POST /api/drive/save`.
- Google 공급자의 기능에 `drive`(범위 `drive.file`) — 관리자 [연결 → Google] 에 **파일 선택 창 API 키**와 **프로젝트
  번호** 칸. 키가 없으면 [가져오기] 단추는 숨고 [저장]만 보인다.
- 화면
  - [파일](내 정보·비서 탭) 머리에 [Google Drive에서 가져오기]. 모든 비서의 [파일]에서는 넣을 비서를 먼저 고른다.
    아직 잇지 않았으면 Google 로 보내 `drive` 만 더 청하고 이 화면으로 돌아온다.
  - 파일 상세에 [Google Drive에 저장] — 저장 뒤 [Drive에서 열기].
  - [출처] 거르기에 Google Drive, 연동 카드의 가는 곳에 "파일은 [파일]로".
- CSP: script-src `https://apis.google.com`, frame-src `https://docs.google.com https://drive.google.com`.
- 개인정보 처리방침 제2조 3·제8조 표·영문 블록에 drive.file 을 적었다.

## 2. Google Cloud 콘솔에서 할 것

1. API 라이브러리에서 **Google Drive API**, **Google Picker API** 사용 설정.
2. 사용자 인증 정보 → API 키 만들기 → 애플리케이션 제한 "HTTP 리퍼러" `https://memo-ora.com/*`, API 제한 "Google
   Picker API". 이 키와 프로젝트 번호를 Memora 관리자 [연결 → Google] 에 넣는다.
3. 데이터 액세스: `auth/docs` 와 `iam.test` 를 지우고 `https://www.googleapis.com/auth/drive.file` 을 넣는다.

## 3. 검증

- `tests/test_gdrive.py` — 가짜 Drive 로 연결·선택 창 설정 여부, 가져오기(시트→xlsx, 폴더·없는 파일 건너뜀), 남의
  비서로는 못 가져옴, 저장(폴더 한 번만 만듦, multipart 본문), Google 이 청하는 범위에 전체 Drive·docs 가 없음.
