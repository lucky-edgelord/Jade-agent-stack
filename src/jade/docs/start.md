---
title: "Quick start"
summary: "Install, connect, check, then build a site or run a playbook."
tags: [install, init, doctor]
applies_to: stack
audience: both
since: 0.1.0
order: 1
---
# Quick start

Jade Agent Stack is one Python package, `jade-agent-stack`, that drives the four Jade repositories through their
documented interfaces. It is a client and needs the network to reach them.

| Repository | Role | The toolkit uses |
| --- | --- | --- |
| Jade Vault | control plane: agent loop, schedules, approvals, the person | HTTP API `/v1` (header auth) |
| Jade Agent Base | resource plane: identity, database, model gateway, billing, audit log | REST `/api/agent/tools`, MCP `/api/agent/mcp` |
| Jade Agent Kit | the embeddable subset of Vault (an agent in any web page) | a generated page that loads it |
| Jade Agent UI/UX | presentation: web components | generated HTML that loads them |

## Install

```sh
pip install jade-agent-stack          # Python 3.11+; needs only PyYAML
pip install "jade-agent-stack[keyring]"   # store tokens in the OS keyring
```

## Connect

```sh
jade init                 # seven steps; resumable; --yes for defaults, --answers FILE for headless
jade doctor               # reachable, authenticated, compatible, no tokens in URLs
```

`jade init` writes `jade.config.yaml` (found later by walking up from the working directory, or `$JADE_CONFIG`).
Tokens go to the OS keyring under `jade.<host>`, never into the file.

## Build a site

```sh
jade site new "Acme AI" --template saas --tagline "Embeddings for every app."
jade site build           # → dist/ (static files)
jade site preview         # http://127.0.0.1:8080
jade site plan            # every Base call a deploy makes; makes none
jade site deploy          # collections, modules, models, plans, billing, then the files
```

## Run a playbook

```sh
jade playbook check examples/base-products.playbook.yaml
jade playbook plan examples/base-products.playbook.yaml
jade playbook approve base-products
jade playbook run base-products --var collection=products
```

## Find help

```sh
jade docs topics
jade docs search "idempotency key"
jade docs show playbooks#failure-modes
jade commands               # every command with its parameters, as data
```
