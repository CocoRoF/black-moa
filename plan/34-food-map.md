# 34 · 내 주변 맛집 — **폐기 (2026-09-12)**

> 사용자 결정으로 맛집 기능 전체를 제거했다(코드·테이블·게시판·설정·화면 모두). 아래는 기록용.


> 목표: 커뮤니티 안에 **[내 주변 맛집]** 을 만든다. 지도에서 주변 음식점을 보고, 골라서
> 메모라 사람들의 리뷰를 읽고 쓰고, 맛집 이야기를 게시판에 올리고, 인기글을 본다.
> 지도와 장소 데이터는 카카오·네이버 API에서, **리뷰와 이야기는 전부 우리 것**이다.

## 0. 두 API가 실제로 주는 것 — 오늘(2026-09-12) 직접 찔러 확인

| API | 인증 | 실측 | 주는 것 | 안 주는 것 |
|---|---|---|---|---|
| **Kakao Local — 카테고리 검색** `dapi.kakao.com/v2/local/search/category.json` | REST 키(`KakaoAK`) | `AccessDeniedError` — 계약 확인 | 좌표+반경(≤20km) 안의 **음식점(FD6)·카페(CE7)** — 이름·주소·도로명·좌표·전화·카테고리·`place_url`. 페이지당 15, **최대 45건** | **평점·리뷰 없음** |
| **Kakao Local — 키워드 검색** `…/keyword.json` | REST 키 | 계약 확인 | 키워드 + 좌표 정렬(`sort=distance`) | 〃 |
| **Kakao Maps JS SDK** `dapi.kakao.com/v2/maps/sdk.js` | **JavaScript 키**(공개, **도메인 등록 필수**) | 401 — 도달 확인 | 지도 렌더·마커·클러스터러 | — |
| **Naver 검색 — 지역** `openapi.naver.com/v1/search/local.json` | Client ID/Secret | `024 인증 실패` — 계약 확인 | 키워드 검색, **최대 5건**, 좌표는 `mapx/mapy`(WGS84×10⁷) | 반경 검색 없음, 평점·리뷰 없음 |
| **Naver Maps JS v3** `oapi.map.naver.com/openapi/v3/maps.js` | NCP Key ID(공개, 도메인 등록) | 200 | 지도 렌더 | — |

**설계를 정하는 사실 두 가지.**
1. **어느 쪽도 평점·리뷰를 API로 주지 않는다.** 그래서 리뷰는 처음부터 메모라의 것이다 —
   API가 주는 건 "어디에 무엇이 있는지"뿐이고, "어땠는지"는 우리 사람들이 쓴다. 이것이 이
   기능이 지도 앱의 복제가 아니라 커뮤니티인 이유다.
2. **"내 주변"을 제대로 하는 건 카카오뿐이다.** 좌표+반경 카테고리 검색이 있고 45건을 준다.
   네이버 지역 검색은 5건에 반경 개념이 없다. 그래서 **장소 탐색의 1차 출처는 카카오**,
   네이버는 (a) 키워드 보강 (b) 대체 지도 렌더러다. 둘 다 키 없이는 아무것도 못 하므로 관리자
   패널에서 키를 넣는 순간 켜지게 하고, 없을 때는 무엇을 넣어야 하는지 화면이 말한다.

