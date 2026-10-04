# LiteLLM Assist

Chat with all models of your [LiteLLM](https://docs.litellm.ai/) proxy — as a dashboard card, fullscreen panel view or sidebar entry in Home Assistant.

Rides on the **core `litellm` integration** (bundled with Home Assistant): no duplicate connection config, no extra pip dependencies. Two modes:

- 💬 **Chat** — direct streaming chat with any model from your proxy, with your own system prompt
- 🏠 **Assist** — route through your existing LiteLLM conversation agents with full home control (LLM tools), non-streaming

## Features

- Token-by-token streaming (SSE → WebSocket relay), Stop button
- Per-conversation history stored per HA user (`.storage`, private)
- History drawer: open / rename / delete conversations (wide: side panel, phone: overlay)
- Model picker for all proxy models, agent picker for Assist mode
- Remembers last model/agent per HA user
- Markdown-lite (bold, italic, inline code, code blocks) with copyable code
- German + English UI (follows HA language)
- Sidebar panel with `panel_custom` (hamburger + drawer support on narrow screens)
- Mobile polish: touch targets, iOS zoom guard, safe areas, auto-growing composer

## Requirements

- Home Assistant ≥ 2026.9
- Core **LiteLLM** integration configured (Settings → Devices → LiteLLM) — at least one conversation agent for Assist mode

## Installation

### HACS (custom repository)

1. HACS → ⋮ → *Custom repositories*
2. Add this repository URL, category **Integration**
3. Install *LiteLLM Assist*, restart Home Assistant
4. Settings → Devices & Services → **Add Integration** → *LiteLLM Assist* → Submit (one click, nothing to configure)

### Manual

Copy `custom_components/litellm_assist/` into your HA `config/custom_components/`, restart, add the integration as above.

## Usage

**Card** (any dashboard):

```yaml
type: custom:litellm-assist-chat
title: Chat
height: full        # number (px) or full
default_model: openrouter:some-model
welcome: Frag mich alles…
```

**Fullscreen dashboard view** ("big card"):

```yaml
views:
  - title: Chat
    type: panel
    cards:
      - type: custom:litellm-assist-chat
        title: Chat
        height: full
```

**Sidebar entry**: added automatically ("Chat", star-face icon) — works on desktop and in the companion app.

## Options (Configure dialog)

| option | description |
|---|---|
| Default mode | chat or assist for new conversations |
| Per-user history | keep history separate per HA user (default) or shared |
| Max conversations | per-user cap, oldest pruned |
| Default system prompt | persona for chat mode (assist mode uses each agent's own prompt) |

## Notes

- Chat mode does **not** expose HA tools — pure model chat. Use Assist mode for home control.
- Assist mode cannot be stopped mid-request (HA conversation API limitation).
- The Lovelace card resource is registered automatically (storage mode). YAML-mode dashboards: add `url: /litellm_assist/litellm-assist-chat.js`, `type: module` manually.
