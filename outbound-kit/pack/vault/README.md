# Hermes Outbound Vault Template

이 폴더는 `vault_flow.py init`이 만드는 Obsidian 볼트의 계약과 합성 입력을 제공합니다.
Obsidian community plugin이나 Dataview에 의존하지 않습니다.

흐름은 다음과 같습니다.

`Inbox → Accounts → Evidence → Scores → Drafts → Review → Runs`

- `Inbox/Brief.md`, `Review/*.md`: 사람 소유. 생성 후 러너가 덮어쓰지 않습니다.
- `Dashboard.md`, `Accounts`, `Evidence`, `Scores`, `Drafts`, `Runs`: machine-owned marker가 있는 파일만 갱신합니다.
- machine-owned 노트의 `user-notes` 블록은 재실행해도 보존됩니다.
- Draft는 합성 규칙 기반 템플릿이며 실제 AI 생성 결과가 아닙니다.
- Review의 승인 해시는 현재 Draft 내용 해시와 일치해야 합니다. 초안이 바뀌면 승인이 무효화됩니다.
- 어떤 명령도 메일이나 DM을 발송하지 않습니다.

`seed/normalized-records.json`은 인터넷을 쓰지 않는 교육·테스트용 합성 source envelope입니다.
