# 10 · 사용자 인맥 네트워크 그래프

## 목표

오너의 인맥을 **그래프(노드·엣지)** 로 완전하게 모델링해 비서가 "누가 누구인지, 어떤 관계인지, 최근에 무슨 맥락이 있었는지"를 안다. 방문자가 "저는 OO 회사의 김OO 인데요" 하면 비서가 그래프에서 찾아 맥락에 맞게 응대한다(공개 경계 안에서).

## 데이터 모델 (PG)

### `network_nodes`
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | uuid | |
| owner_id | uuid | 계정 |
| kind | enum `person, organization, group, project, place, event` | |
| name | text | 표시명 |
| aliases | text[] | 별칭·영문명·직함 포함 표기 |
| attrs | jsonb | kind 별 스키마: person `{title, company_node_id?, emails[], phones[], birthday, timezone, languages[], links{linkedin,github,…}, how_we_met, notes}`; organization `{domain, industry, website}` |
| tags | text[] | `client, friend, family, vip, …` |
| visibility | enum `private, on_request, public` | 방문자에게 존재를 밝힐 수 있는가 |
| importance | int 1~5 | 우선순위 |
| last_contact_at | timestamptz | 연동/수동으로 갱신 |
| source | enum `manual, google_contacts, chat_derived, import_csv, integration` | |
| embedding | vector(1536) nullable | 이름+속성+노트 임베딩(검색용, plan/09 임베딩 프로바이더) |
| created_at / updated_at | | |

### `network_edges`
| 컬럼 | 설명 |
|---|---|
| id, owner_id | |
| src_id, dst_id | 노드 |
| rel | enum-ish text: `colleague, reports_to, manages, friend, family(spouse/parent/child/sibling), client, vendor, mentor, mentee, member_of, works_at, founder_of, investor_in, collaborates_on, introduced_by, knows` |
| direction | `directed | undirected` (rel 별 기본값 표) |
| strength | 0~1 (수동 + 접촉 빈도 자동 보정) |
| since / until | date nullable |
| attrs | jsonb `{role, context, notes}` |
| visibility | private/on_request/public |
| source | manual / chat_derived / integration |

### `network_interactions`
접촉 이력(엣지 강도·`last_contact_at` 의 근거). `{node_id, kind: email|meeting|call|message|chat_visit, at, summary, ref}`. 구글 연동이 최근 메일/일정에서 생성(plan/11), 방문자 대화에서 식별된 방문자가 노드와 매칭되면 `chat_visit` 기록.

### `network_proposals`
비서가 대화에서 추론한 그래프 변경 제안. `{kind: add_node|add_edge|update_attr|merge, payload, confidence, source_turn_id, status: pending|accepted|rejected}`. 오너 콘솔 "제안" 탭에서 승인해야 반영. (자동 반영 없음 — 그래프 오염 방지.)

## 그래프 API

```
GET    /api/network/graph?depth=&center=&kinds=&tags=&q=     # 뷰용 서브그래프 (노드 ≤ 500, 엣지 ≤ 3000, truncated 플래그)
GET    /api/network/nodes?q=&kind=&tag=&page=
POST   /api/network/nodes   PATCH /nodes/{id}   DELETE /nodes/{id}
POST   /api/network/edges   PATCH /edges/{id}   DELETE /edges/{id}
POST   /api/network/nodes/{id}/merge {into_id}
GET    /api/network/nodes/{id}/interactions
GET    /api/network/proposals?status=   POST /proposals/{id}/accept|reject
POST   /api/network/import/csv   (name,email,company,relation,tags)
POST   /api/network/import/google-contacts  (연동 필요)
GET    /api/network/stats  (노드/엣지 수, kind 분포, 최근 접촉 상위)
GET    /api/network/path?from=&to=  (최단 경로 ≤ 4홉, BFS)
```

## 쿼리 엔진 (backend `services/network/graph.py`)

- 저장은 PG, 질의는 파이썬 인메모리(오너당 노드 수천 규모 가정). 오너별 그래프 캐시(LRU, 변경 시 무효화).
- 연산: `neighbors(node, depth)`, `shortest_path`, `search(q)`(이름·별칭 트라이그램 `pg_trgm` + 임베딩 코사인 병합), `who_at(org)`, `by_relation(rel)`, `recent_contacts(n)`, `communities`(라벨 전파, 시각화 색상용).
- 방문자 매칭: 방문자가 밝힌 이름/이메일/회사 → 후보 노드 상위 3 + 점수. 점수 ≥0.85 이면 비서에게 "아마 OO(회사·관계)" 로 제공, 그 미만은 "확인 질문" 유도.

## 에이전트 도구 (plan/07 도구 표)

| 도구 | 오너 | 방문자 | 설명 |
|---|---|---|---|
| `network_search(query)` | ✓ | ✓(visibility 필터) | 이름/회사/태그 검색 |
| `network_person(node_id)` | ✓ | ✓(필터) | 상세·관계·최근 접촉 |
| `network_neighbors(node_id, depth)` | ✓ | ✗ | |
| `network_path(a, b)` | ✓ | ✗ | "A 와 B 는 어떻게 아는 사이?" |
| `network_propose(change)` | ✓ | ✓ | 제안 생성(방문자 대화에서 자기소개 → 제안) |
| `network_recent(n)` | ✓ | ✗ | 최근 접촉 |

방문자 모드에서는 `visibility=private` 노드는 **존재 자체를 부정하지도 긍정하지도 않는다**("그 부분은 제가 말씀드릴 수 없어요") — 프롬프트 규칙 + 도구 결과 필터.

## 프롬프트 주입 (매 턴)
- 오너 모드: 그래프 요약(노드 수, 상위 태그, 최근 접촉 5명 한 줄씩) ≤ 400 토큰 + 메시지에 언급된 이름과 매칭된 노드 카드.
- 방문자 모드: 방문자가 식별됐고 매칭 노드가 `on_request/public` 이면 그 노드 카드만.

## 시각화 (오너 콘솔 `/app/network`)
- 라이브러리: **`@cocorof/graphier` 1.4.0**(오너 소유 라이브러리, 2D·필터·미니맵·라이트 테마). 대안 d3-force 는 미채택.
- 뷰: 포스 레이아웃, kind 별 모양, 커뮤니티 색, 엣지 굵기=strength, 필터(kind/tag/visibility/기간), 검색 하이라이트, 노드 클릭 → 우측 상세 패널(편집·관계 추가·접촉 이력·비서에게 물어보기), 미니맵, 모바일은 리스트 뷰 우선 + 그래프 탭.
- 대량 편집: CSV 가져오기 미리보기, 중복 감지(이메일/이름+회사) 병합 제안.

## 시드 데이터
온보딩 위저드에서 "가까운 사람 3명" 입력을 권유(이름·관계·회사). 구글 연락처 연동 시 즉시 가져오기(연락처 ≤ 2,000, `visibility=private` 기본).

## 검증
- 단위: 경로·이웃·병합·가시성 필터.
- 계약: 방문자 모드 도구 결과에 private 노드가 절대 포함되지 않음(퍼저 테스트).
