"""Regression tests for bin/hermes-kit-deploy.sh CLI flag parsing, SSH quoting, and compose invocations."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SH = REPO_ROOT / "bin" / "hermes-kit-deploy.sh"


def _make_stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class DeployCliTests(unittest.TestCase):
    def test_post_command_flags_and_env_file_and_pull_never(self):
        with tempfile.TemporaryDirectory() as td:
            stub_dir = Path(td)
            log_file = stub_dir / "docker.log"
            _make_stub(
                stub_dir,
                "docker",
                f"""
printf '%s\\n' "$*" >> "{log_file}"
case "${{1:-}}" in
  ps) echo "hermes-test\tghcr.io/wendy-nam/hermes-kit:0.23.3-k19" ;;
  exec) exit 0 ;;
  build|compose) exit 0 ;;
esac
""",
            )
            env = dict(os.environ)
            env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
            env["KIT_OMNIROUTE_PASSWORD"] = "test pass $HOME; rm -rf /"
            env.pop("DISCORD_BOT_TOKEN", None)

            # Flags placed AFTER `install` (matching README.md examples) must be honored.
            proc = subprocess.run(
                [str(DEPLOY_SH), "install", "--with-omniroute", "--build-local"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            calls = log_file.read_text(encoding="utf-8").splitlines()
            # Local builds for both Hermes and OmniRoute must have run.
            self.assertTrue(any("omniroute-rtk-envelope" in c for c in calls), calls)
            self.assertTrue(any("omniroute-patches" in c for c in calls), calls)
            # OmniRoute compose must pass --pull never when --build-local is active.
            omni_compose = [c for c in calls if "docker-compose.omniroute.yml" in c]
            self.assertTrue(omni_compose, calls)
            self.assertIn("--pull never", omni_compose[0])
            # verify must perform read-only build-time voice patch checks, not runtime mutation.
            log_text = log_file.read_text(encoding="utf-8")
            self.assertIn("Voice patches (build-time)", log_text)
            self.assertNotIn("install_all()", log_text)

    def test_ssh_dispatch_quotes_args_and_hides_secrets_from_cmdline(self):
        with tempfile.TemporaryDirectory() as td:
            stub_dir = Path(td)
            ssh_log = stub_dir / "ssh.log"
            stdin_log = stub_dir / "ssh_stdin.log"
            _make_stub(
                stub_dir,
                "ssh",
                f"""
printf 'CMD: %s\\n' "$*" >> "{ssh_log}"
# Drain the tar stream like real ssh would; exiting early SIGPIPEs tar under pipefail.
[[ "$*" == *"tar -xzf"* ]] && cat > /dev/null
if [[ "$*" == *"mktemp /tmp/hermes-kit-env."* ]]; then
  cat >> "{stdin_log}"
  printf '/tmp/hermes-kit-env.stub123'
fi
""",
            )
            # Stub tar so we don't archive the whole repo during unit test.
            _make_stub(stub_dir, "tar", "printf 'TAR_STREAM'")

            secret_pw = "p@ss word 'single' \"double\" $INJECT; echo PWNED"
            env = dict(os.environ)
            env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
            env["KIT_OMNIROUTE_PASSWORD"] = secret_pw
            env["DISCORD_BOT_TOKEN"] = "tok-secret-123"

            proc = subprocess.run(
                [
                    str(DEPLOY_SH),
                    "--ssh",
                    "root@203.0.113.10",
                    "migrate",
                    "--with-omniroute",
                    "--apply-presets",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            ssh_calls = ssh_log.read_text(encoding="utf-8")
            # Secrets must NOT appear on the ssh remote command line.
            self.assertNotIn("tok-secret-123", ssh_calls)
            self.assertNotIn("echo PWNED", ssh_calls)
            # Post-command flags must be forwarded to the remote invocation.
            self.assertIn("--with-omniroute", ssh_calls)
            self.assertIn("--apply-presets", ssh_calls)
            # Secrets must be transferred safely via the temp env file stdin payload.
            payload = stdin_log.read_text(encoding="utf-8")
            self.assertIn("DISCORD_BOT_TOKEN=", payload)
            self.assertIn("KIT_OMNIROUTE_PASSWORD=", payload)
            # Verify the payload parses back to the exact secret without executing anything.
            verify_pw = subprocess.run(
                ["bash", "-c", payload + 'printf "%s" "$KIT_OMNIROUTE_PASSWORD"'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(verify_pw.returncode, 0, verify_pw.stderr)
            self.assertEqual(verify_pw.stdout, secret_pw)

    def _run_with_docker(self, docker_body, args, extra_env=None):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        stub_dir = Path(td.name)
        log_file = stub_dir / "docker.log"
        _make_stub(stub_dir, "docker", f'printf \'%s\\n\' "$*" >> "{log_file}"\n' + docker_body)
        env = dict(os.environ)
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
        env["KIT_OMNIROUTE_PASSWORD"] = "pw"
        env.pop("DISCORD_BOT_TOKEN", None)
        env.pop("KIT_OMNIROUTE_VOLUME", None)
        env.update(extra_env or {})
        proc = subprocess.run([str(DEPLOY_SH), *args], env=env, capture_output=True, text=True, timeout=30)
        calls = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
        return proc, calls

    # Running containers on a migrated VPS: OmniRoute (kit image) and Syncthing are listed first.
    PS_MIXED = r"""
  ps)
    if [[ "$*" == *"-a"* ]]; then
      printf 'advanced-omniroute-1\thermes-kit:omniroute-ui-patch\tomniroute\tadvanced\n'
    else
      printf 'advanced-omniroute-1\thermes-kit:omniroute-ui-patch\tomniroute\n'
      printf 'hermes-kit-syncthing-1\tsyncthing/syncthing:1.27.10\tsyncthing\n'
      printf 'hermes-kit-hermes-1\tghcr.io/wendy-nam/hermes-kit:0.23.3-k19\thermes\n'
    fi ;;
  exec)
    # Only the real Hermes container has the gateway venv.
    for a in "$@"; do [[ "$a" == "hermes-kit-hermes-1" ]] && exit 0; done
    exit 1 ;;
