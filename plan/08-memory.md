# 08 · 메모리 체계

## 목표

비서가 **오너에 대해 배운 것**을 잊지 않고, **방문자와 나눈 대화**를 오너의 것과 섞지 않으며,
검색은 한국어·영어 모두에서 강해야 한다. 로컬 임베딩 모델 서빙은 없다(원칙 2).

## 세 층

| 층 | 저장 | 내용 | 검색 |
|---|---|---|---|
| **L1 프로파일** | PG `owner_profiles` (구조화 JSON) | 이름·직함·소개·링크·가용시간·연락 규칙 등 고정 정보 | 검색 아님. 매 턴 프롬프트에 그대로 주입 |
| **L2 사실 원장(Fact Ledger)** | PG `facts` | 대화에서 증류된 원자 사실 (`subject, predicate, object, confidence, visibility, source_turn_id`) | 오디언스·가시성 필터 후 상위 N 주입 + 키워드/벡터 검색 도구 |
| **L3 메모리 볼트(Vault)** | 디스크 `/data/vaults/{agent_id}/{namespace}/notes/**.md`(MFSG `NoteStore`, YAML 프론트매터) + **geny-memory-adaptor(Synapse) SQLite** `synapse.db` | 자유 서술 노트: 대화 요약, 관찰, 오너가 직접 적은 메모 | Synapse 하이브리드(BM25 한/영 토크나이저 + 해시 임베딩 + 그래프 PPR + 온라인 랭커) |

> **구현 결정 D-25**: executor 의 메모리 스테이지(2 retriever·18·19)는 쓰지 않는다. 검색·핀·컨텍스트 블록은 `mfsg/memory/facade.py::AgentMemory` 가 호스트에서 직접 조립해 `RetrievedMemoryBlock` 에 넣는다. 히스토리는 PG `messages` 가 정본이고 런타임 재구성 시 최근 40개를 `state.messages` 로 복원한다.

**임베딩 정책 (결정)**: L3 검색은 Synapse 의 **0-API 로컬 해시 임베딩**을 그대로 쓴다(numpy 만 필요, 모델 서빙 아님, 테넌트당 메모리 ~0 — 프로세스 공유 테이블). API 임베딩(OpenAI `text-embedding-3-small`)은 **지식(plan/09)에서 pgvector** 로 쓰고, Synapse 에는 선택적으로 `teacher_vec` 로 넘겨 유휴 시 `distill()` 로 기하를 근사시킨다. 이유: 메모리 노트는 짧고 수가 적어 BM25+그래프가 지배적이고, 검색 경로에서 네트워크 호출을 락 안에서 하지 않기 위해서다(어댑터 rwlock 설계 의도 존중).

## 네임스페이스 (오디언스 격리)

```
/data/vaults/{agent_id}/
  owner/        # 오너 대화·오너가 준 정보. 오너 모드에서만 읽기/쓰기
  visitors/     # 방문자 대화 관찰. 방문자 모드에서 읽기/쓰기 (방문자 스레드 태그로 구분)
  shared/       # 오너가 "공개 지식"으로 승격한 노트. 양쪽 읽기, 오너만 쓰기
```

- 오너 모드 검색 범위: `owner + shared + visitors`(방문자가 무엇을 물었는지 오너는 봐도 됨).
- 방문자 모드 검색 범위: `shared + visitors[thread=현재 방문자]`. **owner 네임스페이스는 절대 열리지 않는다**(도구 스코프+경로 가드 이중).
- 각 네임스페이스는 별도 `synapse.db` (별도 `SynapseMemory` 인스턴스). 임베더 테이블은 프로세스 공유라 비용 낮음.

## 볼트 파일 규약 (MFSG NoteStore)

`{namespace}/notes/{category}/{YYYY-MM-DD}/{slug}-{4hex}.md`, YAML 프론트매터(`title, category, tags, pinned, importance, created, updated, source, meta`) + 본문. 방문자 노트는 `meta.visitor_id` + 태그 `visitor:<id>` 로 스레드 격리.
카테고리: `conversations`(턴 요약), `observations`(비서가 관찰한 오너 취향/패턴), `decisions`, `people`(인맥 노트 — 네트워크 노드와 `network_node_id` 로 링크), `inbox`(방문자가 남긴 메시지 요약).

