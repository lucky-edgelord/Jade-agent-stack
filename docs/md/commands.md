---
title: "Commands"
summary: "Every command and its parameters, generated from the code."
applies_to: "stack"
audience: "both"
since: "0.1.0"
version: 0.1.0
---
# Commands

Every command, on every surface (CLI `jade a b`, REPL `a b`, JSON lines `a.b`, MCP `a_b`, HTTP `POST /v1/commands/a.b`).

## version

The toolkit version and the versions it works with.

`jade version`

## doctor

Check the config, secrets and every target: reachable, authenticated, compatible, no URL tokens.

`jade doctor`

## config.show

The configuration (it never holds secrets).

`jade config show`

## config.get

One configuration value by dotted key, e.g. targets.base.url.

`jade config get`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `key` (positional) required | str |  |  |

## config.set

Set a configuration value: KEY=VALUE (VALUE may be JSON).

`jade config set`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `assignment` (positional) required | str |  | key=value |

## config.edit

Open jade.config.yaml in $EDITOR, then check it.

`jade config edit` (CLI only)

## secret.set

Store a secret in the OS keyring. The value comes from --value, $JADE_SECRET_VALUE, or a hidden prompt.

`jade secret set`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `value` | str |  | avoid: shells keep history |

## secret.list

The names of stored secrets (never their values).

`jade secret list`

## secret.rm

Delete a stored secret.

`jade secret rm`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |

## vault.status

Vault's status (header auth; refuses a Vault that accepts URL tokens).

`jade vault status`

## vault.chat

Send a message to Vault's agent and wait for the answer.

`jade vault chat`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `message` (positional) required | str |  |  |
| `session` | str |  | a chat id, or new |
| `timeout` | float |  |  |

## vault.flows

Vault's flows.

`jade vault flows`

## vault.flow.run

Run a Vault flow by name.

`jade vault flow run`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `input` | json |  | JSON, -, or @file |
| `timeout` | float |  |  |

## base.tools

The tools this Base token may use.

`jade base tools`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `format` | str (openai, anthropic, mcp) |  | the shape: openai, anthropic or mcp (default: with scope and destructive) |
| `names` | bool |  | names only |

## base.call

Call a Base tool (approvals apply; mutations get an idempotency key).

`jade base call`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `tool` (positional) required | str |  |  |
| `args` | json |  | JSON, -, or @file |
| `idempotency_key` | str |  | default: a new UUIDv7 |
| `timeout` | float |  |  |

```sh
jade base call records_list --args '{"collection":"posts"}'
```

## base.audit

The audit log: what agents did (and what was refused).

`jade base audit`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `limit` | int | `50` | how many entries |
| `tool` | str |  |  |

## base.credential

Mint a short-lived task credential (prints only its id, scopes and expiry).

`jade base credential`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `task_id` (positional) required | str |  |  |
| `scopes` | list | `['read']` | the fewest scopes the task needs, comma-separated |
| `ttl` | str | `15m` | how long it lasts: 15m, 2h (at most 24h) |

## kit.page

Write a page that runs Jade Agent Kit in the browser.

`jade kit page`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `out` (positional) required | str |  |  |
| `features` | list | `['agent']` | Kit features to load, comma-separated (agent, sqlite, bm25, …) |
| `ollama` | str |  | Ollama host |
| `model` | str |  |  |
| `title` | str | `Jade agent` |  |

## ui.chat

Write a page with a chat: full-screen, inline or a floating widget.

`jade ui chat`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `out` (positional) required | str |  |  |
| `mount` | str (full-screen, widget, inline) | `full-screen` | full-screen, inline, or widget (a floating button) |
| `preset` | str | `jade` | a theme |
| `mode` | str (auto, light, dark) | `auto` | light, dark, or auto (follows the system) |
| `base` | str |  | a Jade Agent Base URL |
| `title` | str | `Chat` |  |

## playbook.list

Playbooks here (./, ./playbooks, ./examples) and whether each is approved.

`jade playbook list`

## playbook.check

Validate a playbook: schema, expressions, targets, and tools and arguments against the live targets.

