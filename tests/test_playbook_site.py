import json
import os
import unittest
from pathlib import Path

import yaml
from helpers import ROOT, TOKEN, fake_base, isolate, jade, write_config

import jade as J
from jade import playbook
from jade.errors import JadeError, PlaybookError
from jade.playbook import template
from jade.playbook.engine import SCHEMA, Playbook

EX = ROOT / "examples"


def pb(tasks, **spec):
    return Playbook({"apiVersion": "jade/v1", "kind": "Playbook", "metadata": {"name": "t"}, "spec": {"tasks": tasks, **spec}})


class TemplateTests(unittest.TestCase):
    def test_expressions(self):
        ctx = {"a": 2, "s": "Hi", "d": {"x": [1, {"y": "z"}]}, "ok": True}
        r = template.render
        self.assertEqual(r("{{ a }}", ctx), 2)
        self.assertEqual(r("{{ d.x.1.y }}", ctx), "z")
        self.assertEqual(r("n={{ a }}!", ctx), "n=2!")
        self.assertEqual(r("{{ s | lower }}", ctx), "hi")
        self.assertEqual(r("{{ missing | default('x') }}", ctx), "x")
        self.assertTrue(r("{{ a == 2 and not (s != 'Hi') }}", ctx))
        self.assertEqual(r("{{ d.x | length }}", ctx), 2)
        self.assertEqual(r("{% raw %}{{ a }}{% endraw %} {{ a }}", ctx), "{{ a }} 2")
        for bad in ("{{ missing }}", "{{ a.__class__ }}", "{{ open('x') }}", "{{ __import__ }}", "{{ a | shell }}"):
            with self.subTest(bad=bad), self.assertRaises(PlaybookError):
                r(bad, ctx)


