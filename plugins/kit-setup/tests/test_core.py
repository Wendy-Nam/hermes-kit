"""Phase 2 core: .env storage, key validation, pack definitions, owner/invite maths.

Everything here runs offline — the validators' network call is the only thing stubbed. The
Discord UI is not covered here because it cannot be imported without discord.py; that is the
manual E2E checklist in the plan (Task 9 Step 3).
"""
import asyncio
import json
import os
import stat
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


if __name__ == "__main__":
    unittest.main()