"""

    def test_detection_skips_omniroute_and_syncthing_lookalikes(self):
        body = 'case "${1:-}" in' + self.PS_MIXED + '  *) exit 0 ;;\nesac\n'
        proc, calls = self._run_with_docker(body, ["verify"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Verifying Hermes container 'hermes-kit-hermes-1'", proc.stdout)
        verify_exec = [c for c in calls if c.startswith("exec") and "/opt/hermes/.venv/bin/python -c" in c]
        self.assertTrue(verify_exec and all("hermes-kit-hermes-1" in c for c in verify_exec), calls)

    def test_explicit_container_must_be_hermes_runtime(self):
        body = 'case "${1:-}" in' + self.PS_MIXED + '  inspect) echo true ;;\n  *) exit 0 ;;\nesac\n'
        proc, _ = self._run_with_docker(body, ["--container", "advanced-omniroute-1", "verify"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not a Hermes runtime", proc.stderr)

    def test_migrate_refuses_to_guess_between_omniroute_volumes(self):
        body = 'case "${1:-}" in' + self.PS_MIXED + r"""
  volume)
    [[ "${2:-}" == "ls" ]] && printf 'advanced_omniroute-data\nomniroute_omniroute-data\nhermes-kit_hermes-data\n'
    exit 0 ;;
  *) exit 0 ;;
esac
"""
        proc, calls = self._run_with_docker(body, ["migrate", "--with-omniroute"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Multiple OmniRoute data volumes", proc.stderr)
        self.assertFalse([c for c in calls if "docker-compose.omniroute.yml" in c], calls)

    def test_explicit_omniroute_volume_is_attached_in_existing_project(self):
        body = 'case "${1:-}" in' + self.PS_MIXED + r"""
  volume)
    [[ "${2:-}" == "ls" ]] && printf 'advanced_omniroute-data\nomniroute_omniroute-data\n'
    exit 0 ;;
  *) exit 0 ;;
esac
"""
        override = REPO_ROOT / "advanced" / ".omniroute-volume.override.yml"
        self.addCleanup(lambda: override.unlink(missing_ok=True))
        proc, calls = self._run_with_docker(
            body, ["migrate", "--with-omniroute", "--omniroute-volume", "omniroute_omniroute-data"]
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        omni = [c for c in calls if "docker-compose.omniroute.yml" in c]
        self.assertTrue(omni, calls)
        self.assertIn(".omniroute-volume.override.yml", omni[0])
        self.assertIn("-p advanced", omni[0])
        text = override.read_text(encoding="utf-8")
        self.assertIn("external: true", text)
        self.assertIn('name: "omniroute_omniroute-data"', text)

    def test_missing_explicit_omniroute_volume_is_never_created(self):
        body = 'case "${1:-}" in' + self.PS_MIXED + '  volume) [[ "${2:-}" == "inspect" ]] && exit 1; exit 0 ;;\n  *) exit 0 ;;\nesac\n'
        proc, calls = self._run_with_docker(body, ["migrate", "--with-omniroute", "--omniroute-volume", "nope"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stderr)
        self.assertFalse([c for c in calls if "docker-compose.omniroute.yml" in c], calls)

    def test_missing_option_value_exits_cleanly_with_code_2(self):
        for flag in ("--ssh", "-p", "-i", "--remote-dir", "--container", "--omniroute-volume"):
            proc = subprocess.run(
                [str(DEPLOY_SH), flag],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 2, flag)
            self.assertIn("requires an argument", proc.stderr)


if __name__ == "__main__":
    unittest.main()
