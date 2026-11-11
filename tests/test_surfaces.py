import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request

from helpers import ROOT, isolate

from jade import commands
from jade.errors import JadeError


def proc(*args, input=""):
    p = subprocess.run([sys.executable, "-m", "jade.cli", *args], input=input, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=60)
    return p.stdout, p.stderr


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.d = isolate(self)

    def test_jsonl(self):
        reqs = [{"id": 1, "cmd": "docs.search", "args": {"query": "approvals"}}, {"id": 2, "cmd": "site.templates"}, {"id": 3, "cmd": "nope"},
                {"id": 4, "cmd": "config.set", "args": {"assignment": 'approvals.base.write=["*"]'}}, {"id": 5, "cmd": "site.new", "args": {"name": "X", "template": "landing"}}]
        out, err = proc("repl", "--jsonl", input="\n".join(json.dumps(r) for r in reqs) + "\n")
        res = {r["id"]: r for r in map(json.loads, out.splitlines())}
        self.assertTrue(res[1]["ok"] and res[1]["data"])
        self.assertIn("saas", res[2]["data"])
        self.assertEqual(res[3]["error"]["code"], "JADE405")
        self.assertEqual(res[4]["error"]["code"], "JADE302")  # an agent cannot widen its approvals
        self.assertTrue(res[5]["ok"] and (self.d / "jade.site.yaml").exists())

    def test_mcp_stdio(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "docs_show", "arguments": {"ref": "playbooks#targets"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "playbook_approve", "arguments": {"name": "x"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "site_sections", "arguments": {"name": "hero"}}}]
        out, err = proc("mcp", input="\n".join(json.dumps(m) for m in msgs) + "\n")
        res = {r["id"]: r for r in map(json.loads, out.splitlines())}
        self.assertEqual(set(res), {1, 2, 3, 4, 5})
        names = [t["name"] for t in res[2]["result"]["tools"]]
        for n in ("site_build", "site_deploy", "playbook_run", "docs_search", "base_call", "vault_flow_run"):
            self.assertIn(n, names)
        self.assertIn("vault", res[3]["result"]["content"][0]["text"])
        self.assertTrue(res[4]["result"]["isError"])
        self.assertIn("JADE302", res[4]["result"]["content"][0]["text"])
        self.assertIn("title", res[5]["result"]["content"][0]["text"])

    def test_http(self):
        from jade.serve import make_server
        with self.assertRaises(JadeError):
            make_server("0.0.0.0", 0, None, commands.Context())
        srv = make_server("127.0.0.1", 0, "serve-token-123456", commands.Context())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        u = f"http://127.0.0.1:{srv.server_address[1]}"

        def req(path, body=None, token="serve-token-123456"):
            r = urllib.request.Request(u + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET",
                                       headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
            try:
                with urllib.request.urlopen(r) as x:
                    return x.status, json.loads(x.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        self.assertEqual(req("/healthz", token=None)[0], 200)
        self.assertEqual(req("/v1/playbooks", token=None)[0], 401)
        self.assertEqual(req("/v1/playbooks?token=serve-token-123456", token=None)[0], 400)
        st, j = req("/v1/docs/search?q=rollback")
        self.assertEqual(st, 200)
        self.assertEqual(j["schema"], "jade.v1")
        st, j = req("/v1/commands/site.themes", {})
        self.assertIn("ocean", j["data"])
        st, j = req("/v1/commands/playbook.approve", {"name": "x"})
        self.assertEqual((st, j["error"]["code"]), (403, "JADE302"))
        st, j = req("/v1/playbooks/nope/run", {"vars": {}})
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
