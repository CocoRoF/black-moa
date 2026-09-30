# 12 · 공개 채팅 경로 `/{code}` 와 모바일 특화 채팅 UI

## 경로 · 코드

- 정식 URL: `https://mfsg.hrletsgo.me/{code}`. 루트 레벨 동적 세그먼트 `app/[code]/page.tsx`.
- 예약어(정적 라우트가 우선하지만 코드 생성 시에도 금지): `app, admin, api, login, signup, health, static, _next, c, s, about, terms, privacy, favicon.ico, manifest.webmanifest, robots.txt, sitemap.xml`.
- 코드 형식:
  - 자동: 8자, 알파벳 `abcdefghjkmnpqrstuvwxyz23456789`(혼동 문자 i/l/o/0/1 제외), `secrets.choice`.
  - 커스텀 핸들: `^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$`, 예약어 제외, 전역 유일, 대소문자 무시.
- 한 에이전트에 링크 여러 개(채널별: 명함/이메일/SNS). 링크마다 통계·비활성화·만료·최대 방문자 대화 수.
- `share_links.status`: `active | paused | expired | revoked`. 비활성 시 페이지는 "지금은 자리를 비웠어요" 정적 화면(200).

## 서버 컴포넌트 흐름

1. `app/[code]/page.tsx`(RSC) → `GET {INTERNAL_API_URL}/api/public/links/{code}` → `{agent:{name, avatar_url, greeting, suggested_questions, theme, owner_display_name, voice_enabled, language}, link:{status}}`.
   404 → `notFound()`. paused → Paused 뷰.
2. `generateMetadata`: OG 타이틀 "`{비서이름}` · `{오너이름}`의 비서", OG 이미지는 `/api/public/links/{code}/og.png`(백엔드가 Pillow 로 생성·캐시).
3. 클라이언트 `PublicChat` 마운트 → `visitor_token` 확보(아래) → 최근 대화 복원 → 스트리밍 채팅.

## 방문자 식별

- `POST /api/public/links/{code}/visitor` → `{visitor_token(JWT, 90d), conversation_id}`; 토큰은 `localStorage['mfsg:v:{code}']`. 재방문 시 같은 대화 이어짐(오너 설정 `continue_conversations` 기본 on).
- 방문자가 선택적으로 이름/이메일/메모 입력("제가 누군지 알려주기" 시트) → `visitors.display_name/email`. 비서가 대화 중 자연스럽게 물어 `visitor_identify` 도구로 저장하기도 함.
- 봇/남용: 링크별 레이트리밋(분당 10턴/방문자, 시간당 200턴/링크), 오너 설정으로 Cloudflare Turnstile 켜기 가능(사이트키는 관리자 설정).

## 화면 (모바일 우선)

```
┌──────────────────────────────┐  ← safe-area-top
│ ◉ 비서 이름     ● 온라인   ⋮ │  헤더 44px, sticky, 뒤로가기 없음(딥링크 진입)
├──────────────────────────────┤
│  [비서 아바타] 안녕하세요…    │  메시지 리스트 (virtuoso, 하단 고정)
│                              │  - 비서 말풍선 좌측, 방문자 우측
│              [질문 칩][칩]   │  - 첫 화면: 인사말 + 추천 질문 칩 2~4개
│  ⋯ 생각 중 (툴 한줄 요약)     │  - 스트리밍 텍스트 델타, 마크다운, 코드 복사
│                              │  - "메시지 남기기" 카드, 미팅 요청 카드(구조화 응답)
├──────────────────────────────┤
│ [🎤] [ 메시지 입력…      ] [➤]│  컴포저: 자동 높이(최대 5줄), 음성 버튼, 전송
└──────────────────────────────┘  ← safe-area-bottom
```

