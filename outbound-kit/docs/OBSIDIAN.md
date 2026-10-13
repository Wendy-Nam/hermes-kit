# Obsidian 단계별 아웃바운드 볼트

이 기능은 Obsidian의 기본 Markdown 링크만 사용합니다. Dataview 등 community plugin은 필요하지
않으며 Obsidian GUI를 자동 설치하지 않습니다. `vault_flow.py`는 노트와 실행 receipt를 만들 뿐,
메일이나 DM을 보내지 않습니다.

## 1. 볼트 초기화

macOS/Linux:

```sh
python3 vault_flow.py init --vault "$HOME/hermes-outbound-vault"
```

Windows PowerShell:

```powershell
py -3 vault_flow.py init --vault "$HOME\hermes-outbound-vault"
```

이미 파일이 있는 디렉터리를 사용할 수 있지만, 러너는 자신의 marker가 없는 동일 경로 파일을
덮어쓰지 않습니다. 심볼릭 링크 대상도 거부합니다.

## 2. 합성 fixture로 흐름 확인

```sh
python3 vault_flow.py run --vault "$HOME/hermes-outbound-vault"
python3 vault_flow.py status --vault "$HOME/hermes-outbound-vault"
```

`--input`을 생략하면 `pack/vault/seed/normalized-records.json`의 합성 데이터만 사용합니다.
생성되는 Draft는 규칙 기반 문구 템플릿이며 실제 AI 생성 결과가 아닙니다.

## 3. 실제 수집기의 정규화 결과 연결

```sh
python3 vault_flow.py run \
  --vault "$HOME/hermes-outbound-vault" \
  --input output/job-postings.json
```

입력은 다음 source envelope이어야 합니다.

```json
{
  "status": "ok",
  "source": "adapter-name",
  "records": [
    {
      "schema_version": "outbound-source/v1",
      "record_type": "job_posting",
      "source": "adapter-name",
      "source_id": "stable-source-id",
      "company": "확인된 회사명",
      "company_candidate": "원문 후보명",
      "company_confidence": "confirmed",
      "title": "공개 신호 제목",
      "url": "https://public.example/item",
      "published_at": "2026-10-13T09:00:00+09:00",
      "stack": ["example"],
      "evidence": {
        "source": "adapter-name",
        "url": "https://public.example/item",
        "source_id": "stable-source-id",
        "retrieved_at": "2026-10-13T10:00:00+09:00",
        "raw_sha256": "64자리 sha256"
      }
    }
  ],
  "errors": []
}
```

`empty`는 정상적인 0건 관측으로 receipt에 남지만 완료 workflow가 되지 않습니다. `blocked`,
`failed`, `invalid_response`도 오류를 보존하고 Account/Draft를 만들지 않습니다. `company`가 null인
레코드는 회사 식별 단계에서 멈추며, 후보명을 사람이 확인한 새 source envelope이 필요합니다.

## 4. Obsidian에서 열기

- macOS: Obsidian을 공식 사이트에서 설치한 뒤 **Open folder as vault**로 위 폴더를 선택합니다.
- Windows: Obsidian 공식 설치 프로그램 또는 Microsoft Store판을 설치한 뒤 **Open folder as vault**를
  선택합니다.
- Linux server: GUI 설치는 필요 없습니다. 볼트는 Markdown 산출물 폴더로 사용하고, 필요한 경우
  별도 동기화 절차로 desktop Obsidian에서 엽니다.

설치 파일의 서명/TLS/OS 보안 경고를 우회하지 마세요.

## 5. 단계별 산출물

1. `Inbox/Brief.md`: 사람이 제품·고객·제외 조건을 작성합니다. 각 run의 source 후보는
   machine-owned `Inbox/run-*-source.md`에 staging되며, 회사가 미확정이면 여기서 다음 작업을 안내합니다.
2. `Accounts/*.md`: 확인된 회사의 stable ID와 다음 문서 링크.
3. `Evidence/*.md`: source URL/ID, 수집 시각, raw digest 등 provenance.
4. `Scores/*.md`: 현재는 evidence field coverage만 계산합니다. 구매 가능성 점수가 아닙니다.
5. `Drafts/*.md`: evidence를 인용한 규칙 기반 초안 템플릿과 content hash.
6. `Review/*.md`: 사람 소유 승인 노트. 러너가 덮어쓰지 않습니다.
7. `Runs/*.md`: source 상태, 각 단계 결과, 다음 작업과 입력 digest receipt.
8. `Dashboard.md`: 모든 산출물 링크, 상태, 다음 작업.

## 6. 승인과 해시 무효화

Review 노트에서 내용을 검토한 뒤 다음 두 frontmatter 값을 직접 바꿉니다.

```yaml
decision: approved
approved_draft_hash: "Draft 노트의 draft_content_hash"
```

둘이 일치해야 승인입니다. 같은 account의 source 내용이 바뀌어 Draft hash가 달라지면 status/run은
`invalidated`로 보고합니다. 변경된 문구를 다시 검토하고 새 hash를 복사해야 합니다. `rejected`도
명시적으로 기록할 수 있습니다. 승인 여부와 무관하게 자동 발송은 없습니다.

## 7. 소유권과 재실행

- `Inbox`와 `Review`는 사람이 소유하며 create-only입니다.
- 생성 노트는 첫 줄의 machine-owned marker가 있는 경우에만 갱신됩니다.
- 생성 노트의 `user-notes` 블록 안에 쓴 내용은 재실행해도 보존됩니다.
- 동일한 입력은 같은 run/account/evidence ID를 사용하므로 중복 노트를 만들지 않습니다.
- marker가 사라졌거나 경로가 파일/심볼릭 링크로 바뀌면 안전하게 중단합니다.
