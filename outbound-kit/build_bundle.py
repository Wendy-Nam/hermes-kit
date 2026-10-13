"""Build a source distribution from an explicit allowlist; never include user setup or secrets."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
files = ['README.md', 'PLAN.md', 'VALIDATION.md', 'LICENSE', 'kit.py', 'wizard.html',
         'setup.example.json', '시작하기.command', '시작하기.bat', 'build_bundle.py',
         'sources.py', 'services.py', 'runtime_connect.py', 'vault_flow.py', 'installer.py', 'server_access.py',
         'engine_bootstrap.py', 'omh_setup.py', 'omniroute_setup.py']
files += ['paths.py', 'workflow.py', 'runtime_connect.py', 'docs_support.py',
          'operations.py', 'vault_sync.py', 'support.py', 'start.py',
          'bootstrap.command', 'bootstrap.ps1', 'test_bot.py', 'local_smoke.py',
          'privacy_audit.py', 'public_data_lens.py']
for folder in ('docs', 'agent-skill', 'pack', 'samples'):
    files.extend(str(p.relative_to(root)) for p in (root / folder).rglob('*')
                 if p.is_file() and (p.suffix in ('.md', '.json', '.py', '.csv')
                                    or (folder == 'samples' and p.suffix == '.html'))
                 and 'archive' not in p.parts and 'assets' not in p.parts
                 and '.build-v2' not in p.parts and 'output' not in p.parts)
target = root / 'dist/hermes-outbound-kit-0.1.zip'
target.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(set(files)):
        archive.write(root / name, 'hermes-outbound-kit/' + name)
print(target)
