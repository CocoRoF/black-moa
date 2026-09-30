# 13 · 오너 콘솔 UI (`/app`)

## 레이아웃
- 데스크톱: 좌측 네비(240px, 접힘 64px) + 본문. 모바일: 하단 탭바 5개(홈·채팅·인박스·비서·더보기) + 상단 헤더.
- 라우트 그룹 `app/(owner)/app/**`, 서버 컴포넌트에서 세션 확인(refresh 쿠키 존재 여부) → 없으면 `/login?next=`.
- 전역: 크레딧 잔액 배지(헤더), 알림 벨(인박스 new 수), 다크/라이트, ko/en.

## 화면 목록

| 라우트 | 화면 | 핵심 요소 |
|---|---|---|
| `/app` | 대시보드 | 비서 카드(상태·7일 대화·크레딧), 인박스 최신 5, 미답변 질문, 크레딧 게이지, 온보딩 체크리스트(프로필·지식·인맥·연동·공개 링크) |
| `/app/onboarding` | 위저드 | plan/06 3단계 + 프로필 기본 5문항 |
| `/app/agents` | 비서 목록 | 카드 그리드, 새 비서(플랜 한도) |
| `/app/agents/[id]` | 비서 상세 탭 | **대화 · 설정 · 공개 링크 · 인박스 · 통계 · 방문자 시뮬레이터 · 메모리** |
| `/app/agents/[id]/chat` | 오너 채팅 | 전체화면 채팅(plan/12 컴포넌트 재사용, 오너 모드 카드: 프로필 갱신 확인·사실 확인·인맥 제안 승인), 대화 목록 사이드(모바일 드로어), 첨부 업로드, 음성 |
| `/app/agents/[id]/settings` | 설정 | 페르소나(프리셋+슬라이더+미리보기), 모델 선택(단가 표시), 커스텀 지시문, 능력 토글, 공개 경계 정책 편집기(필드별 3단계 세그먼트, 주제 태그), 인사말·추천 질문, 테마·음성, 방문자 설정(보존·레이트·Turnstile), 위험 영역(일시정지/보관/삭제) |
| `/app/agents/[id]/links` | 공개 링크 | 링크 카드(코드·URL 복사·QR·상태·통계·라벨), 새 링크(자동/커스텀 핸들 검증), 만료/최대 대화 |
| `/app/agents/[id]/memory` | 메모리 브라우저 | 네임스페이스 탭(owner/shared/visitors), 노트 목록(카테고리·날짜), 노트 뷰/편집(마크다운), 핀·중요도, 검색, 사실 원장 표(가시성 편집·거부), "비서가 아는 것" 요약 |
| `/app/profile` | 내 정보 | 프로파일 폼(필드별 공개등급 인라인), 가용시간 위클리 그리드, 연락 규칙, 아바타 |
| `/app/knowledge` | 지식 | plan/09 |
| `/app/network` | 인맥 | plan/10 (그래프/리스트 토글, 상세 패널, 제안 탭, 가져오기) |
| `/app/integrations` | 연동 | plan/11 |
| `/app/inbox` | 인박스(전체) | 필터(비서·종류·상태), 아이템 상세(대화 전체 보기, 방문자 정보, 답장 초안 — 이메일 있으면 메일 발송, 없으면 링크 내 답신 게시), 미팅 요청 수락/거절(수락 시 캘린더 초안 v1.5) |
| `/app/conversations` | 대화 기록 | 오너/방문자 대화 검색·열람, 턴별 근거(도구 스팬) 펼치기, 크레딧 표시 |
| `/app/credits` | 크레딧 | 잔액·이번 달 사용 그래프(일별)·원장 표·플랜·충전(관리자 수동 안내 또는 Stripe 체크아웃 버튼) |
| `/app/notifications` | 알림 | 채널 카드(이메일 기본 = 계정 이메일, 텔레그램 봇 연결(코드 입력), 슬랙/디스코드 웹훅, 일반 웹훅 + 서명 비밀), 규칙 표(이벤트×채널×긴급도×방해금지), 테스트 발송, 발송 이력 |
| `/app/settings` | 계정 | 이름·언어·TZ·비밀번호·Google 로그인 연결·기기 세션·계정 삭제·데이터 내보내기(ZIP) |

## 컴포넌트 (재사용 우선)
- `components/chat/*`: `MessageList`(virtuoso), `MessageBubble`, `Markdown`(Geny ChatMarkdown 이식: GFM, 코드 복사, 인증 이미지 blob), `Composer`, `ToolChip`, `ThinkingPill`, `CardRenderer`(카드 종류별), `StreamingCursor`.
- `components/agent/*`: `PersonaEditor`, `ModelPicker`(카탈로그+단가), `DisclosureEditor`, `CapabilityToggles`, `PromptPreview`, `LinkCard`, `QrDialog`.
- `components/network/*`: `GraphView`(graphier), `NodePanel`, `EdgeEditor`, `ProposalList`, `ImportDialog`.
- `components/ui/*`: Button, Input, Textarea, Select, Switch, Tabs, Dialog, Sheet(모바일 바텀시트), Toast(sonner), Badge, Card, Skeleton, Segmented, Slider, Tooltip, DropdownMenu, Table, EmptyState.
- `lib/sse.ts`: fetch 스트림 파서 + 재개 + 취소 AbortController.
- `stores/`: `auth`, `chat`(대화별 메시지·스트림 상태), `ui`(사이드바·테마).

## 상태·데이터
- react-query 로 서버 상태(키 규약 `['agents', id]` 등), 뮤테이션 후 invalidate. 스트리밍은 zustand `chat` 스토어.
- 낙관적 업데이트: 메시지 전송, 인박스 읽음, 토글.

## 모바일 규약
plan/12 §모바일 요구사항 중 1·3·4·5·10·11 은 오너 콘솔 전체에 적용. 표는 카드 목록으로 접힘. 바텀시트로 편집.

## 접근성·i18n
모든 문구 `t()` 키. 폼 에러 인라인. 키보드 내비게이션.
