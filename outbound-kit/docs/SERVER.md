# Linux server installation support

키트를 서버의 사용자 소유 디렉터리에 복사합니다. README의 install/model/connect를
같은 사용자와 같은 --home으로 실행한 뒤 gateway를 foreground로 시작합니다.
Telegram, Discord 둘 다 선택했다면 각각 본인 메시지에 응답하는지 확인합니다.
토큰 확인 API 성공만으로 메시지 왕복 성공을 주장하지 않습니다.

장기 실행은 설치된 버전의 `hermes gateway --help`와 `hermes gateway install --help`로
공식 서비스 설치 지원을 확인합니다. HERMES_HOME을 위의 독립 경로로 설정한 상태에서
공식 서비스 설치를 진행하고, 서비스 정의가 그 경로를 사용하며 기존 Hermes 서비스를
대체하지 않는지 확인합니다. 충돌하면 설치를 멈추고 별도 서비스 이름을 사용합니다.
이 템플릿은 시스템 서비스나 재부팅 정책을 자동 변경하지 않습니다.

완료 기준: 서비스 시작 → 실제 대화 → 로그 확인 → 중지 → 재시작 → 재부팅 복구.
장기 자동화/크론은 수동 작업 1회 성공 이후 별도로 등록합니다.
desktop에서는 종료·절전 중 실행되지 않습니다.
