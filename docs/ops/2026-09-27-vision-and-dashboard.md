# 운영 이미지 분석·대시보드 복구 (2026-09-27)

## 장애 증거

14:29 KST의 이미지 첨부는 Hermes 캐시에 도착했고, 이미지 인코딩도 성공했다. OmniRoute Vision Bridge 내부 요청이 AUTH_002 / 401로 실패했지만, 이미지를 읽지 못했다는 텍스트로 치환한 뒤 외부 요청은 200으로 반환했다. 따라서 Hermes 로그에는 분석 성공으로 기록됐지만 사용자에게 이미지 내용은 전달되지 않았다.

별도 프로세스에서 실행한 Hermes 비전 도구에서도 인증 누락을 발견했다. 제공자 클라이언트를 직접 해석할 때는 키가 맞았지만, 실제 비동기 보조 요청의 Authorization은 해당 키와 달랐다. auxiliary.vision에 base_url만 있고 key_env가 없는 경로였다.

## 수정

- 기본 설정 및 OmniRoute 비전을 사용하는 creator/coder/research/life/public 프로필의 auxiliary.vision.key_env를 OMNIROUTE_API_KEY로 명시했다. work 프로필의 별도 비전 설정은 변경하지 않았다.
- OmniRoute 컨테이너에 기존 유효한 추론 키를 OMNIROUTE_API_KEY로 전달했다. 권한을 넓힌 새 키는 만들지 않았다.
- 내부 인증과 combo/hermes-vision 지정만으로는 bridge의 자동 Gemini 재라우팅·시간 초과가 남았다. 최종적으로 modalityBridgeVisionEnabled=false로 중복 Vision Bridge를 껐다. Hermes 자체 vision_analyze → hermes-vision 콤보가 이미 이미지 분석을 담당한다. 실험 중 변경한 bridge 모델명은 원래 값으로 복원했다. 내부 키는 비활성 bridge에서는 사용되지 않는다.
- 로컬 127.0.0.1:20128 SSH 터널을 복구하고 로그인 페이지 HTTP 200을 확인했다. SSH keepalive를 적용했으나 컴퓨터 재시작 후 자동 실행하는 서비스는 설치하지 않았다.
- 사용자 요청으로 관리자 비밀번호를 관리 API에서 변경하고 새 비밀번호 로그인 200을 확인했다. 비밀번호는 이 문서에 기록하지 않는다.

## 백업

- Hermes: /opt/data/.backups/vision-fix-20260927T060559
- OmniRoute 환경: /docker/omniroute/backups/vision-bridge-20260927T060758Z
- OmniRoute 설정: /docker/omniroute/backups/vision-settings-20260927T060827.json

백업에는 인증 관련 설정이 포함될 수 있으므로 서버의 제한된 권한으로만 보관한다. 저장소에는 복사하지 않는다.

## 별도 개선 후보

OCR은 현재 동작하는 로컬 설치가 없다. 예전 EasyOCR 실행 스크립트는 가상환경이 없고 import 오류도 남아 있다. 한국어 PaddleOCR 모델을 별도 CPU 워커에서 검증하는 것이 후보이며, 이번 복구에서는 OCR을 새로 설치하지 않았다. Vision Bridge는 이미지를 텍스트로 바꾸는 추가 호출이므로 정밀한 글자 추출과 비용 최적화는 별도 평가가 필요하다.

## 실제 검증

최종 설정에서 특별한 우회 헤더 없이 실제 Hermes vision_analyze_tool에 합성 빨간 이미지를 입력해 success=true 및 정확한 답 “빨강”을 확인했다. 실제 사용자의 사적 이미지나 Discord 메시지는 시험에 사용하지 않았다.

OmniRoute 직접 경로에서도 전역 bridge off 및 우회 헤더 없는 상태로 합성 한국어 문구 “비전 점검 7392”와 빨간 사각형을 정확히 판독했다(HTTP200, 약54초). 내용 누락은 해결됐지만 지연 최적화는 남아 있다.

## 지연 재발 후 추가 조치

15시 실제 대화에서 자동 분석 두 건(총143초)에 동일 이미지 도구 재분석(101초·120초)이 겹친 것을 확인했다. 기본과 관련 5개 프로필은 vision timeout=30, configured_routes_only=true, fallback_chain=[]로 바꿨다. 인바운드 분석은 사용자 질문을 포함해 최대2개 병렬·전체30초 제한, 실패 후 같은 턴 재호출 억제로 수정했다. 이 패치는 학생 이미지의 Docker 빌드 단계에도 포함된다.


## 기본 프로필의 최종 비전 경로

OmniRoute를 통한 요청 지연이 남아 기본 프로필의 이미지 분석만 기존 ChatGPT 구독의 `openai-codex / gpt-6-luna`로 변경했다. 이전 OmniRoute base_url/key_env/api_key/api_mode 재정의는 제거했고 30초 제한과 구성 외 fallback 차단을 유지했다. 메인 대화 모델과 다른 프로필은 변경하지 않았다. 백업은 `/opt/data/config.yaml.bak-native-vision-20260927-080314`이다.

새 설정을 읽은 실제 `vision_analyze_tool`로 합성 한국어 세 줄을 **7.9초**에 정확히 판독했다. 이는 단일 합성 시험의 결과이며 모든 실제 이미지의 속도·정확도를 보장하지 않는다. 운영 기본 에이전트에는 이 경로를 적용하고, 학생에게 특정 구독 경로를 강제하지 않는다. 학생에게는 검증된 연결 선택과 공통 시간 제한 패치를 제공한다.
