---
title: "CLI, REPL, MCP and HTTP"
summary: "The same commands on every surface, with the same JSON payloads."
tags: [cli, repl, jsonl, mcp, http, serve]
applies_to: stack
audience: both
since: 0.1.0
order: 50
---
# CLI, REPL, MCP and HTTP

One registry of commands (`jade commands`) serves every surface. Results are the same JSON values everywhere.

## CLI

`jade <group> <command> [args] [--json] [--verbose]`. Exit codes: 0 ok, 1 user error, 2 remote error, 3 refused for
safety. `--json` prints `{"schema": "jade.v1", "ok": true, "command": "…", "data": …}` or `{"ok": false, "error":
{"code", "message", "remediation"}}`. `--verbose` prints HTTP calls with Authorization and secrets redacted.
After a failed `jade doctor`, commands that touch targets refuse until it passes, or `--force`.
Completion: `eval "$(jade completion bash)"` (also zsh, fish).

## REPL

`jade repl`: type commands without `jade`, arguments as values then `key=value` (JSON allowed).
`help`, `help site.build`, `commands`, `docs search …`.

## JSON lines

`jade repl --jsonl` reads one request per line and writes one answer per line:

```json
{"id": 1, "cmd": "docs.search", "args": {"query": "approvals"}}
{"id": 1, "schema": "jade.v1", "ok": true, "command": "docs.search", "data": [ … ]}
```

## MCP

`jade mcp` serves the commands as MCP tools over stdio: `site_build`, `site_plan`, `site_deploy`, `playbook_run`,
`docs_search`, `docs_show`, `base_call`, … Nothing asks a person there: approvals in the config decide, and playbooks
must be approved.

```json
{"mcpServers": {"jade": {"command": "jade", "args": ["mcp"]}}}
```

## HTTP

`jade serve` (127.0.0.1:9765; other hosts need `--token`, sent as `Authorization: Bearer`; tokens in URLs are refused):

| Route | Does |
| --- | --- |
| `GET /healthz` | liveness |
| `GET /v1/playbooks` | playbooks and their approval |
| `POST /v1/playbooks/{name}/run` | `{"vars": {…}, "fresh": false}` |
| `GET /v1/commands`, `POST /v1/commands/{name}` | any command |
| `GET /v1/docs`, `GET /v1/docs/{topic}?section=…`, `GET /v1/docs/search?q=…` | the docs browser |
