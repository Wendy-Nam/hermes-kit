hermes-kit / clients/pc-sync — PC 옵시디언 동기화 스킬
====================================================

hermes-kit으로 VPS에 설치한 Hermes 에이전트와 내 컴퓨터의 Obsidian을
양방향으로 동기화합니다. 서버 설정은 전혀 건드리지 않습니다.

먼저 hermes-kit을 배포하고 Discord에서 /setup 을 끝내야 합니다.
이 폴더는 hermes-kit 저장소에 포함되어 있으므로 저장소를 따로 설치하지 않습니다.
  → https://github.com/Wendy-Nam/hermes-kit

사용법 (3단계)
--------------
0. 전체 흐름(준비물 → VPS 배포 → /setup → PC 동기화)을 먼저 보려면
   ONBOARDING.md 를 읽으세요. 이 폴더는 그중 PC 구간만 다룹니다.

1. clients/pc-sync 폴더 전체를 아래 위치에 두세요.

   맥:      ~/.claude/skills/hermes-vps-setup
   윈도우:  C:\Users\<내이름>\.claude\skills\hermes-vps-setup

2. 실행합니다 (모두 SSH + 셸만 있으면 됩니다).

   $ bash scripts/00-preflight.sh     # 키트가 배포됐는지 확인
   $ bash scripts/01-pc-sync.sh       # Syncthing·Obsidian 설치 + 볼트 2개 페어링
   $ bash scripts/02-verify.sh        # 실제 파일이 왕복하는지 확인

   2단계가 PC에 Syncthing을 자동으로 설치하고 로그인 시 자동 실행까지 등록합니다.
   Obsidian도 없으면 자동으로 설치합니다(윈도우는 설치 창이 뜹니다).

3. 끝나면 Obsidian에서 볼트를 엽니다.

   기본 위치: ~/HermesVaults
     · work      — 업무 노트
     · personal  — 개인 노트

   자동으로 안 열리면: Obsidian → 'Open folder as vault' → 위 폴더 선택

설정 변경하려면
--------------
setup.env.example 을 setup.env 로 복사해 고치세요. 없어도 동작합니다.

   LOCAL_VAULT_ROOT   볼트를 만들 위치 (기본 ~/HermesVaults)
   SSH_ALIAS          SSH 별칭 (기본 hermes)

주의
----
· 이 스킬은 볼트 2개(work·personal)를 만듭니다. 예전 버전의 단일 "wiki"
  폴더 구조는 더 이상 쓰지 않습니다.
· 모델·API 키 설정은 Discord /setup 이 담당합니다. 이 스크립트들은
  서버 설정을 변경하지 않습니다.
· 2단계(verify)는 실제로 서버에 시험 파일을 써서 PC에 도착하는지까지 봅니다.
  첫 실행은 1~2분 걸릴 수 있습니다.

문제 해결
----------
· "컨테이너를 찾지 못했습니다" → hermes-kit을 아직 배포하지 않았습니다.
· "Syncthing이 응답하지 않습니다" → docker logs 로 syncthing 서비스를 확인하세요.
· "공유 설정은 됐는데 파일이 안 옵니다" → 02-verify.sh 의 안내대로
  Syncthing 화면에서 '업로드 대기' 항목을 확인하세요.
