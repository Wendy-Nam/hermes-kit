"""Phase 2 core: .env storage, key validation, pack definitions, owner/invite maths.

Everything here runs offline — the validators' network call is the only thing stubbed. The
Discord UI is not covered here because it cannot be imported without discord.py; that is the
manual E2E checklist in the plan (Task 9 Step 3).
"""
import asyncio
import importlib.util
import io
import tarfile
import time
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

import env_store
import owner
import packs
import validators as v


class EnvStore(unittest.TestCase):
    def test_update_preserves_others_comments_and_perms(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("# c\nA=1\nB=2\n")
        env_store.set_env(p, {"B": "3", "C": "x=y"})
        self.assertEqual(p.read_text(), "# c\nA=1\nB=3\nC=x=y\n")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(env_store.get_env(p), {"A": "1", "B": "3", "C": "x=y"})

    def test_value_with_equals_survives_a_roundtrip(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        env_store.set_env(p, {"TOKEN": "a=b=c"})
        self.assertEqual(env_store.get_env(p), {"TOKEN": "a=b=c"})

    def test_rejects_newline_injection(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        for bad in ({"A": "ok\nEVIL=1"}, {"A": "ok\r\nEVIL=1"}, {"A=B": "x"}):
            with self.assertRaises(ValueError):
                env_store.set_env(p, bad)
        self.assertFalse(p.exists())   # a rejected write must not leave a file behind

    def test_creates_file_with_secure_perms_when_absent(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        env_store.set_env(p, {"A": "1"})
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertTrue(env_store.is_secure(p))

    def test_is_secure_flags_group_readable_files(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("A=1\n")
        os.chmod(p, 0o644)
        self.assertFalse(env_store.is_secure(p))

    def test_commented_and_blank_lines_are_not_treated_as_keys(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        p.write_text("# A=commented\n\nB=2\n")
        env_store.set_env(p, {"A": "real"})
        self.assertEqual(env_store.get_env(p), {"B": "2", "A": "real"})
        self.assertIn("# A=commented", p.read_text())


class Validators(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _stub(self, status, body):
        def fake(url, headers, proxy=None):
            self.calls.append((url, headers, proxy))
            return status, body
        v._get = fake

    def test_groq_ok_names_a_model(self):
        self._stub(200, b'{"data":[{"id":"whisper-large-v3"}]}')
        ok, msg = v.VALIDATORS["groq"]("gsk_x")
        self.assertTrue(ok)
        self.assertIn("whisper", msg)
        self.assertEqual(self.calls[0][1]["Authorization"], "Bearer gsk_x")

    def test_key_never_appears_in_a_url(self):
        self._stub(200, b'{"models":[]}')
        for name in ("gemini", "groq", "apify", "opencode_go", "commandcode"):
            self.calls.clear()
            v.VALIDATORS[name]("SECRETKEY")
            self.assertNotIn("SECRETKEY", self.calls[0][0], name)

    def test_401_reads_as_a_wrong_key_not_a_server_problem(self):
        self._stub(401, b"")
        ok, msg = v.VALIDATORS["groq"]("bad")
        self.assertFalse(ok)
        self.assertIn("401", msg)

    def test_network_failure_is_distinguished_from_a_rejection(self):
        self._stub(0, b"timed out")
        ok, msg = v.VALIDATORS["groq"]("good")
        self.assertFalse(ok)
        self.assertIn("인터넷", msg)

    def test_discord_reports_the_bot_name(self):
        self._stub(200, b'{"username":"hermes-kit"}')
        ok, msg = v.VALIDATORS["discord"]("tok")
        self.assertTrue(ok)
        self.assertIn("hermes-kit", msg)

    def _webshare_sequences(self, second):
        seq = [(200, json.dumps({"results": [{"username": "u", "password": "p",
                                              "proxy_address": "1.2.3.4", "port": 8080}]}).encode()),
               second]
        v._get = lambda url, headers, proxy=None: (self.calls.append((url, headers, proxy)), seq.pop(0))[1]

    def test_webshare_verifies_through_the_proxy_not_just_the_key(self):
        self._webshare_sequences((200, b"<html>"))
        ok, _ = v.VALIDATORS["webshare"]("tok")
        self.assertTrue(ok)
        self.assertEqual(self.calls[1][2], "http://u:p@1.2.3.4:8080")
        self.assertIn("wanted.co.kr", self.calls[1][0])

    def test_webshare_valid_key_but_dead_proxy_is_not_success(self):
        self._webshare_sequences((0, b""))
        ok, msg = v.VALIDATORS["webshare"]("tok")
        self.assertFalse(ok)
        self.assertIn("프록시", msg)

    def test_every_validator_is_callable(self):
        for name, check in v.VALIDATORS.items():
            self.assertTrue(callable(check), name)


class Packs(unittest.TestCase):
    def test_definitions_load(self):
        ps = packs.load_packs(v.VALIDATORS)
        self.assertTrue(ps)
        self.assertTrue(any(p.required for p in ps), "the base pack must be required")

    def test_every_pack_key_fits_one_modal(self):
        for p in packs.load_packs(v.VALIDATORS):
            self.assertLessEqual(len(p.keys), packs.MAX_KEYS_PER_PACK, p.id)

    def test_env_names_are_upper_snake(self):
        for p in packs.load_packs(v.VALIDATORS):
            for k in p.keys:
                self.assertRegex(k.env, r"^[A-Z][A-Z0-9_]*$", f"{p.id}.{k.env}")

    def test_kit_features_resolve_to_real_packs(self):
        ps, ks = packs.load_packs(v.VALIDATORS), packs.load_kits()
        self.assertTrue(ks)
        for k in ks:
            for f in k.features:
                self.assertIn(f, [p.id for p in ps], f"{k.id} -> {f}")

    def test_kit_selection_pulls_in_base_and_its_features(self):
        ps, ks = packs.load_packs(v.VALIDATORS), packs.load_kits()
        self.assertEqual([p.id for p in packs.packs_for_kits(["job"], ps, ks)],
                         [p.id for p in ps if p.id in {"base", "proxy"}])

    def test_kit_selection_is_stable(self):
        ps, ks = packs.load_packs(v.VALIDATORS), packs.load_kits()
        self.assertEqual([p.id for p in packs.packs_for_kits(["pm", "job"], ps, ks)],
                         [p.id for p in packs.packs_for_kits(["pm", "job"], ps, ks)])

    def test_unknown_kit_is_an_error_not_a_silent_empty_result(self):
        with self.assertRaises(ValueError):
            packs.packs_for_kits(["nope"], packs.load_packs(v.VALIDATORS), packs.load_kits())

    def test_alternative_sub_models_may_share_a_group_without_colliding(self):
        subs = [p for p in packs.load_packs(v.VALIDATORS) if p.required_one_of == "sub"]
        self.assertGreaterEqual(len(subs), 2)
        envs = [k.env for p in subs for k in p.keys]
        self.assertEqual(len(envs), len(set(envs)))

    def test_missing_keys_reports_only_required_packs(self):
        ps = packs.load_packs(v.VALIDATORS)
        self.assertTrue(packs.missing_keys(ps, {}))
        self.assertFalse(packs.missing_keys(ps, {"GEMINI_API_KEY": "x"}))

    def _load_bad(self, bad):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "packs.json").write_text(json.dumps(bad))
        return patch.object(packs, "HERE", tmp)

    def test_load_packs_rejects_an_unknown_validator(self):
        bad = json.loads((HERE / "packs.json").read_text())
        bad[0]["keys"][0]["validator"] = "nope"
        with self._load_bad(bad), self.assertRaises(ValueError):
            packs.load_packs(v.VALIDATORS)

    def test_load_packs_rejects_a_duplicate_env_claim(self):
        bad = json.loads((HERE / "packs.json").read_text())
        bad[1]["keys"][0]["env"] = "GEMINI_API_KEY"
        bad[1].pop("required_one_of", None)
        with self._load_bad(bad), self.assertRaises(ValueError):
            packs.load_packs(v.VALIDATORS)


def _pairing_stub(approved):
    """A gateway.pairing module backed by a plain list, for the owner helpers."""
    import types
    mod = types.ModuleType("gateway.pairing")
    mod.PairingStore = lambda *a, **k: types.SimpleNamespace(
        list_approved=lambda plat: approved,
        generate_code=lambda plat, uid, name: "CODE",
        approve_code=lambda plat, code: (approved.append({"user_id": "42"}) or True))
    sys.modules.setdefault("gateway", types.ModuleType("gateway"))
    sys.modules["gateway.pairing"] = mod


class Owner(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("gateway.pairing", None)
        sys.modules.pop("gateway", None)

    def test_permission_bits_are_the_documented_value(self):
        # Any change to PERM_BITS changes this number; the plan pins it so a silently
        # under-permissioned invite cannot slip through.
        self.assertEqual(owner.PERMS, 277028654080)

    def test_invite_url_carries_client_and_permissions(self):
        url = owner.invite_url("123")
        self.assertIn("client_id=123", url)
        self.assertIn(f"permissions={owner.PERMS}", url)
        self.assertIn("applications.commands", url)

    def test_ensure_owner_approves_a_new_user(self):
        approved = []
        _pairing_stub(approved)
        self.assertTrue(owner.ensure_owner("42", "someone"))
        self.assertEqual(approved, [{"user_id": "42"}])

    def test_ensure_owner_is_idempotent(self):
        approved = [{"user_id": "42"}]
        _pairing_stub(approved)
        self.assertFalse(owner.ensure_owner("42", "someone"))
        self.assertEqual(len(approved), 1, "an already-approved owner must not be re-added")

    def test_is_approved_reflects_the_store(self):
        _pairing_stub([{"user_id": "7"}])
        self.assertTrue(owner.is_approved("7"))
        self.assertFalse(owner.is_approved("8"))


class ApplyFlow(unittest.TestCase):
    """The rule that matters: a pack is saved only when every one of its keys verifies."""

    def setUp(self):
        import discord_ui
        self.du = discord_ui
        self.spec = packs.load_packs(v.VALIDATORS)[0].keys[0]   # GEMINI_API_KEY
        self.tmp = Path(tempfile.mkdtemp())
        patcher = patch.object(discord_ui, "ENV_FILE", self.tmp / ".env")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_verify_reports_each_key_and_never_leaks_the_value(self):
        with patch.dict(v.VALIDATORS, {"gemini": lambda k: (False, "키가 거부됐습니다 (HTTP 401)")}):
            out = asyncio.run(self.du._verify([(self.spec, "SECRET")]))
        self.assertEqual(out, [("GEMINI_API_KEY", False, "키가 거부됐습니다 (HTTP 401)")])
        self.assertNotIn("SECRET", repr(out))

    def test_verify_survives_a_validator_that_raises(self):
        def boom(k):
            raise RuntimeError("network stack exploded")
        with patch.dict(v.VALIDATORS, {"gemini": boom}):
            out = asyncio.run(self.du._verify([(self.spec, "k")]))
        self.assertFalse(out[0][1])
        self.assertIn("RuntimeError", out[0][2])

    def test_apply_writes_keys_with_600_and_returns_no_secret(self):
        lines = self.du._apply([(self.spec, "AIza-real")], {})
        self.assertEqual(env_store.get_env(self.tmp / ".env"), {"GEMINI_API_KEY": "AIza-real"})
        self.assertEqual(stat.S_IMODE(os.stat(self.tmp / ".env").st_mode), 0o600)
        self.assertNotIn("AIza-real", "\n".join(lines))

    def test_apply_preserves_unrelated_existing_keys(self):
        env_store.set_env(self.tmp / ".env", {"DISCORD_BOT_TOKEN": "keepme"})
        self.du._apply([(self.spec, "AIza-real")], {})
        self.assertEqual(env_store.get_env(self.tmp / ".env"),
                         {"DISCORD_BOT_TOKEN": "keepme", "GEMINI_API_KEY": "AIza-real"})

    def test_env_refs_are_left_for_the_env_file_not_written_to_config(self):
        with patch.object(self.du.subprocess, "run") as run:
            self.du._apply([(self.spec, "x")], {"a": "1", "b": "${COMMANDCODE_API_KEY}"})
        keys = [c.args[0][3] for c in run.call_args_list if c.args and c.args[0]]
        self.assertIn("a", keys)
        self.assertNotIn("b", keys)   # writing the literal "${...}" would store a useless string

    def test_a_failed_config_set_is_reported_not_claimed_as_applied(self):
        """A green tick on a setting that did not stick is worse than an honest red one."""
        import subprocess as sp
        with patch.object(self.du.subprocess, "run",
                          return_value=sp.CompletedProcess([], 1, "", "boom")):
            lines = self.du._apply([(self.spec, "x")], {"stt.provider": "groq"})
        failed = [l for l in lines if "stt.provider" in l][0]
        self.assertIn("설정 적용 실패", failed)
        self.assertNotIn("✅", failed)

    def test_a_missing_hermes_binary_is_reported_not_raised(self):
        with patch.object(self.du.subprocess, "run", side_effect=FileNotFoundError("no hermes")):
            lines = self.du._apply([(self.spec, "x")], {"a": "1"})
        self.assertIn("설정 적용 실패", "\n".join(lines))
        self.assertEqual(env_store.get_env(self.tmp / ".env"), {"GEMINI_API_KEY": "x"})

    def test_successful_config_set_is_still_claimed(self):
        import subprocess as sp
        with patch.object(self.du.subprocess, "run",
                          return_value=sp.CompletedProcess([], 0, "", "")):
            lines = self.du._apply([(self.spec, "x")], {"stt.provider": "groq"})
        self.assertIn("✅ 설정 적용: stt.provider", "\n".join(lines))


class PacksFetch(unittest.TestCase):
    """Downloading the private packs repo must never damage a working install."""

    def setUp(self):
        import fetch_packs
        self.fp = fetch_packs
        self.data = Path(tempfile.mkdtemp())

    def _tarball(self, build):
        """Build an in-memory .tar.gz the way GitHub serves one (single top-level dir)."""
        import io, tarfile
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz") as tf:
            root = tarfile.TarInfo("Wendy-Nam-hermes-kit-packs-abc123/")
            root.type = tarfile.DIRTYPE
            tf.addfile(root)
            build(tf)
        return raw.getvalue()

    def _add(self, tf, name, data=b"x"):
        info = tarfile.TarInfo(f"Wendy-Nam-hermes-kit-packs-abc123/{name}")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    def _fetch(self, blob):
        return self.fp._safe_extract(blob, Path(tempfile.mkdtemp()))

    def test_no_token_means_skip_and_success(self):
        ok, msg = self.fp.fetch("o/r", "main", "", self.data)
        self.assertFalse(ok)
        self.assertIn("KIT_ACCESS_CODE", msg)

    def test_installs_kit_skills_and_replaces_them_on_a_later_run(self):
        blob = self._tarball(lambda tf: self._add(tf, "skills/kit/base/SKILL.md", b"v1"))
        with patch.object(self.fp, "_download", return_value=blob):
            self.assertTrue(self.fp.fetch("o/r", "main", "tok", self.data)[0])
        target = self.data / "skills" / "kit" / "base" / "SKILL.md"
        self.assertEqual(target.read_bytes(), b"v1")
        blob2 = self._tarball(lambda tf: self._add(tf, "skills/kit/base/SKILL.md", b"v2"))
        with patch.object(self.fp, "_download", return_value=blob2):
            self.assertTrue(self.fp.fetch("o/r", "main", "tok", self.data)[0])
        self.assertEqual(target.read_bytes(), b"v2")

    def test_soul_and_freellmapi_are_not_overwritten(self):
        self.data.mkdir(exist_ok=True)
        (self.data / "soul").mkdir()
        (self.data / "soul" / "SOUL.md").write_text("학생이 고친 버전")
        blob = self._tarball(lambda tf: self._add(tf, "soul/SOUL.md", b"author"))
        with patch.object(self.fp, "_download", return_value=blob):
            self.fp.fetch("o/r", "main", "tok", self.data)
        self.assertEqual((self.data / "soul" / "SOUL.md").read_text(), "학생이 고친 버전")

    def test_a_symlink_in_the_tarball_aborts_everything(self):
        def build(tf):
            link = tarfile.TarInfo("Wendy-Nam-hermes-kit-packs-abc123/skills/kit/evil")
            link.type = tarfile.SYMTYPE
            link.linkname = "/opt/data/.env"
            tf.addfile(link)
        with self.assertRaises(ValueError) as ctx:
            self._fetch(self._tarball(build))
        self.assertIn("링크", str(ctx.exception))

    def test_path_traversal_is_refused(self):
        def build(tf):
            self._add(tf, "skills/kit/../../escape.md")
        with self.assertRaises(ValueError):
            self._fetch(self._tarball(build))

    def test_a_failed_download_leaves_the_previous_skills_intact(self):
        import urllib.error
        blob = self._tarball(lambda tf: self._add(tf, "skills/kit/base/SKILL.md", b"v1"))
        with patch.object(self.fp, "_download", return_value=blob):
            self.fp.fetch("o/r", "main", "tok", self.data)
        good = (self.data / "skills" / "kit" / "base" / "SKILL.md").read_bytes()
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with patch.object(self.fp, "_download", side_effect=err):
            ok, msg = self.fp.fetch("o/r", "main", "tok", self.data)
        self.assertFalse(ok)
        self.assertIn("404", msg)
        self.assertEqual((self.data / "skills" / "kit" / "base" / "SKILL.md").read_bytes(), good)

    def test_expired_token_says_so(self):
        import urllib.error
        err = urllib.error.HTTPError("u", 401, "Bad credentials", {}, None)
        with patch.object(self.fp, "_download", side_effect=err):
            ok, msg = self.fp.fetch("o/r", "main", "expired", self.data)
        self.assertFalse(ok)
        self.assertIn("만료", msg)

    def test_network_error_never_raises(self):
        with patch.object(self.fp, "_download", side_effect=TimeoutError("no route")):
            ok, msg = self.fp.fetch("o/r", "main", "tok", self.data)
        self.assertFalse(ok)
        self.assertIn("실패", msg)


class Doctor(unittest.TestCase):
    """The report is what a student sends to their instructor, so redaction is the point."""

    def setUp(self):
        import doctor
        self.d = doctor
        self.data = Path(tempfile.mkdtemp())

    def test_mask_removes_key_shapes_tokens_ids_and_emails(self):
        # Built at runtime on purpose: a literal key-shaped string committed to a public repo
        # trips scripts/secret-scan.sh, and a real channel id or IP must never enter this file.
        fake_key = "gsk_" + "a" * 32
        fake_aiza = "AIza" + "B" * 35
        for secret in (fake_key, fake_aiza,
                       "203.0.113.7",                      # TEST-NET-3, reserved for docs
                       "1000000000000000001",              # a made-up snowflake
                       "student@example.com",
                       "DISCORD_BOT_TOKEN=notarealtoken"):
            out = self.d.mask(f"값: {secret} 끝")
            self.assertNotIn(secret, out, secret)
            self.assertIn("[가림]", out)

    def test_instructor_copy_is_redacted(self):
        fake = "gsk_" + "c" * 32
        findings = [self.d.Finding("봇", self.d.BAD, f"키 {fake} 가 거부")]
        self.assertNotIn(fake, self.d.copy_for_instructor(findings))

    def test_env_file_missing_points_at_setup(self):
        f = self.d.check_env_file(self.data / ".env")
        self.assertEqual(f.status, self.d.BAD)
        self.assertIn("/setup", f.detail)

    def test_loose_env_permissions_are_flagged(self):
        p = self.data / ".env"
        p.write_text("A=1\n")
        os.chmod(p, 0o644)
        f = self.d.check_env_file(p)
        self.assertEqual(f.status, self.d.BAD)
        self.assertIn("600", f.detail)

    def test_healthy_env_file_passes(self):
        p = self.data / ".env"
        p.write_text("A=1\n")
        os.chmod(p, 0o600)
        self.assertEqual(self.d.check_env_file(p).status, self.d.OK)

    def test_missing_key_is_reported_as_needing_setup(self):
        with patch.dict(v.VALIDATORS, {"gemini": lambda k: (True, "확인됨")}):
            out = self.d.check_keys({}, self.data / ".env")
        gem = [f for f in out if "Gemini" in f.name]
        self.assertEqual(gem[0].status, self.d.BAD)
        self.assertIn("/setup", gem[0].detail)

    def test_a_rejected_key_shows_the_reason_without_the_value(self):
        with patch.dict(v.VALIDATORS, {"gemini": lambda k: (False, "키가 거부됐습니다 (HTTP 401)")}):
            out = self.d.check_keys({"GEMINI_API_KEY": "AIzaSECRET"}, self.data / ".env")
        line = out[0].line()
        self.assertIn("401", line)
        self.assertNotIn("AIzaSECRET", line)

    def test_optional_addon_absent_is_not_an_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("no route")):
            f = self.d.check_optional("http://freellmapi:3001/api/ping", "freellmapi 심화팩")
        self.assertEqual(f.status, self.d.SKIP)

    def test_report_summarises_the_worst_state(self):
        out = self.d.report([self.d.Finding("a", self.d.OK, "정상"),
                             self.d.Finding("b", self.d.BAD, "문제")])
        self.assertIn("🔴", out)
        self.assertIn("문제가 있습니다", out)

    def test_report_of_all_good_says_so(self):
        self.assertIn("모든 항목 정상", self.d.report([self.d.Finding("a", self.d.OK, "정상")]))

    def test_gateway_just_restarted_is_a_hint_not_an_alarm(self):
        class P:
            def is_running(self):
                return True

            def create_time(self):
                import time as t
                return t.time() - 10
        self.assertEqual(self.d.check_gateway(P()).status, self.d.WARN)

    def test_gateway_down_is_an_error(self):
        class P:
            def is_running(self):
                return False
        self.assertEqual(self.d.check_gateway(P()).status, self.d.BAD)


class Backup(unittest.TestCase):
    """The exclusion list is the safety property: a backup must never become a key archive."""

    def setUp(self):
        import backup
        self.b = backup
        self.data = Path(tempfile.mkdtemp())
        (self.data / "memories").mkdir()
        (self.data / "memories" / "note.md").write_text("학생 메모")
        (self.data / "config.yaml").write_text("a: 1")
        (self.data / ".env").write_text("GEMINI_API_KEY=AIzaSECRET\n")
        (self.data / "auth.json").write_text('{"token": "secret"}')
        (self.data / "profiles").mkdir()
        (self.data / "profiles" / "p").mkdir()
        (self.data / "profiles" / "p" / "auth.json").write_text('{"token": "nested-secret"}')
        (self.data / "vaults").mkdir()
        (self.data / "vaults" / "note.md").write_text("볼트 노트")
        self.dest = Path(tempfile.mkdtemp())

    def _archive(self):
        return self.dest / f"{time.strftime('%Y-%m-%d')}.tar.gz"

    def _names(self, archive):
        with tarfile.open(archive) as tf:
            return tf.getnames()

    def test_backup_contains_notes_and_config(self):
        ok, msg = self.b.build(self.data, self.dest)
        self.assertTrue(ok, msg)
        names = self._names(self._archive())
        self.assertIn("config.yaml", names)
        self.assertIn("memories/note.md", names)
        self.assertIn("vaults/note.md", names)

    def test_backup_never_contains_env_or_auth_at_any_depth(self):
        self.b.build(self.data, self.dest)
        for n in self._names(self._archive()):
            self.assertNotIn(".env", n, n)
            self.assertNotIn("auth", n, n)
        blob = self._archive().read_bytes()
        self.assertNotIn(b"AIzaSECRET", blob)
        self.assertNotIn(b"nested-secret", blob)

    def test_two_runs_on_the_same_day_do_not_overwrite(self):
        self.assertTrue(self.b.build(self.data, self.dest)[0])
        ok, msg = self.b.build(self.data, self.dest)
        self.assertFalse(ok)
        self.assertIn("이미", msg)

    def test_old_archives_are_pruned_to_keep_count(self):
        for d in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"):
            (self.dest / f"{d}.tar.gz").write_bytes(b"old")
        self.b.build(self.data, self.dest)
        self.assertLessEqual(len(list(self.dest.glob("*.tar.gz"))), self.b.KEEP)

    def test_nothing_to_back_up_leaves_no_empty_archive(self):
        ok, _ = self.b.build(Path(tempfile.mkdtemp()), self.dest)
        self.assertFalse(ok)
        self.assertEqual(list(self.dest.glob("*.tar.gz")), [])

    def test_cron_registration_is_idempotent_and_uses_no_agent(self):
        ok, msg = self.b.install_cron(self.data)
        self.assertTrue(ok, msg)
        self.assertFalse(self.b.install_cron(self.data)[0])
        jobs = json.loads((self.data / "cron" / "jobs.json").read_text())
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["no_agent"])


class Updates(unittest.TestCase):
    def test_version_parsing_is_numeric_not_lexicographic(self):
        import updates
        self.assertGreater(updates.parse_version("0.21.3-k1"), updates.parse_version("0.21.2-k9"))
        self.assertGreater(updates.parse_version("1.0.0"), updates.parse_version("0.99.99"))
        self.assertEqual(updates.parse_version("v0.21.2-k1"), (0, 21, 2, 1))
        self.assertEqual(updates.parse_version("0.21.2"), (0, 21, 2, 0))
        self.assertIsNone(updates.parse_version("latest"))
        self.assertIsNone(updates.parse_version(""))

    def test_no_update_when_current_is_newer(self):
        import updates
        with patch.object(updates, "latest_release", return_value=("v0.21.2-k1", "notes")):
            self.assertFalse(updates.check("0.21.3-k1")[0])

    def test_update_message_carries_the_bullets(self):
        import updates
        with patch.object(updates, "latest_release",
                          return_value=("v0.21.3-k2", "- 버그 수정\n- 체인 추가\n- 셋째\n- 넷째")):
            avail, tag, msg = updates.check("0.21.2-k1")
        self.assertTrue(avail)
        self.assertIn("0.21.2-k1", msg)
        self.assertIn("0.21.3-k2", msg)
        self.assertIn("버그 수정", msg)
        self.assertIn("셋째", msg)
        self.assertNotIn("넷째", msg)   # only the first three bullets

    def test_release_notes_fallback_still_tells_the_student_what_to_do(self):
        import updates
        with patch.object(updates, "latest_release", return_value=("v0.21.3-k2", "")):
            self.assertIn("Redeploy", updates.check("0.21.2-k1")[2])

    def test_unreachable_github_is_silent_not_an_alert(self):
        import updates
        with patch.object(updates, "latest_release", return_value=(None, "GitHub에 연결하지 못했습니다")):
            self.assertFalse(updates.check("0.21.2-k1")[0])

    def test_update_cron_is_idempotent_and_no_agent(self):
        import updates
        data = Path(tempfile.mkdtemp())
        self.assertTrue(updates.install_cron(data)[0])
        self.assertFalse(updates.install_cron(data)[0])
        jobs = json.loads((data / "cron" / "jobs.json").read_text())
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["no_agent"])


class Entrypoints(unittest.TestCase):
    """Run each script the way a cron or a container would, not the way a test would.

    The weekly backup shipped with a NameError in its __main__ block that 67 passing tests
    never noticed, because every one of them called build() directly. A test that imports a
    module proves nothing about the part that only runs in production.
    """

    def _run(self, name, env=None, args=()):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("GEMINI_", "APIFY_"))}
        e.update(env or {})
        return subprocess.run([sys.executable, str(HERE / f"{name}.py"), *args],
                              capture_output=True, text=True, timeout=60, env=e)

    def test_backup_entrypoint_runs_and_writes_an_archive(self):
        home = Path(tempfile.mkdtemp())
        (home / "memories").mkdir()
        (home / "memories" / "n.md").write_text("노트")
        r = self._run("backup", {"HERMES_HOME": str(home)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue(list((home / "vaults" / "personal" / "_backup").glob("*.tar.gz")))

    def test_backup_entrypoint_on_an_empty_home_is_not_a_crash(self):
        r = self._run("backup", {"HERMES_HOME": tempfile.mkdtemp()})
        self.assertNotIn("Traceback", r.stderr)

    def test_update_check_entrypoint_runs(self):
        r = self._run("updates", {"HERMES_HOME": tempfile.mkdtemp()})
        self.assertNotIn("Traceback", r.stderr)

    def test_every_module_imports_cleanly(self):
        for name in ("env_store", "validators", "packs", "owner", "discord_ui",
                     "doctor", "backup", "updates", "fetch_packs"):
            spec = importlib.util.spec_from_file_location(f"m_{name}", HERE / f"{name}.py")
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            self.assertTrue(m, name)

    def test_doctor_and_setup_share_the_same_owner_rule(self):
        """/doctor is owner-only for the same reason /setup is: it re-checks real keys."""
        import inspect

        import doctor
        import discord_ui

        self.assertIn("guild.owner_id", inspect.getsource(doctor.doctor_command))
        self.assertIn("guild.owner_id", inspect.getsource(discord_ui.setup_command))


class Disconnect(unittest.TestCase):
    """연결 해제 — the reverse of /setup. Two things must hold: keys really go, and settings come back."""

    def setUp(self):
        import disconnect
        self.dc = disconnect
        self.data = Path(tempfile.mkdtemp())
        self.env_file = self.data / ".env"
        env_store.set_env(self.env_file, {"GEMINI_API_KEY": "AIzaREAL", "DISCORD_BOT_TOKEN": "keepme",
                                          "GROQ_API_KEY": "gskREAL"})

    def _flatten(self):
        spec = importlib.util.spec_from_file_location("du_flat", HERE / "discord_ui.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m._flatten({"stt": {"provider": "none"}, "agent": {"max_turns": 20}})

    def test_plan_lists_only_keys_that_are_actually_present(self):
        ps = packs.load_packs(v.VALIDATORS)
        keys, settings = self.dc.plan(self.data, self.env_file, ps)
        self.assertIn("GEMINI_API_KEY", keys)
        self.assertNotIn("DISCORD_BOT_TOKEN", keys)   # owned by compose, not by a pack

    def test_remove_keys_keeps_everything_else_and_stays_600(self):
        removed = self.dc.remove_keys(self.env_file, ["GEMINI_API_KEY", "GROQ_API_KEY"])
        self.assertEqual(sorted(removed), ["GEMINI_API_KEY", "GROQ_API_KEY"])
        self.assertEqual(env_store.get_env(self.env_file), {"DISCORD_BOT_TOKEN": "keepme"})
        self.assertEqual(stat.S_IMODE(os.stat(self.env_file).st_mode), 0o600)

    def test_drop_env_keeps_comments_and_unrelated_lines(self):
        self.env_file.write_text("# keep me\nDISCORD_BOT_TOKEN=t\nGROQ_API_KEY=g\n")
        os.chmod(self.env_file, 0o600)
        self.dc.remove_keys(self.env_file, ["GROQ_API_KEY"])
        self.assertIn("# keep me", self.env_file.read_text())
        self.assertIn("DISCORD_BOT_TOKEN=t", self.env_file.read_text())
        self.assertNotIn("GROQ", self.env_file.read_text())

    def test_drop_env_on_a_missing_file_is_a_no_op(self):
        self.assertEqual(self.dc.remove_keys(self.data / "nope.env", ["A"]), [])

    def test_snapshot_records_the_pre_apply_value(self):
        self.dc.snapshot(self.data, {"stt.provider": "groq", "agent.max_turns": 5}, self._flatten())
        snap = json.loads((self.data / ".kit-config-snapshot.json").read_text())
        self.assertEqual(snap["stt.provider"], "none")
        self.assertEqual(snap["agent.max_turns"], 20)

    def test_a_second_apply_does_not_clobber_the_baseline(self):
        """The first apply is the baseline; a later one must not overwrite what we restore to."""
        self.dc.snapshot(self.data, {"stt.provider": "groq"}, {"stt.provider": "none"})
        self.dc.snapshot(self.data, {"stt.provider": "groq"}, {"stt.provider": "groq"})
        snap = json.loads((self.data / ".kit-config-snapshot.json").read_text())
        self.assertEqual(snap["stt.provider"], "none")

    def test_revert_restores_every_snapshotted_key(self):
        self.dc.snapshot(self.data, {"stt.provider": "groq"}, {"stt.provider": "none"})
        applied = {}
        done = self.dc.revert_config(self.data, lambda k, v: applied.update({k: v}))
        self.assertEqual(done, ["stt.provider"])
        self.assertEqual(applied, {"stt.provider": "none"})

    def test_revert_with_nothing_snapshotted_is_a_no_op(self):
        self.assertEqual(self.dc.revert_config(self.data, lambda k, v: None), [])

    def test_forget_clears_the_snapshot(self):
        self.dc.snapshot(self.data, {"a": 1}, {"a": 0})
        self.dc.forget(self.data)
        self.assertFalse((self.data / ".kit-config-snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()


