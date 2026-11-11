---
title: "Playbooks"
summary: "Portable YAML automation over Vault, Base, Kit and local commands; check, plan, run, approve."
tags: [playbook, yaml, approval, idempotency, resume]
applies_to: stack
audience: both
since: 0.1.0
order: 20
---
# Playbooks

A playbook (`*.playbook.yaml`) compiles to each target's existing primitives: Base tools, Vault's HTTP API, a Kit page
and local commands. It does not replace Vault playbooks, flows or Jade Lisp. The schema is
`schema/playbook.v1.json` (and `jade docs show playbook-schema`).

## Example

```yaml
apiVersion: jade/v1
kind: Playbook
metadata: {name: base-products, description: A products collection}
spec:
  targets: [base]
  scopes: [read, write, schema]        # the run's short-lived task credential
  vars: {collection: products}
  defaults: {fail_mode: rollback}
  tasks:
    - name: Products collection
      tool: collection_create
      args: {name: "{{ collection }}", fields: [{name: title, type: text}]}
      register: col
      undo: {tool: collection_delete, args: {name: "{{ collection }}", confirm: "{{ collection }}"}}
```

## Targets

| Target | Tools | Notes |
| --- | --- | --- |
| `base` | every tool the token may use (`jade base tools`) | arguments are checked against the tool's schema at check time |
| `vault` | `chat`, `flow`, `status`, `flows`, `chats`, `history` | Vault-only tools (ui_render, notify) run inside a Vault flow |
| `kit` | `page` | writes a page that runs Kit in a browser |
| `local` | `command: "…"` | allowed by `approvals.shell` |

A task without `target` goes to the one allowed target that owns the tool; two owners is an error.

## Task fields

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | shown in events and logs |
| `target` | vault, base, kit, local | where it runs |
| `tool` / `command` / `block` | string / string / list | exactly one |
| `args` | mapping | the tool's arguments (expressions allowed) |
| `register` | name | keep `{ok, changed, result, error}` under this name |
| `when` | expression | run only if true |
| `retries`, `delay` | int 0–10, seconds | try again on failure or while `until` is false |
| `until` | expression | done when true |
| `undo` | `{tool, args, target}` or `{command}` | how to reverse it (rollback) |
| `idempotency_key` | string | override the default key |
| `fail_mode` | stop, continue, rollback | this task's failure handling |
| `rescue`, `always` | lists | with `block`: on failure / in every case |
| `timeout` | duration | for this call |

## Expressions

`{{ name }}`, `{{ created.result.id }}`, `{{ items.0 }}`, literals, `==` `!=` `<` `<=` `>` `>=` `and` `or` `not` `in`,
filters `default(x)` `lower` `upper` `trim` `json` `length` `string` `int`. `{% raw %}…{% endraw %}` keeps text as it
is. No calls, no imports, no I/O. An unknown name is an error unless `| default()` is used.

## Failure modes

| Mode | On a failed task |
| --- | --- |
| `stop` | stop the run (default) |
| `continue` | go on with the next task; the run stays ok (use it for checks like "is it there?") |
| `rollback` | run each finished task's `undo` in reverse, then stop. `check` refuses a rollback playbook whose mutating tasks lack `undo` |

## Idempotency and resume

Every mutating call carries a key: `sha256(playbook | task | vars)` by default (`idempotent_strategy: key`),
`content-hash` (the rendered arguments) or `none` (a new UUIDv7 each run). Base runs a key once and replays the first
answer. Runs are recorded in `~/.local/state/jade/runs/`; running again with the same vars resumes, skipping finished
tasks. States: not_started, in_progress, completed, refused, failed, interrupted, resumable.

## Approval

A playbook that changes Vault or Base starts unapproved. `jade playbook approve NAME` signs its SHA-256 with a local
key; any edit invalidates it. Unattended runs (`--no-input`, MCP, HTTP) need the approval; interactive runs ask.

## Schedules

`spec.schedule: "every weekday at 9am"` needs the vault target: `jade playbook plan` prints the equivalent Vault
schedule. Base has no scheduler, by design.

## Commands

`jade playbook list | check | plan | run | approve | revoke | logs NAME [--var k=v …] [--json]`
