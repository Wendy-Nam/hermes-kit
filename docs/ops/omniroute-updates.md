# OmniRoute 업데이트

학생용 심화 Compose는 `diegosouzapw/omniroute:next`를 기본으로 사용한다. 특정 이미지 digest로 고정하지 않으며, `pull_policy: always`로 설치·재배포 때 최신 이미지를 확인한다. `docker restart`만으로 새 이미지를 설치하지는 않는다.

공식 채널은 다음과 같다.

| 채널 | 내용 |
|---|---|
| `latest` | 가장 최근에 게시된 안정판 |
| `next` | 활성 release 브랜치의 프리릴리스 빌드 — 키트 기본값 |
| `main` | main 개발 브랜치 빌드 |
| `next-web` | 브라우저가 필요한 웹 세션 제공자용 next 이미지 |

`next`는 아직 안정판에 들어가지 않은 제공자 수정 등을 받는 대신 호환성이 달라질 수 있다. 최신 이미지가 모든 무료 모델의 현재 사용 가능 여부를 보장하지는 않는다. 키트의 자동 연결 UI는 현재 Gemini·OpenAI·Anthropic API 연결만 지원하며, 다른 제공자는 OmniRoute 대시보드에서 별도로 구성한다.

## 기존 설치 업데이트

1. 기존 OmniRoute의 이미지 digest를 기록하고 컨테이너를 중지한 상태에서 데이터 볼륨 전체를 백업한다. 이 볼륨에는 계정 인증정보가 있으므로 개인 저장소에 보관한다. Hermes 키트의 노트 백업은 이 볼륨을 포함하지 않는다.
2. Hostinger Docker Manager에서 기존 **OmniRoute 프로젝트**의 Compose를 최신 파일로 교체하고 새 이미지를 받아 재배포한다. 기존 프로젝트와 볼륨을 유지한다.
3. 대시보드 로그인, 기존 제공자·콤보·키 보존, Hermes 보조 모델 실제 응답을 확인한다. 신규 연결은 `/setup`의 OmniRoute 연결 기능으로 검증한다.

CLI에서는 해당 Compose 프로젝트의 기존 환경변수와 프로젝트 이름을 유지하여 실행한다.

```sh
docker compose -f advanced/docker-compose.omniroute.yml pull omniroute
docker compose -f advanced/docker-compose.omniroute.yml up -d omniroute
```

문제가 생기면 `KIT_OMNIROUTE_IMAGE`를 기록해 둔 이전 이미지 digest로 지정하여 재배포한다. 데이터 형식이 변경된 업데이트라면 이전 이미지와 함께 업데이트 전 데이터 백업도 복원해야 한다. 자동 업데이트 크론은 설치하지 않는다.

2026-09-27 검증 기준은 3.8.51 이미지였으며, 이후 `next`에 올라오는 모든 빌드가 검증된 것은 아니다.

출처: [공식 Docker 가이드](https://github.com/diegosouzapw/OmniRoute/blob/release/v3.8.51/docs/guides/DOCKER_GUIDE.md).
