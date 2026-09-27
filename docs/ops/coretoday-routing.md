# Core.Today와 OmniRoute 연결 검토

확인일: 2026-09-27. 운영 설정은 변경하지 않았고 생성·업로드·유료 추론 호출도 실행하지 않았다.

## 현재 확인된 상태

- 운영 Hermes의 `creator` 프로필에는 `coretoday` MCP가 활성화되어 있다. 주소는 `https://api.core.today/v1/mcp`이며 인증은 서버에 저장된 환경변수 참조를 사용한다.
- 기본 프로필에는 Core.Today MCP가 등록되어 있지 않다. 기본 채팅에서 자동으로 사용할 수 있다고 간주하면 안 된다.
- 저장된 인증정보로 MCP 초기화와 도구 목록 조회가 성공했다. 설치된 MCP SDK로도 `initialize`와 `list_tools`가 성공했다.
- 현재 인증정보에서 보이는 도구는 9개다: `search_models`, `get_model_schema`, `estimate_credits`, `create_prediction`, `get_prediction`, `cancel_prediction`, `create_upload_url`, `import_file_from_url`, `get_balance`.
- 지갑 조회 당시 상태는 `active`, 잔액은 935 credits였다. 시점 정보이며 향후 잔액을 보장하지 않는다. 계정 식별자와 인증정보는 이 문서에 기록하지 않는다.

## OmniRoute에 한 번만 연결할 수 있는가

운영 OmniRoute 3.8.51의 MCP는 라우터 자체의 관리·검색·라우팅 도구를 제공하는 **MCP 서버**다. 확인한 공식 문서와 실행 이미지에서 다른 서비스의 MCP를 upstream으로 등록하여 그대로 노출하는 일반 MCP 클라이언트/프록시 기능은 찾지 못했다. 설정 한 줄로 Core.Today MCP를 OmniRoute에 연결할 수 있다는 근거는 없다.

Core.Today의 LLM API와 MCP는 별개다. 공식 문서는 LLM 채팅을 `/llm/openai/v1`, `/llm/anthropic/v1`로 안내하며 MCP는 이미지·영상·음성 등의 모델 검색, 비용 예상과 prediction 실행에 사용한다. OmniRoute의 사용자 지정 OpenAI 호환 provider에 LLM 주소를 넣더라도 Core.Today MCP 도구가 생기는 것은 아니다. 현재 지갑 인증정보가 LLM API까지 허용하는지는 검증하지 않았다.

## 권장하는 최소 구성

한 Hermes 대화 안에서 모델 호출은 OmniRoute로, 미디어 작업 도구 호출은 Core.Today MCP로 연결한다. 현재는 `creator` 프로필에서 이 구성이 이미 가능하다. 사용자는 두 서비스를 각각 조작할 필요 없이 Hermes에 작업을 요청하면 된다.

기본 프로필 하나로 사용하려면 별도 선택 후 Core.Today MCP를 그 프로필에도 등록할 수 있다. 이는 기본 에이전트에 유료 생성 도구를 추가하는 변경이므로 현재 검토에서는 적용하지 않았다. 서버 저장 인증정보를 환경변수로 참조하고 토큰을 대화·문서·설정 본문에 복사하지 않는다.

생성 작업의 권장 순서는 모델 검색 → 입력 스키마 확인 → 비용 예상 → 요청한 작업 생성 → 상태 조회다. 사용자가 생성을 요청하지 않은 연결 점검은 초기화·도구 목록·잔액 조회까지만 수행한다. 별도 MCP 프록시 신규 개발은 현재 목표에 비해 운영 요소를 늘리므로 권장하지 않는다.

## 근거

- [Core.Today 공식 MCP 문서](https://console.core.today/docs/mcp): 인증, 도구, 과금 경계, 별도 LLM endpoint.
- [OmniRoute 3.8.51 MCP 서버 문서](https://github.com/diegosouzapw/OmniRoute/blob/release/v3.8.51/docs/frameworks/MCP-SERVER.md): OmniRoute 자체 도구 및 전송 방식.
- 운영 컨테이너의 프로필 설정과 MCP SDK 읽기 전용 호출. 비밀값은 출력하거나 문서에 저장하지 않았다.
