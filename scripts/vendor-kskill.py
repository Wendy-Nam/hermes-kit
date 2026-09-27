"""Vendor the selected NomaDamas/k-skill skills into seed/kskill (maintainer tool).

Usage: python3 scripts/vendor-kskill.py <k-skill checkout at the pinned commit>

Upstream SKILL.md files are stubs that fetch instructions at run time through an
unpinned `npx @nomadamas/k-skill@0`. The kit ships the pinned `instruction.md`
instead, with `npx ... exec|read` rewritten to the bundled helper files, so a
student's agent never downloads code from npm. Test files are not shipped.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

KIT = Path(__file__).resolve().parents[1]
SPEC = json.loads((KIT / 'plugins/kit-setup/kskills.json').read_text())
OUT = KIT / 'seed/kskill'
INSTALLED = '/opt/data/skills/k-skill'
CLI = r'npx -y @nomadamas/k-skill@0'


def selected():
    names = set(SPEC['common'])
    for skills in SPEC['kits'].values():
        names |= set(skills)
    for skill in list(names):
        names |= set(SPEC['requires'].get(skill, []))
    return sorted(names)


def rewrite(text, skill):
    def exec_(match):
        name, path = match.group(1), match.group(2)
        if not path.endswith('.py'):
            raise SystemExit(f'{skill}: non-Python helper {path} is not shippable')
        return f'python3 {INSTALLED}/{name}/{path}'
    text = re.sub(CLI + r' exec (\S+) (scripts/\S+)(?: --)?', exec_, text)
    text = re.sub(CLI + r' read (\S+) (\S+)', lambda m: f'cat {INSTALLED}/{m.group(1)}/{m.group(2)}', text)
    if 'npx' in text or 'k-skill@' in text:
        left = [line for line in text.splitlines() if 'npx' in line or 'k-skill@' in line]
        raise SystemExit(f'{skill}: unrewritten CLI use: {left[:3]}')
    return text


def stub_sections(stub):
    """Upstream's safety/legal sections, without the run-the-CLI-first instructions."""
    body = stub.split('\n---\n', 1)[1] if stub.startswith('---') else stub
    parts = re.split(r'(?m)^(?=## )', body)
    keep = [p for p in parts if p.startswith('## ') and not p.startswith('## Get the full instructions')]
    return ''.join(keep).replace('## Hard rules even without the CLI', '## Hard rules')


def vendor(source, skill, commit):
    src, dst = source / skill, OUT / skill
    meta = json.loads((src / 'skill.json').read_text())
    instruction = (src / 'instruction.md').read_text()
    extra = stub_sections((src / 'SKILL.md').read_text())
    body = (f"---\n{meta['frontmatter'].strip()}\n---\n\n"
            f"<!-- Vendored by hermes-kit from NomaDamas/k-skill@{commit[:12]} (MIT). "
            f"Helper files are in {INSTALLED}/{skill}/. -->\n\n"
            + rewrite(instruction, skill).rstrip() + '\n\n' + rewrite(extra, skill).rstrip() + '\n')
    files = {'SKILL.md': body.encode()}
    for sub in ('scripts', 'references'):
        for path in sorted((src / sub).rglob('*')) if (src / sub).is_dir() else []:
            if path.is_file() and not path.name.startswith('test_') and path.suffix not in ('.lock', '.pin'):
                rel = path.relative_to(src).as_posix()
                blob = path.read_bytes()
                files[rel] = rewrite(blob.decode(), skill).encode() if path.suffix == '.md' else blob
    if dst.exists(): shutil.rmtree(dst)
    for rel, blob in files.items():
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    manifest = {'schema_version': 'kit-component/v1', 'id': skill,
                'version': '1.' + SPEC['source']['date'].replace('-', '') + '.0',
                'files': {rel: hashlib.sha256(blob).hexdigest() for rel, blob in sorted(files.items())}}
    (dst / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def main():
    source = Path(sys.argv[1]).resolve()
    commit = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=True).stdout.strip()
    if commit != SPEC['source']['commit']:
        raise SystemExit(f'checkout is {commit}, kskills.json pins {SPEC["source"]["commit"]}')
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for skill in selected():
        vendor(source, skill, commit)
    shutil.copyfile(source / 'LICENSE', OUT / 'LICENSE')
    (OUT / 'NOTICE.md').write_text(
        f"# k-skill (vendored)\n\nSource: https://github.com/NomaDamas/k-skill at `{commit}` (MIT, see LICENSE).\n"
        "Selected skills only. SKILL.md is upstream `instruction.md` with the CLI calls rewritten to the\n"
        "bundled helpers; upstream test files are omitted. Regenerate with scripts/vendor-kskill.py.\n")
    print(f'vendored {len(selected())} skills from {commit[:12]}')


if __name__ == '__main__':
    main()
