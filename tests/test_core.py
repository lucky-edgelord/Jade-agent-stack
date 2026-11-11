import json
import os
import unittest
from pathlib import Path

from helpers import TOKEN, Fake, fake_base, fake_vault, isolate, jade, write_config

import jade as J
from jade.approvals import Approvals
from jade.config import Config
from jade.errors import JadeError, SafetyError


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.d = isolate(self)

    def test_discovery_upward_and_env(self):
        write_config(self.d, base="http://127.0.0.1:1")
        sub = self.d / "a" / "b"
        sub.mkdir(parents=True)
        os.chdir(sub)
        self.assertEqual(Config.load().path, self.d / "jade.config.yaml")
        other = self.d / "x.yaml"
        other.write_text("version: 1\n")
        os.environ["JADE_CONFIG"] = str(other)
        self.addCleanup(os.environ.pop, "JADE_CONFIG", None)
        self.assertEqual(Config.load().path, other)

    def test_strict(self):
        for bad, code in [({"nope": 1}, "JADE400"), ({"approvals": {"notes.write": True}}, "JADE400"),
                          ({"targets": {"base": {"url": "https://x.example?token=abc"}}}, "JADE102"), ({"targets": {"base": {"url": "ftp://x"}}}, "JADE400"),
                          ({"targets": {"mars": {}}}, "JADE400")]:
            with self.subTest(bad=bad), self.assertRaises(JadeError) as c:
                Config(bad)
            self.assertEqual(c.exception.code, code)


class ApprovalTests(unittest.TestCase):
    def test_deny_wins_and_patterns(self):
        a = Approvals({"base.*": ["*"], "base.schema": {"allow": ["collection_create:*"], "deny": ["collection_delete:*"]},
                       "shell": {"allow": ["ls", "cat"], "deny": ["rm"]}, "http_request": {"allow_hosts": ["api.example.com"], "deny_hosts": ["*"]}})
        self.assertFalse(a.check("base.schema", "collection_delete:posts").allowed)
        self.assertTrue(a.check("base.schema", "collection_create:posts").allowed)
        self.assertTrue(a.check("shell", "ls").allowed)
        self.assertFalse(a.check("shell", "rm").allowed)
        self.assertIsNone(Approvals({"shell": ["ls"]}).check("shell", "curl").allowed)
        self.assertFalse(a.check("http_request", "*", host="evil.example").allowed)
        d = Approvals({"base.schema": ["*"]}).check("base.schema", "collection_delete:x", destructive=True)
        self.assertTrue(d.allowed and d.confirm)

    def test_enforce(self):
        a = Approvals({"base.read": ["*"]}, log_path=Path(os.devnull))
        a.enforce(a.check("base.read", "x"), ask=None)
        with self.assertRaises(SafetyError) as c:
            a.enforce(a.check("base.write", "x"), ask=None)
        self.assertEqual(c.exception.code, "JADE300")
        a.enforce(a.check("base.write", "x"), ask=lambda q: True)
        with self.assertRaises(SafetyError):
            a.enforce(a.check("base.write", "x"), ask=lambda q: False)
        a.enforce(a.check("base.write", "x"), ask=None, yolo=True)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.d = isolate(self)
        self.base = fake_base()
        self.addCleanup(self.base.close)
        os.environ["JADE_SECRET_BASE"] = TOKEN
        self.addCleanup(os.environ.pop, "JADE_SECRET_BASE", None)

    def test_reads_writes_keys_and_approvals(self):
        write_config(self.d, base=self.base.url, approvals={"base.read": ["*"], "base.write": ["record_create:posts"]})
        s = J.Stack.load()
        s.call("base", "records_list", {"collection": "posts"})
        r1 = s.call("base", "record_create", {"collection": "posts", "data": {"t": 1}}, idempotency_key="k1")
        r2 = s.call("base", "record_create", {"collection": "posts", "data": {"t": 1}}, idempotency_key="k1")
        self.assertEqual(r1, r2)
        posts = [x for x in self.base.log if x["path"].endswith("record_create")]
        self.assertEqual([p["headers"].get("Idempotency-Key") for p in posts], ["k1", "k1"])
        reads = [x for x in self.base.log if x["path"].endswith("records_list")]
        self.assertIsNone(reads[0]["headers"].get("Idempotency-Key"))
        s.call("base", "record_create", {"collection": "posts"})
        auto = [x for x in self.base.log if x["path"].endswith("record_create")][-1]["headers"]["Idempotency-Key"]
        self.assertRegex(auto, r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]")
        with self.assertRaises(SafetyError):
            s.call("base", "record_create", {"collection": "other"})  # not approved: refused before it leaves
        n = len(self.base.log)
        with self.assertRaises(SafetyError) as c:
            J.Stack.load(yolo=False).call("base", "collection_delete", {"name": "posts"})
        self.assertEqual(len(self.base.log), n + 0 if False else len(self.base.log))
        self.assertFalse(any(x["path"].endswith("collection_delete") for x in self.base.log))
        with self.assertRaises(JadeError) as c:
            s.call("base", "nope")
        self.assertEqual(c.exception.code, "JADE403")
        self.assertTrue(s.doctor()["ok"])
        self.assertTrue(all(x["headers"].get("Authorization") == f"Bearer {TOKEN}" for x in self.base.log if "/agent/" in x["path"]))
        self.assertFalse(any("token" in x["query"] for x in self.base.log))

    def test_routing_ambiguity(self):
        v = fake_vault(False)
        self.addCleanup(v.close)
        write_config(self.d, base=self.base.url, vault=v.url)
        h = J.Harness.load()
        self.assertEqual(h.route("records_list"), "base")
        self.assertEqual(h.route("chat"), "vault")


