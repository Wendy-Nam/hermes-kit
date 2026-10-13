#!/usr/bin/env python3
"""One guided entry point for configuration, setup, and resume."""
import argparse
import importlib.util
from pathlib import Path
import sys

import installer
from support import SupportError, explain_error

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description='쉬운 질문으로 설치를 시작하거나 이어갑니다.')
    parser.add_argument('--config', default=str(ROOT/'setup.json'))
    parser.add_argument('--offline', action='store_true', help='계정 없이 첫 샘플부터 확인')
    parser.add_argument('--no-launch', action='store_true')
    args = parser.parse_args(argv)
    config = Path(args.config).expanduser().absolute()
    try:
        if not config.exists():
            if not sys.stdin.isatty():
                raise SupportError('INPUT_QUESTIONS','prepare','설치할 환경을 먼저 알려주세요.',
                                   ['AI 설치 스킬이 필요한 질문을 받아 설정을 만들 수 있습니다.',
                                    '본인의 터미널에서는 start.py를 실행하면 질문이 시작됩니다.'])
            source = ROOT/'agent-skill/hermes-outbound-setup/scripts/prepare.py'
            spec = importlib.util.spec_from_file_location('outbound_prepare',source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            data = module.collect_config()
            module.create_config(config,data)
            print('답변을 저장했어요. 같은 설정으로 설치를 이어갑니다.')
            action = 'setup'
        else:
            print('저장된 설정을 확인하고 완료한 단계부터 이어갑니다.')
            action = 'resume'
        forwarded = [action,'--config',str(config)]
        if args.offline: forwarded.append('--offline')
        if args.no_launch: forwarded.append('--no-launch')
        return installer.main(forwarded)
    except KeyboardInterrupt:
        print('여기서 멈췄어요. 다음에 다시 열면 완료한 설정으로 이어갑니다.')
        return 130
    except (ValueError,OSError,EOFError) as exc:
        error = explain_error(exc,'prepare')
        print(error.user_message)
        for action in error.next_actions: print(action)
        return 2 if error.code.startswith('INPUT_') else 1


if __name__=='__main__':
    raise SystemExit(main())
