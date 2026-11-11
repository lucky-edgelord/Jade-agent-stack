---
title: "Section reference"
summary: "Every page section and its parameters."
applies_to: "stack"
audience: "both"
since: "0.1.0"
version: 0.1.0
---
# Sections

The building blocks of a page. In a spec: `- hero` or `- {type: hero, title: …}`. Every section also takes `id` and `class`.

## nav

The top bar: the site's name, links to its pages, a theme switch and, with a backend, Sign in.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `brand` | string |  | name shown (default: the site name) |
| `links` | list |  | links [{"label", "href"}] (default: every page with nav = true) |
| `cta` | object |  | a button {"label", "href"} |
| `theme_toggle` | bool | `true` | show the light/dark switch |

## hero

The opening: a big title, a line under it, buttons and an optional image.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | headline (default: the site name) |
| `subtitle` | string |  | one or two sentences (default: the site tagline) |
| `eyebrow` | string |  | small text above the title |
| `buttons` | list |  | [{"label", "href"}] (first is primary) |
| `image` | string |  | an image URL or path |
| `align` | string | `"center"` | center \| left |

```yaml
- {"type": "hero", "title": "Embeddings for every app", "subtitle": "One API, fair prices.", "buttons": [{"label": "Start free", "href": "/account"}]}
```

## features

A grid of features: an icon (emoji or short text), a title and a sentence each.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | heading |
| `subtitle` | string |  | line under the heading |
| `items` required | list |  | [{"icon", "title", "text"}] |
| `columns` | int | `3` | columns on wide screens |

```yaml
- {"type": "features", "title": "Why us", "items": [{"icon": "\u26a1", "title": "Fast", "text": "Answers in milliseconds."}]}
```

## steps

Numbered steps (how it works).

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string | `"How it works"` | heading |
| `items` required | list |  | [{"title", "text"}] |

## stats

Big numbers with labels.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `items` required | list |  | [{"value", "label"}] |
| `title` | string |  | heading |

## pricing

Plans. With a backend: the live plans and Subscribe buttons (Stripe Checkout). Without: the plans you list.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string | `"Pricing"` | heading |
| `subtitle` | string |  | line under it |
| `currency` | string | `"USD"` | currency code |
| `plans` | list |  | for a static site: [{"name", "price", "features": [...], "button": {"label","href"}}] (default: backend.plans) |

Needs the backend modules: gateway.

```yaml
- {"type": "pricing", "title": "Pricing"}
```

## auth

Sign in, create an account, reset a password (needs a backend). After signing in, go to `next`.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | heading above it |
| `next` | string |  | where to go after signing in, e.g. /account |

## account

The signed-in user's plan, usage, billing and API keys; signed out, a sign-in form (needs a backend).

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string | `"Your account"` | heading |
| `currency` | string | `"USD"` | currency code |

Needs the backend modules: gateway.

## chat

An AI chat. mode gateway: the backend's models for signed-in users. mode ollama: the visitor pastes an Ollama Cloud key. mode demo: a scripted demo.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | heading |
| `mode` | string | `"gateway"` | gateway \| ollama \| demo |
| `model` | string |  | model name (gateway: one of backend.models) |
| `system` | string |  | system prompt |
| `greeting` | string | `"How can I help?"` | empty-state heading |
| `suggestions` | list |  | starter prompts |
| `height` | string | `"70vh"` | CSS height |
| `tools` | bool | `false` | give the model the kit's workspace tools (files, shell) |
| `replies` | object |  | demo mode: {"keyword": "reply"}; "*" for anything else |

Needs the backend modules: gateway.

```yaml
- {"type": "chat", "model": "house-chat", "suggestions": ["What can you do?"]}
```

## form

A form that saves to a backend collection (waitlists, contact forms, signups). The collection must let anyone create.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `collection` required | string |  | collection name |
| `title` | string |  | heading |
| `text` | string |  | a line under it |
| `fields` required | list |  | field specs "name:type!" (type: text, email, number, url, textarea, checkbox; ! = required) or {"name","label","type","required"} |
| `submit` | string | `"Send"` | button label |
| `success` | string | `"Thank you! We got it."` | shown after sending |

```yaml
- {"type": "form", "collection": "waitlist", "fields": ["email:email!", "company:text"], "submit": "Join the waitlist"}
```

## records

Cards listing records of a public backend collection (products, posts, team, …).

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `collection` required | string |  | collection name (its list rule must allow the visitor) |
| `title` | string |  | heading |
| `title_field` | string | `"title"` | field shown as the card title |
| `text_field` | string |  | field shown as text |
| `image_field` | string |  | file field shown as the image |
| `price_field` | string |  | field shown as a price |
| `filter` | string |  | PocketBase filter |
| `sort` | string |  | sort, e.g. title or -price (-created needs a created field) |
| `limit` | int | `12` | how many |
| `empty` | string | `"Nothing here yet."` | shown when there are none |

```yaml
- {"type": "records", "collection": "products", "title_field": "title", "text_field": "description", "price_field": "price"}
```

## faq

Questions and answers that open and close.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string | `"Questions"` | heading |
| `items` required | list |  | [{"q", "a"}] (answers may use markdown) |

## cta

A call to action: a heading, a line and a button, on a coloured band.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` required | string |  | heading |
| `text` | string |  | a line |
| `button` | object |  | {"label", "href"} |

## markdown

Text written in markdown (or a .md file next to jade.toml).

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `text` | string |  | markdown |
| `file` | string |  | a markdown file, relative to jade.toml |
| `narrow` | bool | `true` | a reading width |

## gallery

A grid of images with captions.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | heading |
| `images` required | list |  | [{"src", "alt", "caption"}] or URLs |
| `columns` | int | `3` | columns |

## code

A code block with copy and highlighting.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | heading |
| `lang` | string | `""` | language |
| `code` required | string | `""` | the code |

## surface

UI from a Jade surface spec (components, data, actions), e.g. a calculator, a dashboard or a quiz.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `title` | string |  | heading |
| `spec` | object |  | a surface spec: {root, components, data} (see the UI/UX catalog) |
| `file` | string |  | a saved surface spec (YAML or JSON), relative to jade.site.yaml: reuse a design instead of rebuilding it |
| `name` | string |  | surface name (for agents and actions) |

## html

Your own HTML, as it is (an escape hatch).

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `html` required | string | `""` | HTML |

## footer

The bottom of the page: a line of text and links.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `text` | string |  | text (default: © the site name) |
| `links` | list |  | [{"label", "href"}] |

<!-- generated by docs build; edit src/jade/docs/(generated from the code) not this file -->
