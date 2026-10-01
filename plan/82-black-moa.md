# plan/82 — black-moa: 이름을 갈고 black.memo-ora.com 에 따로 선다

## 0. 지시 (2026-10-01)

앞으로는 black-moa 만 고도화한다. 전체를 black-moa 로 만들고, Memora 와 같은 서버에
`black.memo-ora.com` 으로 배포한다. Memora 는 그대로 돌아간다.

## 1. 이름

| 자리 | 전 | 후 |
|---|---|---|
| 화면·메일·문서의 이름 | Memora / 메모라 | black-moa / 블랙모아 (`frontend/lib/brand.ts` 의 `BRAND.name` 이 정본) |
| 파이썬 패키지 | `memora` | `blackmoa` |
| 환경변수 접두사 | `MEMORA_` | `BLACKMOA_` |
| compose 프로젝트·컨테이너·볼륨·망·이미지 | `memora*` | `blackmoa*` |
| DB·롤·S3 버킷·쿠키·브라우저 저장소 키 | `memora` | `blackmoa` |
| 주소 | `memo-ora.com` | `black.memo-ora.com` |
| PC 앱 | `com.memora.desktop`, `Memora_<os>_<버전>` | `com.blackmoa.desktop`, `black-moa_<os>_<버전>` |
| 다운로드 센터가 보는 저장소 | 옛 비공개 저장소 | `CocoRoF/black-moa` |

- `plan/` 과 `CHANGELOG.md` 의 옛 이름은 그대로 둔다. 그때 내린 결정의 기록이라 고쳐 쓰면 기록이 거짓이 된다.
- 다른 제품에서 가져온 생각을 밝힌 주석(Geny 등)도 그대로.
- 한국어 조사: "Memora" 와 "black-moa" 모두 모음으로 끝나 조사(는·가·를·로)를 바꿀 곳이 없다.

## 2. 그림

- M 표식·아이콘·파비콘·PC 앱 아이콘은 이름이 들어 있지 않아 그대로 쓴다.
- 글자가 들어간 그림만 `tools/brand_wordmark.py` 로 새로 만든다: 원본 글자와 가장 닮은 둥근 서체
  Fredoka 700(OFL)으로 "black-moa" 를 쓰고, "o" 자리에 원본 글자 그림의 그라데이션 o(`images/brand-o.png`,
  한 번 떼어 둔 정본)를 끼운다. 그라데이션 o 는 서체의 o 보다 넓어 같은 중심에 얹으면 m·a 에 닿는다 —
  서체의 양옆 여백을 둔 채 o 의 실제 폭만큼 자리를 낸다.
- 만드는 것: 워드마크(밝게·어둡게), 표식+글자 조합 네 크기, OG 기본 그림, `images/black-moa-*.png`.
  그림을 바꾸면 `BRAND_REV` 를 올린다(가장자리 캐시 7일).
- 메일 머리의 워드마크 크기 138×22(글자가 길어진 비율).

## 3. 한 서버에 두 스택

- Memora 는 `127.0.0.1:58700`, black-moa 는 `127.0.0.1:58710`. 같은 cloudflared 터널에 호스트 이름 하나를 더한다.
  DNS 는 터널 id 로 CNAME — 터널의 cert.pem 이 다른 존의 것이면 `cloudflared tunnel route dns` 가 엉뚱한
  레코드를 만든다(`deploy/scripts/tunnel-add.sh` 가 API 로 만든다).
- compose 의 메모리 상한·예약을 `BLACKMOA_<서비스>_MEM`·`_MEM_RESERVE`, Postgres 의 `shared_buffers`·
  `effective_cache_size` 를 env 로 바꿀 수 있게 했다. 기본값은 혼자 쓰는 호스트에 맞춘 그대로이고, 같이 쓰는
  운영 `.env` 에서 낮춘다. 이웃 스택보다 예약을 작게 둬 메모리가 모자랄 때 먼저 양보한다.
- 데이터·비밀은 처음부터 따로: DB·S3·Claude 자격·암호화 키 모두 새로 만든다. 계정·대화·파일은 옮기지 않는다.

## 4. 처음 켠 뒤 남는 일 (운영자)

- 관리자 콘솔에서 AI 공급자(Claude Code 로그인 등). 다른 설치의 Claude 자격을 복사하면 refresh 회전으로 둘 다 깨진다.
- 메일 발송(SMTP), Google·카카오 연결의 키와 Redirect URI(`https://black.memo-ora.com/...`).
- PC 앱 릴리스를 다운로드 센터에 올리려면 저장소 시크릿 `BLACKMOA_RELEASE_KEY`.
