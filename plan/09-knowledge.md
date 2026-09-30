# 09 · 지식 주입 (사용자 정보 파일 · 노트 · FAQ · URL) — pgvector RAG

## 목표
오너가 올린 문서(이력서·포트폴리오·회사소개·계약 템플릿·FAQ)를 비서가 정확히 인용해 답한다. 방문자에게는 `visibility=public` 문서만.

## 입력 종류
| kind | 입력 | 처리 |
|---|---|---|
| `file` | PDF·DOCX·PPTX·XLSX·MD·TXT·HTML ≤ 25 MB | 텍스트 추출(아래) → 청크 → 임베딩 |
| `note` | 콘솔 에디터 자유 텍스트 | 즉시 청크·임베딩 |
| `faq` | 질문/답 쌍(일괄 CSV 가능) | 질문 임베딩, 답은 그대로 |
| `url` | 웹 페이지 1개 | 서버 fetch(SSRF 가드, 사설망 차단) → readability 추출 → 청크 |

텍스트 추출: PDF `pypdf`(+ 스캔본은 미지원 안내), DOCX `python-docx`, PPTX `python-pptx`, XLSX `openpyxl`(시트별 표→행 텍스트), HTML `readability-lxml`+`bs4`, MD/TXT 그대로. (Geny 의 contextifier 는 무거워 미채택; v2 에서 위치 메타 강화 시 검토.)

## 청킹
- 헤딩 인식 분할 → 목표 700 토큰, 최대 1,000, 오버랩 100 토큰(tiktoken `cl100k_base`). 청크당 UTF-8 ≤ 7,000 바이트 하드캡(임베딩 8k 토큰 한도 안전, Geny 교훈).
- 각 청크: `heading`(상위 헤딩 경로), `page`(PDF), `ordinal`. 문서당 최대 1,500 청크(초과 시 실패 + 안내).

## 임베딩
- 관리자 설정 `embedding.provider/model`(기본 openai `text-embedding-3-small`, 1536). 대안 gemini `text-embedding-004`(768 — 차원 다르면 컬럼 재생성 마이그레이션 필요하므로 **관리자 변경 시 전체 재임베딩 잡** + 경고).
- 배치 96청크/호출, 워커 잡 `knowledge.index(document_id)`. 실패 시 `status=failed` + `error`(키 없음 → `embedding_key_missing` 코드로 409 매핑, 관리자에게 안내).
- 비용: `usage_events(kind=embedding)` → 크레딧 차감(단가 관리자 설정, 기본 소액).

## 검색 (`services/knowledge/search.py`)
하이브리드: `hnsw` 코사인 top 20 ∪ `tsvector`(한국어는 `simple` 설정 + 트라이그램 보조) top 20 → RRF 융합 → 상위 k. 필터: `owner_id`, `visibility`(방문자 = public), `agent_id in (null, 현재)`. FAQ 는 질문 임베딩 코사인 ≥ 0.85 면 답을 그대로 "정답 후보" 로 최상단.

반환 청크 `{document_id, title, heading, page, text(≤ 1,200자), score}`.

## 파이프라인 연결 (plan/07)
- **사전검색**: 매 턴 사용자 메시지로 `search(k=3)` → `RetrievedMemoryBlock` 에 "참고 자료" 로 주입(합계 ≤ 1.8k 토큰). 점수 < 0.25 면 주입 안 함.
- **도구**: `knowledge_search(query, k≤8)`, `knowledge_read(document_id, page|heading)`(문서 일부 8k자), `knowledge_list`(오너).
- 인용 규약: 프롬프트가 "자료를 근거로 답할 때 문서 제목을 언급" 지시. 방문자 모드에서 문서 원문 전체 노출 금지(`knowledge_read` 는 청크 단위).

## 오너 콘솔 `/app/knowledge`
- 업로드 드롭존(진행률·상태 폴링 `processing → ready|failed`), 문서 카드(제목·크기·청크 수·가시성 토글·에이전트 지정·삭제), 노트 에디터, FAQ 표(인라인 편집·CSV 가져오기), URL 추가.
- 검색 미리보기: 질문 입력 → 상위 청크와 점수(비서가 무엇을 볼지 확인).
- 용량 게이지(플랜 `max_knowledge_mb`).

## API
```
GET  /api/knowledge/documents?kind=&status=
POST /api/knowledge/documents (multipart file | {kind:note|faq|url, ...})
GET  /api/knowledge/documents/{id} · PATCH(title, visibility, agent_id) · DELETE
GET  /api/knowledge/documents/{id}/chunks?page=
POST /api/knowledge/documents/{id}/reindex
GET  /api/knowledge/search?q=&k=&audience=
GET/POST/PATCH/DELETE /api/knowledge/faqs  · POST /api/knowledge/faqs/import (csv)
GET  /api/knowledge/usage
```

## 저장
원본 파일 `/data/uploads/{owner_id}/knowledge/{document_id}.{ext}`(sha256 기록). 삭제 시 파일+청크 삭제. 계정 삭제 시 디렉터리 삭제.

## 미답변 질문 루프
방문자 턴에서 비서가 `unknown_policy` 로 "모른다/전달하겠다" 응답하면(도구 `notify_owner(kind=question_unanswered)` 또는 응답 분류) `inbox_items(kind=question_unanswered)` 생성 → 오너 콘솔에서 [답 가르치기] → FAQ 로 저장 → 다음부터 답변. 이것이 지식 성장 루프.
