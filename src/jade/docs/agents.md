---
title: "For agents"
summary: "The shortest paths to a working site or backend, in the fewest tokens."
tags: [agents, recipes, tokens]
applies_to: stack
audience: agent
since: 0.1.0
order: 2
---
# For agents

Read this page, then only what a task needs (`jade docs show <topic>#<section>`). Prefer `--json` output.

## Rules

| Rule | Why |
| --- | --- |
| Start from a template: `name`, `tagline`, `template` is a whole site | three lines instead of hundreds |
| `jade site sections` (one line each), `jade site sections <name>` (one in full) | do not guess parameters |
| `jade site plan` before `jade site deploy` | see every call; makes none |
| Mutations carry idempotency keys automatically | a retry never runs twice |
| A `JADE103` (credential refused) or `JADE30x` (safety) error means stop | do not retry around a refusal |
| Secrets only by environment variable name (`api_key_env`) | never write a key into a file |

## A site in one file

```yaml
# jade.site.yaml
name: Acme AI
tagline: Embeddings for every app.
template: saas          # saas, chatbot, landing, waitlist, docs, portfolio, shop, dashboard
url: https://acme.example.com
backend:
  url: https://acme.example.com
```

```sh
jade site check --json && jade site build --json && jade site deploy --yes --json
```

## Reuse a design

When a design is settled, `jade site template save NAME` keeps it; later sites are `name`, `tagline`,
`template: NAME`. Read `jade site templates` before building anything new.

## Change one page

Pages from the spec replace the template's page with the same path; sections are a list:

```yaml
pages:
  - path: /
    title: Home
    sections:
      - nav
      - {type: hero, title: "Search that understands", buttons: [{label: Try it, href: /playground}]}
      - {type: form, collection: waitlist, fields: ["email:email!"], submit: Join}
      - footer
backend:
  collections:
    - {name: waitlist, fields: "email:email!", create: anyone, list: admin}
```

## Drive it from a program

| Surface | Use |
| --- | --- |
| `jade <command> --json` | one call, one JSON object (`schema: jade.v1`) |
| `jade repl --jsonl` | many calls over a pipe: `{"id":1,"cmd":"site.build","args":{}}` |
| `jade mcp` | MCP over stdio: tools `site_build`, `playbook_run`, `docs_search`, … |
| `jade serve` | HTTP: `POST /v1/commands/site.build`, `POST /v1/playbooks/{name}/run` |
| `import jade` | `jade.Site(...)`, `jade.Stack.load().run("site.build", dir=".")` |

## What needs a person

An agent must not widen its own permissions. Over MCP, HTTP and JSON lines these are refused with JADE302 and need a
person in a terminal: changing `approvals`, target URLs, `secrets.file` or `accept_legacy`; storing or deleting secrets;
`playbook approve`; `site deploy --yes`. Everything else, including `jade init --answers FILE`, an agent can do.
This guard holds for those surfaces. An agent with a shell running as you can do what you can, so run agents as a user
with less.

## Errors

Every error has a stable code and a remediation (`jade docs show errors`). Exit codes: 0 ok, 1 user error,
2 remote error, 3 refused for safety.
