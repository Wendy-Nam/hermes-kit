"""User-facing setup errors with stable recovery instructions."""
from dataclasses import dataclass, field
import subprocess


@dataclass
class SupportError(ValueError):
    code: str
    phase: str
    user_message: str
    next_actions: list[str] = field(default_factory=list)
    docs_topic: str = 'troubleshooting'
    exit_code: int = 1

    def __str__(self):
        return self.user_message

    def as_dict(self):
        return dict(status='needs_user' if self.code.startswith('INPUT_') else 'blocked',
                    code=self.code, phase=self.phase, user_message=self.user_message,
                    next_actions=self.next_actions, docs_topic=self.docs_topic)


def explain_error(exc, phase):
    if isinstance(exc, SupportError):
        return exc
    if isinstance(exc, subprocess.TimeoutExpired):
        return SupportError('TIMEOUT', phase, '응답을 기다리는 시간이 길어 이번 단계만 멈췄어요.',
                            ['인터넷 연결과 제공자 상태를 확인한 뒤 같은 단계를 다시 실행하세요.'])
    if isinstance(exc, PermissionError):
        return SupportError('PERMISSION', phase, '선택한 파일이나 폴더를 사용할 권한이 없어요.',
                            ['본인 계정이 쓸 수 있는 폴더를 선택하고 설치를 재개하세요.'])
    if isinstance(exc, FileNotFoundError):
        return SupportError('MISSING_FILE', phase, '이 단계에 필요한 파일이나 프로그램을 찾지 못했어요.',
                            ['설정 파일과 설치 상태를 확인하세요.', '설치 스킬에 이 단계부터 재개해 달라고 요청하세요.'])
    return SupportError('STEP_FAILED', phase, '이 단계를 마치지 못했어요. 완료한 설정은 그대로 남아 있어요.',
                        ['진단 명령으로 마지막 완료 단계와 필요한 입력을 확인하세요.',
                         '설치 스킬에 오류 코드와 단계 이름을 알려주세요.'])