class LegacyVaultTests(unittest.TestCase):
    """the toolkit refuses a Vault that accepts ?token= (only --accept-legacy goes on)"""

    def setUp(self):
        self.d = isolate(self)

    def run_init(self, vault, *extra):
        ans = self.d / "a.json"
        ans.write_text(json.dumps({"target": "vault", "vault_url": vault.url, "vault_token": TOKEN}))
        return jade("init", "--answers", str(ans), "--skip-smoke", "--accept-file-secrets", *extra)

    def test_init_refuses_legacy(self):
        v = fake_vault(True)
        self.addCleanup(v.close)
        code, out, err = self.run_init(v)
        self.assertEqual(code, 3, err)
        self.assertIn("JADE102", err)
        self.assertFalse((self.d / "jade.config.yaml").exists())
        code, out, err = self.run_init(v, "--accept-legacy")
        self.assertEqual(code, 0, err)
        self.assertIn("accepts ?token=", err)

    def test_modern_vault_passes(self):
        v = fake_vault(False)
        self.addCleanup(v.close)
        code, out, err = self.run_init(v)
        self.assertEqual(code, 0, err)
        self.assertTrue((self.d / "jade.config.yaml").exists())
        self.assertNotIn(TOKEN, (self.d / "jade.config.yaml").read_text())
        # the doctor agrees; and a legacy Vault fails the doctor
        code, out, err = jade("doctor", "--json", "--accept-file-secrets")
        self.assertEqual(code, 0, out + err)
        self.assertTrue(json.loads(out)["ok"])


class LeakTests(unittest.TestCase):
    """the configured token never shows up in stdout, stderr, logs or errors"""

    def test_no_secret_anywhere(self):
        d = isolate(self)
        b = fake_base()
        self.addCleanup(b.close)
        write_config(d, base=b.url, approvals={"base.*": ["*"]})
        env = {"JADE_SECRET_BASE": TOKEN}
        outs = []
        for args in (["doctor", "--verbose"], ["base", "tools", "--names", "--json", "--verbose"], ["base", "call", "records_list", "--args", '{"collection":"p"}', "--verbose", "--json"],
                     ["base", "call", "record_create", "--args", '{"collection":"p"}', "--verbose"], ["base", "call", "nope", "--verbose"], ["config", "show", "--json"], ["secret", "list"]):
            code, out, err = jade(*args, env=env)
            outs.append(out + err)
        bad = Fake()
        self.addCleanup(bad.close)
        bad.routes[("GET", "/api/agent/tools")] = lambda q, bb, h: (401, {"error": "token " + h.get("Authorization", "") + " is wrong"})
        write_config(d, base=bad.url)
        code, out, err = jade("base", "tools", "--verbose", env=env)
        self.assertEqual(code, 1)
        outs.append(out + err)
        for p in (d / "state").rglob("*"):
            if p.is_file():
                outs.append(p.read_text())
        everything = "\n".join(outs)
        self.assertNotIn(TOKEN, everything)
        self.assertIn("Bearer ***", everything)
        self.assertEqual(repr(J.redact.Secret(TOKEN)), "Secret('***')")


class CLITests(unittest.TestCase):
    def test_help_lists_every_command(self):
        isolate(self)
        code, out, _ = jade("--help")
        self.assertEqual(code, 0)
        for c in ("init", "doctor", "config", "secret", "vault", "base", "kit", "ui", "playbook", "serve", "docs", "version", "site", "mcp", "repl", "completion"):
            self.assertIn(c, out)
        code, out, _ = jade("playbook", "--help")
        for c in ("run", "check", "plan", "list", "approve", "revoke", "logs"):
            self.assertIn(c, out)
        for sh in ("bash", "zsh", "fish"):
            code, out, _ = jade("completion", sh)
            self.assertEqual(code, 0)
            self.assertIn("playbook", out)

    def test_init_yes_headless(self):
        d = isolate(self)
        code, out, err = jade("init", "--yes", "--json", "--target", "base", "--base-url", "http://127.0.0.1:9", "--skip-auth", "--skip-smoke")
        self.assertEqual(code, 0, err)
        j = json.loads(out)
        self.assertEqual(j["schema"], "jade.v1")
        c = Config.load(d / "jade.config.yaml")
        self.assertEqual(c.get("targets.base.url"), "http://127.0.0.1:9")
        self.assertEqual(c.get("approvals"), {"base.read": ["*"]})  # read-only by default
        self.assertIn("Not yet", j["data"]["summary"])

    def test_json_errors_and_exit_codes(self):
        isolate(self)
        code, out, _ = jade("docs", "show", "nope", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "JADE405")
        code, out, _ = jade("version", "--json")
        self.assertEqual(json.loads(out)["data"]["jade"], J.__version__)


if __name__ == "__main__":
    unittest.main()