`jade playbook check`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `offline` | bool |  | do not contact targets |

## playbook.plan

Every call a playbook would make, with arguments and idempotency keys. Makes no calls.

`jade playbook plan`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `var` | list |  | k=v, repeatable |

## playbook.run

Run a playbook (resumes an interrupted run with the same vars). Unattended runs need it approved.

`jade playbook run`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `var` | list |  | k=v, repeatable |
| `fresh` | bool |  | start over instead of resuming |

## playbook.approve

Approve a playbook as it is now (its hash is signed; any edit needs a new approval).

`jade playbook approve`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |

## playbook.revoke

Withdraw a playbook's approval.

`jade playbook revoke`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |

## playbook.logs

Runs of a playbook (or all) and the state of each task.

`jade playbook logs`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) | str |  |  |

## site.templates

Site templates (a spec can be just name, tagline and template).

`jade site templates`

## site.themes

Themes for sites and pages.

`jade site themes`

## site.sections

The section library: one line each, or one section's parameters in full.

`jade site sections`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) | str |  |  |

## site.new

Write a jade.site.yaml from a template.

`jade site new`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `template` | str | `landing` | a template (jade site templates) |
| `tagline` | str |  | one line under the name |
| `theme` | str |  | a theme (jade site themes) |
| `dir` | str | `.` | the folder for jade.site.yaml |
| `url` | str |  | the public address of the site |

## site.check

Check a site spec (and that it compiles).

`jade site check`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dir` (positional) | str | `.` |  |

## site.build

Compile the site to static files.

`jade site build`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dir` (positional) | str | `.` |  |
| `out` | str | `dist` | the output folder |
| `ui` | str |  | UI/UX module URL |
| `kit` | str |  | Kit module URL |

## site.plan

Every Base call a deploy would make (secrets shown as placeholders). Makes no calls.

`jade site plan`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dir` (positional) | str | `.` |  |

## site.deploy

Deploy the site to the Base target: settings, modules, collections, models, plans, billing, files.

`jade site deploy`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dir` (positional) | str | `.` |  |
| `yes` | bool |  | approve this deploy (needed when nobody can be asked) |

## site.preview

Build and serve the site on localhost (UI/UX from the CDN unless --ui).

`jade site preview` (CLI only)

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dir` (positional) | str | `.` |  |
| `port` | int | `8080` | the local port |
| `ui` | str |  | a UI/UX module URL (to preview a local build) |

## agent.ask

Ask an agent: on Vault (its agent), or on Base (a model from config.models using Base's tools, through approvals).

`jade agent ask`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `message` (positional) required | str |  |  |
| `target` | str (vault, base) | `vault` | vault (its agent) or base (a model here with Base tools) |
| `name` | str | `jade` | the agent session name |
| `steps` | int | `8` | at most this many tool rounds |

## docs.topics

Documentation topics.

`jade docs topics`

## docs.show

A docs topic, or one section: topic#heading.

`jade docs show`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `ref` (positional) required | str |  |  |

## docs.search

Search the docs; each hit has a ref for docs.show.

`jade docs search`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query` (positional) required | str |  |  |
| `limit` | int | `8` | how many results |

## docs.build

Build the docs: HTML for people, Markdown + llms.txt + catalog.json for agents.

`jade docs build` (CLI only)

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `out` (positional) | str | `docs` |  |
| `format` | str (html, md, both) | `both` | html, md or both |
| `check` | bool |  | fail if the committed output is stale |

## commands

Every command with its parameters (for agents).

`jade commands`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) | str |  |  |

## site.template.save

Keep this site's design as a template (theme, pages, sections, backend) to reuse: new sites become name + tagline + template.

`jade site template save`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` (positional) required | str |  |  |
| `dir` | str | `.` | the site folder |
| `about` | str |  | one line describing it |
| `project` | bool |  | save in ./templates (shared with the project) instead of your own templates |

```sh
jade site template save house --about 'Our look: ocean theme, pricing, account'
```

<!-- generated by docs build; edit src/jade/docs/(generated from the code) not this file -->