## 쓰기 경로

1. **턴 종료 후 증류(post-turn distill)** — 워커 잡 `memory.distill(turn_id)`:
   - 저비용 모델(관리자 지정 `distill_model`, 기본 claude haiku 계열)로 턴을 읽고 JSON 산출:
     `{facts:[{subject,predicate,object,confidence,visibility_hint}], note:{title,body,tags}|null, people:[{name,relation_hint}]}`.
   - facts → `facts` 테이블(중복은 `(agent_id, subject, predicate)` 유사도로 병합, 모순 시 신뢰도 낮은 쪽 `superseded_by`).
   - note → 볼트 노트 생성 + Synapse `index()`.
   - people → 네트워크 제안(`network_proposals`) — 오너 승인 전엔 그래프에 안 들어감(plan/10).
   - 방문자 턴은 `visitors` 네임스페이스에만, `visibility=visitor_private` 사실만 생성.
2. **오너 명시 저장** — 오너 모드 도구 `memory_remember(text, kind)` 즉시 노트+색인. `memory_forget(query)` 는 노트 목록을 보여주고 확인 후 삭제(제안→확인 2단계).
3. **오너 콘솔 편집** — 메모리 브라우저에서 노트 CRUD·핀·중요도. 삭제는 볼트 파일 + Synapse `remove()` + params text 정리(어댑터 `remove_many` 가 본문 params 를 남기는 문제가 있어 MFSG 쪽에서 `remove()` 루프 사용 — 감사 발견).

## 읽기 경로 (파이프라인 단계, plan/07 §메모리)

1. 프로파일(L1) 전체 주입(≤1.5k 토큰, 초과 시 필드 우선순위로 절단).
2. 사실(L2): 가시성 필터 → 최근성·신뢰도 상위 40개 + 쿼리 키워드 매칭 20개 주입.
3. 볼트(L3): 사용자 메시지 + 직전 2턴 요약을 쿼리로 Synapse `search(top_k=8)` → 노트 본문(각 ≤600자) 주입. `MemoryBusy` 시 빈 결과로 강등(턴 차단 금지).
4. 도구: `memory_search(query)`, `memory_read(note_id)`, `memory_remember`, `memory_forget`(오너 전용), `facts_search`.
5. 학습 루프: 모델이 답변에 인용/사용한 노트(도구 `memory_read` 호출 또는 `[[note]]` 인용) → 턴 종료 시 `learn(positives, negatives)`; 검색된 것만으로는 보상 없음(Geny `MemoryUsageTracker` 규범 이식).

## 워밍업·준비 게이트

- 에이전트 세션 첫 로드 시 Synapse 오픈 + `manifest()` 대 노트 디렉터리 차분 → 스테일만 `index_batch`. 백그라운드 태스크, 8초 bounded wait 후 턴 진행(미완료면 키워드 폴백 + "기억을 불러오는 중" 노티스 없음 — 방문자에겐 보이지 않게).
- 유휴 15분 → 세션 evict(Synapse close). 프로세스당 동시 오픈 볼트 상한 200(LRU).

## 보존·삭제(개인정보)

- 오너가 에이전트 삭제 → 볼트 디렉터리 전체 삭제 + facts/turns 삭제(하드).
- 방문자 대화 보존 기간: 오너 설정(기본 90일). 워커 잡 `retention.sweep` 가 만료 스레드의 노트·사실·turns 삭제.
- 계정 삭제 → 전 에이전트 연쇄.

## 관리자 노브

`memory.distill_model`, `memory.distill_enabled`, `memory.max_open_vaults`, `memory.idle_evict_minutes`.

## 재사용 지도

- `geny-memory-adaptor==1.11.1` 그대로 의존(numpy-only). `SynapseMemory.open/index/index_many/search/search_join/learn/trust_feedback/contradictions/manifest/remove`.
- Geny `service/memory/synapse_handle.py`(VectorHandle 어댑터) · `usage_tracker.py`(학습 루프 클로저) · `manager.py::_vector_initialize_and_index`(차분 리컨사일) 를 MFSG `memory/` 로 이식(경로·네임스페이스 계층 추가).
- BLAS 스레드 1 고정 + 포크 후 매트멀 웨지 가드 테스트 이식.
