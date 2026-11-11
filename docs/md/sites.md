---
title: "Sites"
summary: "The site spec, templates, themes, building, previewing and deploying to Jade Agent Base."
tags: ["site", "spec", "templates", "themes", "deploy"]
applies_to: "stack"
audience: "both"
since: "0.1.0"
version: 0.1.0
---
# Sites

A site is one file, `jade.site.yaml`, compiled to static HTML that loads Jade Agent UI/UX from its CDN. With a
backend, the same spec also sets up Jade Agent Base: collections, modules, sign-in providers, models, plans and billing.

## Spec

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | required | the site name (brand, titles) |
| `tagline` | string | `""` | one line under the name (hero default) |
| `description` | string | tagline | meta description |
| `template` | string | none | `saas`, `chatbot`, `landing`, `waitlist`, `docs`, `portfolio`, `shop`, `dashboard` |
| `theme` | string or mapping | `jade` | a theme name, or `{name, mode: auto/light/dark, accent: "#hex", …}` |
| `url` | URL | none | public address: canonical links, sitemap, Base `appURL` |
| `lang` | string | `en` | page language |
| `logo`, `favicon` | URL | none | images |
| `cdn` | mapping | pinned | `{ui: URL, kit: URL}` to override the pinned module URLs |
| `static` | folder | `static` | files copied as they are (images, robots) |
| `head` | HTML | none | added to every `<head>` |
| `pages` | list | template's | `{path, title, description, nav, nav_label, sections}` |
| `backend` | mapping | none | see below |

## Templates

A template supplies pages and backend defaults. Pages in the spec replace the template's page at the same path; backend
lists (collections, providers, models, plans) merge by `name`. `jade site templates` lists them.

## Reusing a design

A settled design does not need rebuilding. Save it once and start new sites from it:

```sh
jade site template save house --about "Our look: ocean theme, pricing, account"   # → ~/.config/jade/templates/house.yaml
jade site template save house --project                                           # → ./templates/house.yaml (commit it)
```

```yaml
name: Second product
tagline: Same look, new idea.
template: house          # or a path: template: ../brand/site.yaml
```

Templates are looked up in `./templates`, then your own, then the built-in ones; a template may itself name a
`template` to build on. Saved UI (a dashboard, a calculator) can live in a file and be reused by a surface section:
`{type: surface, file: dashboards/sales.yaml}`.

## Themes

`jade site themes` lists them: jade, midnight, paper, contrast, sunset, ocean, forest, rose, mono, neon, slate, terminal.
Each has a light and a dark palette, a font and a radius. Visitors switch with the theme toggle in the nav.

## Backend

| Key | Shape | Becomes (Base tool) |
| --- | --- | --- |
| `url` | URL | `<meta name="jade-base">` in every page |
| `modules` | `[gateway, billing]` | `module_enable` |
| `rate_limits` | `true` or `{rules: [...]}` | `rate_limits` |
| `auth.password` | bool | password sign-in on or off |
| `auth.providers` | `[{name: google, client_id_env, client_secret_env}]` | `auth_provider_set` (OAuth2) |
| `collections` | `[{name, fields: "email:email!, note:text", list, view, create, update, delete}]` | `collection_get`, then `collection_create` or `collection_update` |
| `providers` | `[{name, type, base_url, api_key_env}]` | `provider_set` |
| `models` | `[{name, provider, upstream, kind, price_in, price_out}]` | `model_set` |
| `plans` | `[{name, price_month, monthly_tokens, rpm, default, description}]` | `plan_set` |
| `billing` | `{secret_key_env, webhook_secret_env, currency, publish: [pro]}` | `billing_setup`, `plan_publish` |

Field shorthand: `name:type!` (`!` = required). Types: text, email, url, number, bool, date, json, editor, select,
file, relation, textarea, checkbox. Rule shorthands: `anyone`, `users` (signed in), `owner` (adds a `user` relation),
`admin` (no rule: superusers only), or a PocketBase rule.

## Build, preview, deploy

| Command | Does |
| --- | --- |
| `jade site check` | validates and compiles in memory; lists warnings |
| `jade site build [--out dist]` | writes `index.html` per page (`/pricing` → `pricing/index.html`), `404.html`, `sitemap.xml`, `robots.txt` |
| `jade site preview [--port 8080]` | builds and serves on localhost |
| `jade site plan` | the deploy as a list of Base calls; secrets as placeholders; makes none |
| `jade site deploy [--yes]` | runs the deploy as a playbook through the harness |

A deploy is a generated playbook: approvals apply, every mutation has a content-hash idempotency key (deploying the same
thing twice changes nothing), the run uses a short-lived task credential with only the scopes it needs, and an
interrupted deploy resumes where it stopped. Secrets come from the environment variables the spec names.

## From Python

```python
import jade
site = jade.Site("Acme AI", tagline="Embeddings for every app.", template="saas")
site.page("/", "Home").add("nav").add("hero").add("pricing").add("footer")
site.collection("waitlist", "email:email!", create="anyone", list="admin")
site.build("dist")
```

<!-- generated by docs build; edit src/jade/docs/sites.md not this file -->
