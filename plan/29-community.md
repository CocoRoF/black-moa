# 커뮤니티 — 아키텍처

> 목표: 개인 비서(마이데이터)를 만든 사람들이 그 데이터를 근거로 **직장인 · 취업 · 연애** 이야기를 나누는 광장.
> 익명 게시판이 아니라 **직무가 붙는 실명형 커뮤니티**가 차별점이다.

## 1. 위치 결정 — 같은 DB, 분리된 경계

MSA로 떼지 **않는다.** 지금 필요한 것은 배포 단위 분리가 아니라 *변경 격리*이고, 커뮤니티는
`users`/`profiles`와 매 요청 조인된다(작성자 신원 = 마이데이터). 서비스를 쪼개면 그 조인이
네트워크 호출과 최종적 일관성 문제로 바뀐다 — 얻는 것 없이 잃기만 한다.

대신 **떼어낼 수 있게** 짓는다:

- 모든 테이블 `community_` 접두사, 커뮤니티 외 테이블 참조는 `users.id` 하나뿐
- 모든 접근은 `services/community.py` 단일 게이트를 통과 (다른 서비스가 테이블을 직접 읽지 않음)
- API 네임스페이스 `/api/community/*`

트래픽이 실제로 분리를 요구하면 그때 이 세 경계를 따라 잘라내면 된다.

## 2. Multi-pod 전제

지금도 backend/worker 파드가 여러 개다. 커뮤니티에서 깨지기 쉬운 지점만 나열한다.

| 위험 | 순진한 구현 | 여기서 하는 것 |
|---|---|---|
| 카운터(댓글·좋아요) | 파이썬에서 읽고 +1 후 저장 | `UPDATE ... SET c = c + 1` 원자 증가. 읽기-수정-쓰기 금지 |
| 조회수 | 요청마다 UPDATE → 인기글 행 잠금 직렬화 | `(post, viewer, day)` 유니크 삽입 → **삽입된 경우에만** 증가. 중복 제거가 곧 의미 있는 수치 |
| 좋아요 토글 | SELECT 후 INSERT/DELETE (경합 시 중복) | 유니크 제약 + `ON CONFLICT DO NOTHING` / `DELETE ... RETURNING`, 실제 변화량만 카운터에 반영 |
| 인기글 정렬 | 요청마다 전체 스캔 정렬 | 워커가 주기적으로 `hot_score` 계산·기록, 인덱스로 읽음 |
| 이중 제출 | 새 글 두 번 생김 | `client_token` per author 유니크 |
| 동시 수정 | 나중 저장이 앞을 덮음 | `version` 낙관적 잠금, 충돌 시 409 |
| 도배 | 인메모리 레이트리미터(파드마다 따로 셈) | DB 기준 창(窓) 카운트 — 파드 수와 무관 |
| 삭제 | 하드 삭제로 스레드 붕괴 | `status`(published/hidden/deleted) 소프트 삭제, 답글은 살아남음 |

## 3. 스키마

```
community_boards      slug, name, description, kind(discussion|jobs), sort_order,
                      enabled, min_role, icon
community_posts       board_id, author_id, title, body, status, is_pinned,
                      comment_count, like_count, view_count, hot_score,
                      client_token, version, search(tsvector), created/updated/edited_at
community_comments    post_id, author_id, parent_id, body, status, like_count,
                      depth, version, created/updated_at
community_reactions   target_type(post|comment), target_id, user_id, kind
                      UNIQUE(target_type, target_id, user_id, kind)
community_post_views  post_id, viewer_key, day     UNIQUE(post_id, viewer_key, day)
community_reports     target_type, target_id, reporter_id, reason, status
community_jobs        title, company, location, employment_type, experience_min,
                      salary_min/max, tags, apply_url, posted_by, status, expires_at
```

작성자 신원은 **저장하지 않는다.** 표시할 때 `users` + `profiles`에서 읽는다 — 프로필을 고치면
과거 글의 직함도 함께 최신이 되고, 신원 사본이 두 벌 생기지 않는다.

## 4. 신원 — 마이데이터가 쓰이는 지점

글쓴이 줄은 `닉네임 | 직무 · 회사` 다. 직무·회사는 비서 콘솔의 프로필에서 온다.
공개 범위는 사용자가 정한다: `community.identity` = `job`(직무까지) · `name_only` · `hidden`.
비서의 공개/비공개 정책과 같은 원칙 — 본인이 고른 것만 보인다.

## 5. 화면

사이드바 최상단에 **[비서관리 | 커뮤니티]** 탭. 전환하면 상대편 홈으로 간다.

- 커뮤니티 홈: 좌측 주제 목록 · 가운데 베스트글 + 새글 피드 · 우측 추천글
- 글 상세: 제목, 주제, 작성자(직무), 조회·좋아요·댓글, 본문, 답글 가능한 댓글
- 글쓰기/수정, 좋아요, 신고
- 채용: 직무·지역·경력 필터가 붙은 목록

## 6. 단계

1. 스키마 + 서비스 + API + 기본 게시판 시드 ← *지금*
2. 커뮤니티 홈 · 글 목록/상세/작성 · 댓글 · 좋아요
3. 채용 탭, 검색, 내 활동, 신고·모더레이션