### 모바일 요구사항 (전부 구현·검증 대상)
1. **뷰포트**: `height: 100dvh`, `viewport-fit=cover`, `env(safe-area-inset-*)` 4방향 패딩, `interactive-widget=resizes-content` 메타.
2. **키보드**: `window.visualViewport` `resize/scroll` 리스너로 컴포저를 키보드 위에 고정(iOS Safari 15+ 보정, `--kb-offset` CSS 변수). 키보드 열릴 때 리스트 하단 유지.
3. **iOS 줌 방지**: 입력 `font-size: 16px` 이상(`@layer base`), `maximum-scale=1` 은 접근성 위배라 쓰지 않음.
4. **스크롤**: 리스트만 스크롤(`overscroll-behavior: contain`), body `overflow: hidden`, 새 메시지 도착 시 하단에 있을 때만 자동 스크롤, 아니면 "↓ 새 메시지" 플로팅 버튼.
5. **터치**: 탭 타깃 ≥44px, `-webkit-tap-highlight-color: transparent`, 메시지 **롱프레스** → 복사/공유 시트(우클릭 아님), 스와이프로 시트 닫기.
6. **네트워크**: SSE `fetch` 스트리밍, 끊기면 `after=seq` 커서 리플레이로 재개, `visibilitychange`(잠금 해제/탭 복귀) 시 진행 중 턴 재구독(Geny CommandTab 패턴 이식). 오프라인 배너.
7. **PWA**: `manifest.webmanifest`(name=비서 이름 동적 → 링크별 manifest 라우트 `/[code]/manifest.webmanifest`), `theme_color`, 아이콘 192/512(오너 아바타 기반 생성), 서비스워커는 셸 캐시만(대화는 캐시 금지). iOS `apple-mobile-web-app-*` 메타. "홈 화면에 추가" 힌트 배너(2회 방문 후 1회).
8. **성능**: 초기 JS ≤ 180 kB gz(공개 채팅 번들은 오너 콘솔과 분리된 라우트 그룹, 무거운 의존 lazy), 폰트 Pretendard Variable subset + `font-display: swap`, LCP 는 인사말 텍스트. Lighthouse 모바일 ≥90.
9. **음성**: 마이크 버튼 → MediaRecorder(webm/opus, iOS 는 mp4/aac) → `POST /api/public/.../stt` → 텍스트가 컴포저에 채워짐(전송 전 확인). 답변 TTS: 문장 단위 스트림 재생(Geny `audioManager` 의 iOS 전략 이식: `decodeAudioData` + `AudioBufferSourceNode`, 제스처로 `resume()`). 토글은 헤더 ⋮ 메뉴.
10. **다크/라이트**: `prefers-color-scheme` + 오너 테마 색 1개(`theme.accent`)로 말풍선·버튼 강조.
11. **접근성**: 라이브 리전(`aria-live=polite`)으로 스트리밍 답변 알림, 포커스 순서, 축소 모션 존중.
12. **i18n**: 방문자 브라우저 언어(ko/en) 로 UI 문구, 비서 답변 언어는 페르소나 설정(자동=방문자 언어 따라감).

### 구조화 카드
비서가 특정 도구를 부르면 텍스트 대신 카드가 렌더된다(이벤트 `card`).
- `leave_message` 카드: "OO에게 메시지 남기기" 폼(이름·연락처·내용) → `POST /api/public/.../messages` → 오너 알림.
- `meeting_request` 카드: 희망 일시 후보 3개 + 목적 → 인박스 "요청".
- `contact_card`: 오너가 공개 허용한 연락 수단 버튼(메일/링크).
- `file` 카드: 오너가 공개 지정한 파일(포트폴리오 PDF 등) 다운로드 버튼(서명 URL 10분).

### 상태 화면
- 크레딧 소진: "지금은 잠시 쉬고 있어요. 메시지를 남겨주시면 전달할게요" + 메시지 남기기 폼(LLM 호출 없이 동작).
- 레이트리밋: "잠시 후 다시 시도" 토스트, 카운트다운.
- 링크 만료/취소: 정적 안내.

## 데스크톱 확장
같은 라우트, `md:` 이상에서 최대 폭 720px 중앙 카드 + 배경 그라데이션 + 좌측 오너 프로필 패널(공개 항목만).

## API (plan/18 상세)
- `GET  /api/public/links/{code}`
- `POST /api/public/links/{code}/visitor`
- `GET  /api/public/conversations/{cid}/messages?before=`
- `POST /api/public/conversations/{cid}/turns` → SSE
- `GET  /api/public/conversations/{cid}/turns/{tid}/events?after=seq` (리플레이)
- `POST /api/public/conversations/{cid}/turns/{tid}/cancel`
- `POST /api/public/conversations/{cid}/messages` (메시지 남기기), `/meeting-requests`
- `POST /api/public/conversations/{cid}/stt`, `POST …/tts`
- `PATCH /api/public/visitors/me` (이름/이메일)

전부 `Authorization: Bearer <visitor_token>`.
