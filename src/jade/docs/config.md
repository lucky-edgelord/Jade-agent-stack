---
title: "Configuration and secrets"
summary: "jade.config.yaml keys, discovery, the OS keyring, and the init wizard."
tags: [config, secrets, keyring, init]
applies_to: stack
audience: both
since: 0.1.0
order: 60
---
# Configuration and secrets

## Discovery

`$JADE_CONFIG`, else the nearest `jade.config.yaml` from the working directory upward.

## Keys

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `version` | int | `1` | config format |
| `targets.base.url` | URL | none | Jade Agent Base |
| `targets.base.token` | string | `jade.<host>` | keyring name of the agent token |
| `targets.base.credentials` | `{ttl, enabled}` | `{ttl: 15m, enabled: true}` | task credentials for playbooks |
| `targets.vault.url` | URL | none | Vault's HTTP API |
| `targets.vault.token` | string | `jade.<host>` | keyring name |
| `targets.vault.accept_legacy` | bool | `false` | diagnosis only |
| `targets.kit` | `{ollama, model, features}` | none | defaults for Kit pages |
| `models` | `{provider, url, key, fast, strong}` | none | the model for `agent --target base` |
| `approvals` | mapping | `{}` | see harness |
| `defaults.timeout` / `defaults.chat_timeout` | seconds | 30 / 300 | call timeouts |
| `secrets.file` | bool | `false` | allow the 0600 file store |
| `playbooks.routes` | `{tool: target}` | `{}` | resolve tools two targets have |

Unknown keys are errors. A URL with a token in it is refused.

## Secrets

| Where | When |
| --- | --- |
| OS keyring, service `jade` | with `keyring` installed and a backend available |
| `~/.config/jade/secrets.json` (mode 0600) | only with `--accept-file-secrets` or `secrets.file: true` |
| `JADE_SECRET_<NAME>` environment variables | always first (CI); name upper-cased, other characters as `_` |

`jade secret set NAME` (hidden prompt), `jade secret list` (names only), `jade secret rm NAME`.

## The wizard

`jade init` runs environment, targets, auth, models, permissions, smoke test, write. `--yes` takes defaults,
`--answers FILE` (JSON) or `--json` runs headless, `--skip-<step>` and `--only=<step>` select steps, `--restart`
forgets earlier answers (`~/.config/jade/init-state.json`). Permissions default to read-only and become approval
patterns. A failed smoke test leaves the previous file as it was.