키 발급: [developers.kakao.com](https://developers.kakao.com) (앱 생성 → REST API 키·JavaScript 키,
**플랫폼 > Web 에 `https://memo-ora.com` 등록**), [developers.naver.com](https://developers.naver.com)
(검색 API), 네이버 지도는 [ncloud.com](https://www.ncloud.com) Maps. 전부 무료 구간이 있다.

## 1. 원칙

- **요청 시점 조회, 단 캐시.** 기업정보(plan/33)와 달리 이건 위치 기반이고 사용자가 기다리는
  요청이다. 배치로 전국을 긁는 건 카카오 약관(별도 DB 구축 금지)에도 어긋난다. 대신 **격자
  캐시**(좌표를 ~250m 격자로 반올림 + 반경 + 카테고리 → 5분 TTL)로 같은 동네를 보는 사람들이
  호출을 공유하고, 하루 할당량이 보인다.
- **우리 DB에 남는 것은 사람이 손댄 장소뿐.** 리뷰·저장·이야기 태그가 붙는 순간 `places` 에
  (provider, provider_place_id) 로 고정된다. 검색 결과 전체를 저장하지 않는다.
- **위치는 저장하지 않는다.** 사용자 좌표는 그 요청에만 쓰인다. 리뷰에는 장소가 남지, 사람의
  위치가 남지 않는다.
- **비밀은 서버에.** REST 키·Client Secret 은 서버만 안다. 브라우저에는 지도 렌더용 공개 키만
  간다(그건 도메인 제한이 보호한다).
- **남의 서버는 우리 지연이 아니다.** 프로바이더 호출은 `httpx` 타임아웃 4초, 실패하면 캐시나
  빈 결과로 답하고 화면이 이유를 말한다. `misc` 레인.

## 2. 스키마

```
places
  id, provider (kakao|naver), provider_place_id     -- UNIQUE (provider, provider_place_id)
  name, category_text, category_group (FD6|CE7), address, road_address, phone, place_url
  lat, lng
  review_count, rating_sum, save_count              -- 비정규화 집계 (목록 정렬용)
  created_at, updated_at

place_reviews
  id, place_id → places, user_id → users
  rating 1..5, body, images JSONB, visited_on date?
  created_at, updated_at                             -- UNIQUE (place_id, user_id): 한 사람 한 장소 리뷰 하나(수정 가능)

place_saves
  place_id, user_id, created_at                      -- PK (place_id, user_id)

community_posts.place_id → places (nullable)         -- 이야기에 맛집 태그
community_boards: ("food", "맛집", kind="food")     -- 시드
```

## 3. 백엔드

`services/places/`
- `kakao.py` — 카테고리/키워드 검색, 응답 정규화. `place_url` 보존(카카오맵으로 이동).
- `naver.py` — 지역 검색 정규화. `mapx/mapy` 는 WGS84×10⁷ → 나눈다. HTML 태그(`<b>`) 제거.
- `cache.py` — 격자 TTL 캐시 + 호출 카운터(오늘 호출 수 → 관리자 화면).
- `service.py` — `nearby()`, `search()`: 프로바이더 결과에 **우리 집계(리뷰 수·평점·저장 수·
  이야기 수)를 얹는다**. `ensure_place()` upsert. 리뷰 CRUD + 집계 갱신. 저장 토글.

API (`/api/community/places/…`, 전부 로그인 사용자, 커뮤니티 읽기 예산 적용)
- `GET config` — 지도 프로바이더, 공개 JS 키, 기본 중심(서울시청), 검색 가능 여부
- `GET nearby?lat&lng&radius&category&sort` — 카카오 카테고리 검색 + 우리 집계
- `GET search?q&lat&lng` — 키워드
- `GET {id}` — 장소 + 리뷰 + 관련 이야기
- `GET/POST/DELETE {id}/reviews` — 내 리뷰(1개, 수정=덮어쓰기)
- `POST/DELETE {id}/save`, `GET mine` — 저장한 맛집
- `PostIn.place_id` — 이야기에 장소 태그; `_post_out` 에 `place` 요약

관리자
- 설정: `places.kakao_rest_key`(비밀) `places.kakao_js_key`(공개) `places.naver_client_id`
  `places.naver_client_secret`(비밀) `places.map_provider` `places.default_center`
- `GET /admin/places/status` — 키 등록 여부, 오늘 프로바이더 호출 수, 캐시 적중률, 장소·리뷰·
  이야기 수, 마지막 오류. `POST /admin/places/test/{provider}` — 실제 1회 호출로 키 검증.

## 4. 화면 `/app/community/food`

탭 셋: **[지도] [이야기] [인기글]**

**지도 탭** — 좌 지도 / 우 목록 (모바일: 지도 위 45vh, 목록 아래)
- 상단: [내 위치] · 카테고리(음식점/카페) · 반경(500m/1km/2km/5km) · 정렬(거리/평점/리뷰 많은 순)
  · 검색창
- 지도를 옮기면 [이 지역 재검색] 버튼. 마커 ↔ 목록 하이라이트 동기화.
- 목록 카드: 이름·카테고리·거리·**우리 평점(★4.3 · 리뷰 12)** ·저장 수·이야기 수
- 카드/마커 클릭 → **상세 서랍**: 정보, 평점 분포, 리뷰 목록, [리뷰 쓰기](별점+본문+방문일),
  [저장], [카카오맵에서 보기], 관련 이야기, [이 맛집 이야기 쓰기]
- 위치 권한 거부/실패 → 기본 중심(서울시청)으로 열고 안내 한 줄. 키 없음 → 목록은 비고
  "관리자가 카카오 키를 넣어야 해요"(관리자에게는 설정 링크).

**이야기 탭** — `board=food` 최신순, 장소 태그 칩, [이야기 쓰기]
**인기글 탭** — `board=food` hot 순

글쓰기: `/app/community/write?board=food&place=<id>` 로 오면 장소 칩이 붙는다.
글 보기: 장소 태그가 있으면 상단에 장소 카드(지도 탭으로 이동).

## 5. 단계

| 단계 | 내용 | 키 |
|---|---|---|
| 1 | 스키마 + 프로바이더 모듈(정규화·캐시) + 설정 + 관리자 상태/검증 | 없이 구조 완성, 있으면 즉시 동작 |
| 2 | API 전부 (nearby/search/detail/reviews/save/config) + 이야기 태그 | 〃 |
| 3 | 화면: 지도 탭(카카오 SDK 동적 로드, 마커, 서랍, 리뷰) | JS 키 있으면 지도, 없으면 목록만 |
| 4 | 이야기·인기글 탭, 글쓰기 장소 칩, 글 보기 장소 카드, 내비 | 없음 |
| 5 | 네이버: 키워드 보강 + 대체 렌더러 | 네이버 키 |

이번 작업 범위는 1~4 + 5의 검색 보강. 네이버 지도 렌더러는 프로바이더 스위치만 두고 카카오와
같은 인터페이스로 붙일 자리를 남긴다.

## 6. 하지 않는 것

- 전국 장소를 배치로 긁어 자체 DB를 만들지 않는다(약관·불필요).
- 카카오·네이버 리뷰를 스크래핑하지 않는다. 우리 리뷰만.
- 사용자 위치 이력을 남기지 않는다.
- 사진 업로드는 기존 업로드 경로(`community` 레인) 재사용, 별도 저장소 없음.

## 7. 상태 (2026-09-12)

| 단계 | 상태 | 비고 |
|---|---|---|
| 1 스키마·프로바이더·설정·관리자 상태 | **배포됨** | 0027_places, `services/places/{kakao,naver,cache,service}`, `places.*` 설정 8개, 관리자 [커뮤니티]→[맛집 지도] 탭(키 유무·검증·오늘 호출·캐시 적중·마지막 오류) |
| 2 API 전부 + 이야기 태그 | **배포됨** | `/api/community/places/{config,nearby,search,mine,{id},{id}/reviews/mine,{id}/save}`, `community_posts.place_id`, `food` 게시판 시드 |
| 3 지도 탭 | **배포됨** | 카카오 SDK 런타임 로드(`autoload=false`), 마커·반경 원·드래그 후 [이 지역 재검색]·마커↔목록 하이라이트·상세 서랍(저장/리뷰/이야기). 키 없으면 목록·지도 모두 "무엇이 빠졌는지" 안내 + 관리자 링크. **`?place=<id>` 딥링크**로 서랍 직접 열기, **[저장한 곳] 보기**는 프로바이더 없이 우리 행만 |
| 4 이야기·인기글·글쓰기 칩·글보기 카드·내비 | **배포됨** | 사이드바·하단 탭 [맛집], 글 카드/서랍/이야기 칩이 모두 `?place=` 로 이어짐 |
| 5 네이버 | 검색 보강만 | `naver.search` 는 키 있으면 keyword 결과에 dedup 보강. 지도 렌더러는 `places.map_provider` 스위치만 두고 "준비 중" |

운영 확인(2026-09-12, 실배포 브라우저): 키 없이 세 탭 렌더·안내 문구·관리자 탭 정상, CSP 에 kakao/naver 호스트 반영,
`Permissions-Policy: geolocation=(self)` 로 내 위치 허용, 딥링크→서랍→저장→리뷰(1인 1리뷰, 집계 반영)→[저장한 곳] 목록→글쓰기 칩까지
데스크톱/폰 동일 동작. 검증용 행은 삭제.

배포 함정: `deploy/nginx/nginx.conf` 는 **단일 파일 bind-mount** 라 `git pull` 로 inode 가 바뀌면 `nginx -s reload` 로는 새 내용을 못 본다 →
nginx 는 `up -d --force-recreate nginx`.

키 등록 후 남는 일(사용자): developers.kakao.com 앱 → [앱 키] REST API 키·JavaScript 키, [플랫폼 > Web] 에 `https://memo-ora.com` 등록 →
관리자 [커뮤니티]→[맛집 지도] 에 붙여넣고 [카카오 검증]. 네이버(선택): developers.naver.com 검색 API Client ID/Secret.

## 8. 배치 수집 (2026-09-12 추가 — "맛집도 크롤링 시스템 관리여야 한다")

§6 의 "자체 DB 를 만들지 않는다"는 철회. 기업정보와 같은 이유로 배치가 맞다: 프로바이더 하루 한도 /
동네 음식점은 주 단위로만 변함 / 커뮤니티 쿼리 예산 안에 남의 서버를 넣지 않는다.

- **영역(place_areas)**: 관리자가 이름·중심·반경·분류(음식점/카페)를 정한다. 전국을 긁지 않는다.
- **걷기**: 영역을 `places.grid_step_m`(500) 간격 격자로 나눠 중심에서 가까운 칸부터. 카카오는 칸당 최대 45곳만
  주므로 `total_count > 45` 인 칸은 넷으로 쪼개 다시(깊이 2). 영역당 `cursor` 로 **중단 지점부터 재개**.
- **예산**: `places.collect_per_run`(1500) · `places.daily_limit`(30000) · 실사용은 `place_source_runs.calls` 합.
  `RUN_DEADLINE_S=600`, 칸마다 커밋(죽어도 쓴 것과 쓴 호출이 남는다), 영역별 단일 비행 20분.
- **잡**: `crawl.places {area_id}` (crawl 클래스) / `places.refresh` 매일(`places.auto_collect` 켜져 있고 키 있을 때
  영역별로 큐잉). 워커 부팅 시 `close_abandoned`.
- **읽기 경로**: `nearby` 는 **우리 행 먼저** — 반경 안에 20곳 이상이면 프로바이더 호출 0, 적으면 호출해 병합, 키 없으면
  우리 행만(`note=partial`). 원 전체를 보고 정렬한 뒤 상위 200 + `total`. `hidden` 은 모든 독자 경로에서 제외.
- **관리자 [서비스]→[맛집 지도]** (`/admin/places`, 기업정보와 같은 3탭): 수집 설정(집계·키·검증·출처+예산·영역 표·키 폼) /
  수집 로그(큐 + 회차 이력, 5초 폴링) / 맛집 목록(출처·영역·분류·정렬 필터, 숨김 토글, 표는 창 안에서 스크롤).

첫 실측(2026-09-12, 강남역 2km, 음식점+카페): 1회차 131초 · **1,528회 호출 · 9,227곳 조회 · 신규 7,665** ·
52/69칸에서 per_run 에 걸려 "다음 수집에서 이어서". 지도는 `note=db` 로 호출 없이 응답.

## 9. 평점·리뷰 출처와 화면 개편 (2026-09-12)

**사실 확인**: 카카오 로컬·네이버 지역검색 API 는 평점·리뷰를 주지 않는다. 두 곳의 평점은 웹 페이지에만 있고 스크래핑은 약관 위반.
평점을 API 로 주는 곳은 **Google Places API (New)** 뿐 — Text Search 한 번에 `rating`·`userRatingCount`·`reviews`(최근 5개, 작성자 표기 의무)·
`googleMapsUri`·`priceLevel`. 요금은 Enterprise + Atmosphere SKU(장소당 1콜, 월 무료 한도 후 유료). 카카오 좌표 200m 안의 결과만 채택.

- 저장: `places.google_*` 컬럼(0029). 조회 시점 ① 사람이 서랍을 열 때(`places.google_on_open`) ② 관리자 [맛집 지도] 의 두 번째 출처 카드에서 배치
  (`places.google_per_run`, 재조회 `places.google_refresh_days`, `crawl.places {source:google}`; 사람이 만진 곳 → 최근 수집 순).
- 표시: 모든 카드·서랍에 **메모라 평점 / Google 평점** 을 나란히, 각각 이름표. Google 리뷰는 작성자·링크·시점과 함께 "Google에서 더 보기".
- 화면: 검색이 앞, 필터는 칩, 카드에 분류 글리프·두 평점·거리·이야기/저장 수, 핀은 분류 색·평가 있으면 금테·호버 확대·클러스터,
  서랍은 평점 2칸 → 액션(저장·이야기·전화·카카오맵·구글맵) → 사실(주소 복사) → "이 곳 어떠셨어요?" → 분포 → 다른 사람 리뷰 → Google 리뷰 → 이야기.
- 관리자 중심좌표 입력: Chrome 이 로그인 폼으로 오인해 이메일을 채움 → focus 전 `readOnly` + autocomplete off.

**아이콘(2026-09-12 추가)**: 이모지 글리프 폐기. `frontend/components/icons` 패키지가 유일한 아이콘 출처(lucide 재수출 + `BOARD_ICONS`/`FOOD_ICONS` 도메인 세트 +
vanilla `lucide` 노드로 SVG 문자열 → 지도 핀). ESLint 가 `lucide-react`/`lucide`/`react-icons` 직접 import 를 막는다.