class PlaybookTests(unittest.TestCase):
    def setUp(self):
        self.d = isolate(self)

    def test_examples_check_and_plan(self):
        for p in sorted(EX.glob("*.playbook.yaml")):
            with self.subTest(p=p.name):
                x = playbook.load(p)
                self.assertTrue(x.check()["ok"])
                plan = x.plan()
                self.assertTrue(plan["calls"])
                for c in plan["calls"]:
                    self.assertIn(c["target"], ("base", "vault", "kit", "local"))

    def test_example_emitted_calls(self):
        calls = playbook.load(EX / "provision-booking-app.playbook.yaml").plan()["calls"]
        self.assertEqual([(c["target"], c["tool"]) for c in calls],
                         [("base", "collection_create"), ("vault", "flow"), ("vault", "chat"), ("local", "shell"), ("local", "shell")])
        self.assertEqual(calls[0]["args"]["name"], "bookings")
        self.assertEqual([c["section"] for c in calls][-2:], ["rescue", "always"])
        b = playbook.load(EX / "base-products.playbook.yaml").plan({"collection": "items"})["calls"]
        self.assertEqual([c["tool"] for c in b], ["collection_create", "record_create", "record_create", "records_list"])
        self.assertIsNone(b[-1]["idempotency_key"])
        self.assertEqual(b[1]["args"]["collection"], "items")
        self.assertEqual(playbook.load(EX / "base-products.playbook.yaml").plan({"collection": "items"})["calls"][1]["idempotency_key"], b[1]["idempotency_key"])
        self.assertNotEqual(playbook.load(EX / "base-products.playbook.yaml").plan({"collection": "other"})["calls"][1]["idempotency_key"], b[1]["idempotency_key"])
        v = playbook.load(EX / "vault-digest.playbook.yaml").plan()
        self.assertEqual(v["schedule"]["target"], "vault")
        self.assertEqual([c["tool"] for c in v["calls"]], ["status", "flow", "chat"])
        k = playbook.load(EX / "kit-page.playbook.yaml").plan()["calls"]
        self.assertEqual((k[0]["target"], k[0]["tool"], k[0]["args"]["out"]), ("kit", "page", "agent.html"))

    def test_plan_makes_no_calls(self):
        b = fake_base()
        self.addCleanup(b.close)
        write_config(self.d, base=b.url)
        code, out, err = jade("playbook", "plan", str(EX / "provision-booking-app.playbook.yaml"), "--json", env={"JADE_SECRET_BASE": TOKEN})
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out)["data"]["calls"]), 5)
        self.assertEqual(b.log, [])

    def test_strict_schema(self):
        cases = [({"tasks": [{"tool": "x", "nope": 1}]}, "unknown key"), ({"tasks": [{"tool": "x", "command": "ls"}]}, "exactly one"),
                 ({"tasks": [{"tool": "x"}], "schedule": "daily", "targets": ["base"]}, "Base has no scheduler"),
                 ({"tasks": [{"tool": "x", "target": "mars"}]}, "target"), ({"tasks": []}, "at least one"),
                 ({"tasks": [{"tool": "x", "rescue": [{"tool": "y"}]}]}, "rescue"), ({"tasks": [{"tool": "x"}], "bogus": 1}, "unknown key")]
        for spec, msg in cases:
            with self.subTest(spec=spec), self.assertRaises(PlaybookError) as c:
                pb(**spec)
            self.assertIn(msg, c.exception.message)
        with self.assertRaises(PlaybookError) as c:
            pb([{"tool": "record_create", "target": "base", "args": {"x": "{{ nope }}"}}]).check()
        self.assertIn("nope", c.exception.message)
        with self.assertRaises(PlaybookError) as c:
            pb([{"tool": "record_create", "target": "base"}], defaults={"fail_mode": "rollback"}).check()
        self.assertIn("undo", c.exception.message)
        with self.assertRaises(PlaybookError):
            pb([{"tool": "ui_render", "target": "vault"}], targets=["vault"]).check()

    def test_schema_file_in_sync(self):
        self.assertEqual(json.loads((ROOT / "schema/playbook.v1.json").read_text()), SCHEMA)

    def test_check_against_live_tools(self):
        b = fake_base()
        self.addCleanup(b.close)
        write_config(self.d, base=b.url)
        os.environ["JADE_SECRET_BASE"] = TOKEN
        self.addCleanup(os.environ.pop, "JADE_SECRET_BASE", None)
        h = J.Harness.load()
        with self.assertRaises(PlaybookError) as c:
            pb([{"tool": "records_list", "target": "base", "args": {"colection": "x"}}]).check(h)
        self.assertIn("unknown argument", c.exception.message)
        with self.assertRaises(PlaybookError) as c:
            pb([{"tool": "no_such", "target": "base"}]).check(h)
        self.assertIn("no tool", c.exception.message)

    def test_run_approve_resume(self):
        b = fake_base()
        self.addCleanup(b.close)
        write_config(self.d, base=b.url, approvals={"base.read": ["*"], "base.write": ["record_create:*"]})
        os.environ["JADE_SECRET_BASE"] = TOKEN
        self.addCleanup(os.environ.pop, "JADE_SECRET_BASE", None)
        f = self.d / "two.playbook.yaml"
        f.write_text(yaml.safe_dump({"apiVersion": "jade/v1", "kind": "Playbook", "metadata": {"name": "two"}, "spec": {"targets": ["base"], "vars": {"c": "posts"}, "tasks": [
            {"name": "one", "tool": "record_create", "args": {"collection": "{{ c }}", "data": {"n": 1}}, "register": "r1"},
            {"name": "two", "tool": "record_create", "args": {"collection": "{{ c }}", "data": {"from": "{{ r1.result.id }}"}}}]}}))
        h = J.Harness.load()
        x = playbook.load(f)
        with self.assertRaises(JadeError) as c:
            list(x.run(h))
        self.assertEqual(c.exception.code, "JADE303")  # not approved, nobody to ask
        playbook.approve(x)
        ev = list(x.run(h))
        self.assertEqual(ev[-1]["event"], "done")
        self.assertTrue(ev[-1]["ok"])
        creates = [l for l in b.log if l["path"].endswith("record_create")]
        self.assertEqual(creates[1]["body"]["data"]["from"], "r1")
        # a finished run with the same vars runs again (new run); an interrupted one resumes
        st = playbook.runs("two")
        self.assertEqual(st[0]["status"], "completed")
        # edit → approval gone
        f.write_text(f.read_text() + "\n# changed\n")
        self.assertFalse(playbook.approved(playbook.load(f)))

    def test_resume_skips_finished(self):
        b = fake_base()
        self.addCleanup(b.close)
        write_config(self.d, base=b.url, approvals={"base.*": ["*"]})
        os.environ["JADE_SECRET_BASE"] = TOKEN
        self.addCleanup(os.environ.pop, "JADE_SECRET_BASE", None)
        calls = {"n": 0}
        orig = b.routes[("POST", "/api/agent/tools/record_create")]

        def flaky(q, body, hd):
            calls["n"] += 1
            if body["collection"] == "fail" and calls["n"] == 2:
                return 400, {"error": "boom"}
            return orig(q, body, hd)
        b.routes[("POST", "/api/agent/tools/record_create")] = flaky
        x = pb([{"name": "a", "tool": "record_create", "target": "base", "args": {"collection": "ok"}},
                {"name": "b", "tool": "record_create", "target": "base", "args": {"collection": "fail"}}], targets=["base"])
        playbook.approve(x)
        h = J.Harness.load()
        ev = list(x.run(h))
        self.assertFalse(ev[-1]["ok"])
        ev2 = list(x.run(h))
        self.assertTrue(ev2[0]["resumed"])
        self.assertEqual([e["why"] for e in ev2 if e["event"] == "skip"], ["finished in an earlier attempt of this run"])
        self.assertTrue(ev2[-1]["ok"])
        self.assertEqual(calls["n"], 3)

    def test_rollback(self):
        b = fake_base()
        self.addCleanup(b.close)
        b.routes[("POST", "/api/agent/tools/record_create")] = lambda q, body, hd: (400, {"error": "nope"}) if body["collection"] == "bad" else (200, {"result": {"id": "x1"}})
        write_config(self.d, base=b.url, approvals={"base.*": {"allow": ["*"], "confirm": False}})
        os.environ["JADE_SECRET_BASE"] = TOKEN
        self.addCleanup(os.environ.pop, "JADE_SECRET_BASE", None)
        x = pb([{"name": "make", "tool": "record_create", "target": "base", "args": {"collection": "good"}, "register": "m", "undo": {"tool": "collection_delete", "args": {"name": "{{ m.result.id }}"}}},
                {"name": "break", "tool": "record_create", "target": "base", "args": {"collection": "bad"}, "undo": {"tool": "collection_delete", "args": {"name": "-"}}}],
               targets=["base"], defaults={"fail_mode": "rollback"})
        playbook.approve(x)
        ev = list(x.run(J.Harness.load()))
        rb = [e for e in ev if e["event"] == "rollback"]
        self.assertEqual(len(rb), 1)
        self.assertEqual([l["body"] for l in b.log if l["path"].endswith("collection_delete")], [{"name": "x1"}])


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.d = isolate(self)

    def test_templates_build(self):
        from jade.site.spec import Site, templates
        for t in templates():
            with self.subTest(t=t):
                r = Site(f"Site {t}", tagline="x", template=t, url="https://example.com").build(self.d / t)
                self.assertTrue((self.d / t / "index.html").exists())
                for p in r["pages"]:
                    rel = "index.html" if p == "/" else p.strip("/") + "/index.html"
                    html = (self.d / t / rel).read_text()
                    self.assertIn("<main id=\"main\">", html)
                    self.assertIn('lang="en"', html)
                self.assertTrue((self.d / t / "sitemap.xml").exists())

    def test_escaping(self):
        from jade.site.spec import Site
        s = Site('<script>alert(1)</script>', tagline='"><img src=x onerror=alert(1)>')
        s.page("/", "Home").add("nav").add("hero").add("markdown", text="<script>x</script> [a](javascript:alert(1))").add("footer")
        r = s.build(self.d / "x")
        h = (self.d / "x/index.html").read_text()
        self.assertNotIn("<script>alert(1)", h)
        self.assertNotIn("<img src=x", h)
        self.assertNotIn("javascript:alert", h)

    def test_spec_errors(self):
        from jade.site.spec import Site
        for spec, msg in [({"name": "x", "theme": "pink"}, "theme"), ({"name": "x", "pages": [{"path": "/", "sections": ["heroo"]}]}, "unknown type"),
                          ({"name": "x", "pages": [{"path": "/", "sections": [{"type": "hero", "colour": 1}]}]}, "unknown parameter"),
                          ({"name": "x", "backend": {"providers": [{"name": "o", "api_key": "sk-123"}]}}, "api_key_env"), ({"name": "x", "nope": 1}, "unknown key")]:
            with self.subTest(msg=msg), self.assertRaises(JadeError) as c:
                Site(**spec).check()
            self.assertIn(msg, c.exception.message)

    def test_cli_site_flow_and_deploy_plan(self):
        code, out, err = jade("site", "new", "Acme", "--template", "saas", "--json")
        self.assertEqual(code, 0, err)
        code, out, err = jade("site", "build", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)["data"]
        self.assertIn("pricing/index.html", data["files"])
        code, out, err = jade("site", "plan", "--json")
        self.assertEqual(code, 0, err)
        calls = json.loads(out)["data"]["calls"]
        tools = [c["tool"] for c in calls]
        for t in ("module_enable", "provider_set", "model_set", "plan_set", "billing_setup", "plan_publish", "site_write"):
            self.assertIn(t, tools)
        prov = next(c for c in calls if c["tool"] == "provider_set")
        self.assertIn(prov["args"]["api_key"], ("***", "<secrets.OLLAMA_API_KEY>"))  # never the value
        code, out, err = jade("site", "deploy", "--json", "--no-input")
        self.assertEqual(code, 1)
        self.assertIn("OLLAMA_API_KEY", out)


class DocsTests(unittest.TestCase):
    def test_browser(self):
        from jade import docs
        t = [x["topic"] for x in docs.topics()]
        for need in ("start", "agents", "sites", "playbooks", "commands", "errors", "sections"):
            self.assertIn(need, t)
        self.assertIn("rollback", docs.show("playbooks#failure-modes"))
        self.assertTrue(docs.search("idempotency")[0]["ref"])
        with self.assertRaises(JadeError):
            docs.show("playbooks#nope")
        # every command and error is documented (generated)
        from jade import commands, errors
        cmds = docs.show("commands")
        for c in commands.REGISTRY:
            self.assertIn(f"## {c}", cmds)
        for code in errors.CODES:
            self.assertIn(code, docs.show("errors"))

    def test_committed_docs_are_current(self):
        import subprocess, sys
        p = subprocess.run([sys.executable, str(ROOT / "build/build.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        agents = (ROOT / "AGENTS.md").read_text()
        self.assertTrue(agents.startswith("<!-- jade-agent-stack "))
        self.assertTrue(agents.rstrip().endswith("not this file -->"))


if __name__ == "__main__":
    unittest.main()
