# Decisions

Assumptions, guesses and judgments, so a later pass can correct them. Newest first. The implementation brief
(architecture §2) is followed; where this toolkit departs from the brief's details, the reason is here.

## 2026-11 · 0.1.0

### Departures from the brief

| Brief | Here | Why |
| --- | --- | --- |
| Dependencies: httpx, pydantic, typer, keyring, pyyaml, rich | PyYAML only; keyring optional (`[keyring]`) | A solo maintainer and agents installing it often: one dependency means fewer breakages and a fast install. The standard library covers HTTP (urllib), CLI (argparse) and validation (hand-written, strict, with paths in messages). |
| Async-first with `jade.sync` | Blocking core with `jade.aio` wrappers (asyncio.to_thread) | The callers today (CLI, REPL, MCP stdio, HTTP, scripts) are blocking; a sync core is simpler to test. The async API exists for asyncio programs. |
| Astro/Starlight or VitePress, Pagefind | Docs built by the toolkit itself (`build/build.py`), with a small offline search index | No Node toolchain to maintain for docs. One source: `src/jade/docs/*.md` plus pages generated from the code (commands, errors, sections, themes, schema, versions), so an undocumented command cannot exist. |
| `/api/agent/playbooks/{name}/run` on Base | Not added | Base does not run tasks (it hosts no agent and runs no schedules). Playbooks run in the toolkit or Vault and call Base's tools; every call is in Base's audit log. |
| Vault tools such as `ui_render`, `notify` as playbook targets | Not available: Vault's HTTP API offers chat, flow, status, flows, chats, history | The toolkit only uses documented interfaces. Run Vault-only tools inside a Vault flow, and call the flow. To do: an issue on jade-vault for a tool endpoint. |
| `jade.config.yaml` for everything | Config in `jade.config.yaml`; sites in `jade.site.yaml`; playbooks in `*.playbook.yaml` | Different lifecycles: config is per machine, a site spec belongs to its project. |
| Versioned docs `/v0.1/` and `/latest/` | One version (0.1.0) | There is one release. Add versions when there are two. |
| mypy --strict, 90% coverage | Not enforced yet | Typed where it helps; 36 tests including real Base and browser end-to-end. Next pass. |

### Judgments

- **Sites are part of the toolkit.** The project owner asked for site construction by CLI, API and Python; a site deploy
  is a generated playbook, so it gets approvals, idempotency, task credentials and resume for free.
- **Agents cannot widen their own permissions.** Over MCP, HTTP and JSON lines, changing approvals, secrets, target
  URLs, approving a playbook or `site deploy --yes` is refused (JADE302). An agent with a shell running as the person can
  still do what the person can; the docs say so.
- **Deploy keys are content hashes**, so deploying the same site twice is all replays and changes nothing.
- **`fail_mode: continue` failures keep a run ok** (used for "is it there?" checks). Stop and rollback failures fail it.
- **Templates come from ./templates, then ~/.config/jade/templates, then the built-in ones**, so a settled design is
  reused instead of rebuilt.
- **Generated pages pin the UI/UX and Kit versions** (compat.CDN). Those tags must exist: releases are made by the owner.
- **A Vault that accepts `?token=` is refused**, detected by `/v1/health` `query_token: false` (Vault 2.18.3+) or by
  probing `/v1/status?token=` with the real token. The Vault fix exists on a local branch and is not yet released.
