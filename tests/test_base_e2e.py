"""End to end against a real Jade Agent Base, built from ../jade-agent-base (or $JAB_DIR). Skipped without Go or the repo."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from helpers import REAL_HOME, ROOT, isolate, jade

SRC = Path(os.environ.get("JAB_DIR") or ROOT.parent / "jade-agent-base")


def req(method, url, body=None, token=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                               headers={"Content-Type": "application/json", **({"Authorization": token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.status, x.read().decode(), dict(x.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


@unittest.skipUnless(shutil.which("go") and (SRC / "agent" / "credentials.go").exists(), "needs Go and jade-agent-base 0.6 (JAB_DIR)")
class BaseE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="jab-e2e-"))
        cls.bin = cls.tmp / "jab"
        subprocess.run(["go", "build", "-o", str(cls.bin), "./cmd/jab"], cwd=SRC, check=True, capture_output=True)
        data = cls.tmp / "pb_data"
        run = lambda *a: subprocess.run([str(cls.bin), *a, "--dir", str(data)], check=True, capture_output=True, text=True).stdout.strip()
        run("superuser", "upsert", "root@example.com", "1234567890")
        cls.token = run("agent", "create", "boss", "--scopes", "all").splitlines()[-1]
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); cls.port = s.getsockname()[1]; s.close()
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.srv = subprocess.Popen([str(cls.bin), "serve", "--http", f"127.0.0.1:{cls.port}", "--dir", str(data), "--publicDir", str(cls.tmp / "pub"), "--hooksDir", str(cls.tmp / "hooks")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if req("GET", cls.url + "/api/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.kill()
        cls.srv.wait()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.d = isolate(self)
        (self.d / "jade.config.yaml").write_text(yaml.safe_dump({"version": 1, "targets": {"base": {"url": self.url, "token": "base"}},
                                                                 "approvals": {"base.*": {"allow": ["*"], "confirm": False}}}))
        self.env = {"JADE_SECRET_BASE": self.token}

    def test_doctor_tools_call_and_replay(self):
        code, out, err = jade("doctor", "--json", env=self.env)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(out)["data"]["targets"]["base"]["version"], "0.6.0")
        code, out, err = jade("base", "call", "collection_create", "--args", '{"name":"notes","fields":[{"name":"t","type":"text"}]}', "--idempotency-key", "e2e-1", "--json", env=self.env)
        self.assertEqual(code, 0, out + err)
        code2, out2, _ = jade("base", "call", "collection_create", "--args", '{"name":"notes","fields":[{"name":"t","type":"text"}]}', "--idempotency-key", "e2e-1", "--json", env=self.env)
        self.assertEqual(code2, 0, out2)  # replayed, not run twice (a second create would fail)
        code3, out3, _ = jade("base", "call", "collection_create", "--args", '{"name":"other","fields":[]}', "--idempotency-key", "e2e-1", "--json", env=self.env)
        self.assertEqual(json.loads(out3)["error"]["code"], "JADE205")
        code, out, _ = jade("base", "audit", "--json", env=self.env)
        self.assertIn("e2e-1", out)
        self.assertNotIn(self.token, out)

    def test_site_deploy_and_redeploy(self):
        (self.d / "jade.site.yaml").write_text(yaml.safe_dump({"name": "Lumen", "tagline": "Join early.", "template": "waitlist", "url": self.url, "backend": {"url": self.url}}))
        code, out, err = jade("site", "deploy", "--yes", "--no-input", "--json", env=self.env)
        self.assertEqual(code, 0, out + err)
        st, page, _ = req("GET", self.url + "/")
        self.assertEqual(st, 200)
        self.assertIn("Lumen", page)
        self.assertIn('<meta name="jade-base"', page)
        # the waitlist form's collection: anyone can join, nobody anonymous can read it
        self.assertEqual(req("POST", self.url + "/api/collections/waitlist/records", {"email": "a@example.com", "name": "Ada"})[0], 200)
        st, body, _ = req("GET", self.url + "/api/collections/waitlist/records")
        self.assertTrue(st in (403, 404) or json.loads(body)["items"] == [], body)
        # rate limits are on
        st, body, _ = req("POST", self.url + "/api/agent/tools/rate_limits", {}, self.token)
        self.assertTrue(json.loads(body)["result"]["enabled"])
        # the task credential was revoked after the run, and the audit log names the task
        st, body, _ = req("POST", self.url + "/api/agent/tools/records_list", {"collection": "agent_credentials"}, self.token)
        creds = json.loads(body)["result"]["items"]
        self.assertTrue(creds and all(c["revoked"] for c in creds), creds)
        st, body, _ = req("POST", self.url + "/api/agent/tools/audit_list", {"limit": 200}, self.token)
        self.assertIn("playbook:deploy-lumen", body)
        # deploying the same thing again changes nothing: the writes are replays
        code, out, err = jade("site", "deploy", "--yes", "--no-input", "--json", env=self.env)
        self.assertEqual(code, 0, out + err)
        st, body, _ = req("POST", self.url + "/api/agent/tools/audit_list", {"limit": 300, "tool": "site_write"}, self.token)
        items = json.loads(body)["result"]
        items = items.get("items", items) if isinstance(items, dict) else items
        self.assertTrue(any(i.get("replayed") for i in items), items[:2])

    def test_playbook_with_credential_and_rollback(self):
        code, out, err = jade("playbook", "approve", str(ROOT / "examples/base-products.playbook.yaml"), env=self.env)
        self.assertEqual(code, 0, err)
        code, out, err = jade("playbook", "run", str(ROOT / "examples/base-products.playbook.yaml"), "--var", "collection=teas", "--json", "--no-input", env=self.env)
        self.assertEqual(code, 0, out + err)
        events = json.loads(out)["data"]["events"]
        self.assertEqual(events[1]["event"], "credential")
        self.assertEqual(sorted(events[1]["scopes"]), ["read", "schema", "write"])
        st, body, _ = req("POST", self.url + "/api/agent/tools/records_list", {"collection": "teas"}, self.token)
        self.assertEqual(len(json.loads(body)["result"]["items"]), 2)
        # rollback: the second task fails, the first is undone
        f = self.d / "rb.playbook.yaml"
        f.write_text(yaml.safe_dump({"apiVersion": "jade/v1", "kind": "Playbook", "metadata": {"name": "rb"}, "spec": {"targets": ["base"], "scopes": ["read", "schema", "write"],
            "defaults": {"fail_mode": "rollback"}, "tasks": [
                {"name": "make", "tool": "collection_create", "args": {"name": "temp", "fields": []}, "undo": {"tool": "collection_delete", "args": {"name": "temp", "confirm": "temp"}}},
                {"name": "fail", "tool": "record_create", "args": {"collection": "missing", "data": {}}, "undo": {"tool": "server_info"}}]}}))
        jade("playbook", "approve", str(f), env=self.env)
        code, out, err = jade("playbook", "run", str(f), "--json", "--no-input", env=self.env)
        self.assertEqual(code, 2, out)
        st, body, _ = req("POST", self.url + "/api/agent/tools/collection_get", {"name": "temp"}, self.token)
        self.assertNotEqual(st, 200, body)


    @unittest.skipUnless(shutil.which("node") and (ROOT.parent / "jade-agent-ui-ux" / "dist" / "jade-ui.js").exists() and (ROOT.parent / "jade-agent-ui-ux" / "node_modules" / "playwright").exists(),
                         "needs node, Playwright and ../jade-agent-ui-ux/dist")
    def test_browser_deployed_site(self):
        ui = ROOT.parent / "jade-agent-ui-ux" / "dist"
        shutil.copytree(ui, self.tmp / "pub" / "ui", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.map"))
        (self.d / "jade.site.yaml").write_text(yaml.safe_dump({
            "name": "Kettle", "tagline": "Tea.", "url": self.url, "cdn": {"ui": "/ui/jade-ui.js"}, "backend": {"url": self.url, "collections": [
                {"name": "signups", "fields": "email:email!, name:text", "create": "anyone"},
                {"name": "leaves", "fields": "title:text!, description:text", "list": "anyone", "view": "anyone"}]},
            "pages": [{"path": "/", "title": "Home", "sections": ["nav", {"type": "form", "collection": "signups", "fields": ["email:email!", "name:text"], "submit": "Join", "success": "You are on the list."},
                                                               {"type": "records", "collection": "leaves", "text_field": "description"}, "footer"]},
                      {"path": "/account", "title": "Account", "sections": ["nav", {"type": "auth", "next": "/"}, "footer"]}]}))
        code, out, err = jade("site", "deploy", "--yes", "--no-input", "--json", env=self.env)
        self.assertEqual(code, 0, out + err)
        for t in ("Sencha", "Assam"):
            req("POST", self.url + "/api/agent/tools/record_create", {"collection": "leaves", "data": {"title": t, "description": "nice"}}, self.token)
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path(REAL_HOME) / ".cache" / "ms-playwright")}
        p = subprocess.run(["node", str(ROOT / "tests/browser_site.mjs"), self.url], capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        r = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(r["form"] and r["native_validation"])
        self.assertEqual(sorted(r["records"]), ["Assam", "Sencha"])
        self.assertEqual(r["signed_up_and_redirected"], "/")
        self.assertEqual(r["errors"], [])
        st, body, _ = req("POST", self.url + "/api/agent/tools/records_list", {"collection": "signups"}, self.token)
        self.assertEqual([x["email"] for x in json.loads(body)["result"]["items"]], ["grace@example.com"])


if __name__ == "__main__":
    unittest.main()
