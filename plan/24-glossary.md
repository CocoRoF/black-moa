# 24 · 용어집

| 용어 | 정의 |
|---|---|
| **MFSG** | my-first-secretary-geny. 이 제품. |
| **관리자(Admin)** | 최초 가입 계정. `role=admin`. 인프라·프로바이더·요금표 설정 권한. 단 1명(승격 가능). |
| **오너(Owner)** | 비서 에이전트를 소유한 가입자. `role=user`. |
| **방문자(Visitor)** | 공개 링크로 비서와 대화하는 비회원. 익명 `visitor_token` 으로 식별. |
| **비서(Secretary) / 에이전트(Agent)** | 오너가 만든 에이전트 인스턴스. `agents` 테이블 1행. |
| **공개 링크(Share Link)** | `https://<domain>/{code}`. `share_links` 1행. 한 에이전트에 여러 개 가능(채널별 추적). |
| **코드(code)** | 공개 링크 경로 조각. 자동(8자 base32 소문자, 혼동 문자 제거) 또는 커스텀 핸들(3~32자). |
| **오디언스(Audience)** | 턴을 발화한 주체 유형: `owner` \| `visitor`. 파이프라인 스코프의 1차 키. |
| **공개 경계(Disclosure Policy)** | 방문자에게 무엇을 말해도 되는지의 정책. 3분류: public / on_request / private. |
| **페르소나(Persona)** | 비서의 이름·말투·언어·성격·인사말·추천 질문 묶음. 프리셋 + 사용자 커스텀. |
| **하네스(Harness) / 파이프라인** | geny-executor 위에 정의한 MFSG 단일 매니페스트 파이프라인. `plan/07`. |
| **프로파일(Profile)** | 오너의 구조화된 자기 정보(이름·직함·소개·링크·가용시간 등). `owner_profiles`. |
| **사실 원장(Fact Ledger)** | 대화에서 증류된 구조화 사실. 출처·신뢰도·공개등급 보유. `facts`. |
| **지식(Knowledge)** | 업로드 파일·노트·FAQ 를 청크·임베딩한 검색 대상. `knowledge_*`. |
| **네트워크(Network)** | 오너의 인맥 그래프. 노드(`network_nodes`)·엣지(`network_edges`). |
| **연동(Connection)** | 외부 계정 OAuth 연결. `connections`. v1: google. |
| **메모리 볼트(Vault)** | 에이전트별 geny-memory-adaptor 저장 디렉터리. 오디언스별 네임스페이스. |
| **턴(Turn)** | 사용자 메시지 1개에 대한 에이전트 응답 1회. `turns` 1행. 크레딧 청구 단위. |
| **대화(Conversation)** | 턴들의 스레드. 오너 대화 / 방문자 대화. `conversations`. |
| **인박스(Inbox)** | 오너 콘솔에서 방문자 대화·남긴 메시지·요청을 보는 화면. |
| **크레딧(Credit)** | 사용량 화폐. 1 크레딧 = 관리자가 정한 기준 단가(기본 USD 0.001 상당). `credit_ledger`. |
| **플랜(Plan)** | 월 크레딧 지급·한도 묶음. free / pro / custom. |
| **프로바이더(Provider)** | 외부 API 공급자. LLM: claude_code·anthropic·openai·gemini. STT/TTS: openai·google·elevenlabs. 임베딩: openai·gemini·voyage. |
| **모델 카탈로그(Model Catalog)** | 관리자가 노출을 켠 모델과 크레딧 단가 표. |
| **알림 채널(Channel)** | email / webhook / telegram / slack / discord. `notification_channels`. |
| **이벤트 봉투(Envelope)** | SSE 로 보내는 `{seq, type, data}` JSON. `plan/18`. |
| **커서 리플레이** | 끊긴 스트림을 `after=seq` 로 재개하는 방식. |
| **워커(Worker)** | 백그라운드 작업 컨테이너(색인·알림·연동 동기화·다이제스트). PG 잡 큐. |
