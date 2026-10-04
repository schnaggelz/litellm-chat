# PLAN.md — litellm_assist

Home Assistant custom integration + Lovelace card for chatting with a LiteLLM proxy.
Rides on the **core `litellm` integration** (present since HA 2026.x) instead of duplicating its backend.

- Target instance: HA 2026.9.1 (docker), config at `/opt/homeassistant/data` (this repo).
- Existing core `litellm` entry: `http://192.168.242.21:4000/v1`, 2 conversation agent subentries
  (`openrouter:ling-3.0-flash`, `agx:gemma4:e2b`), both with `llm_hass_api: [assist]`.
- Later: HACS installable, single repo.

## 1. Architecture

```
┌───────────────────────────── HA frontend ─────────────────────────────┐
│  litellm-assist-chat card (Lit, single file, no build step)           │
│  - chat mode + assist mode, model/agent picker, history drawer        │
└───────────────┬───────────────────────────────────────────────────────┘
                │ WebSocket only (no API key in frontend)
┌───────────────▼───────── litellm_assist custom integration ───────────┐
│  websocket_api.py                                                     │
│   ├─ stream          : direct SSE  → token-by-token, any model        │
│   ├─ assist_process  : conversation/process(agent_id) → tools         │
│   ├─ models          : subentry agents + /v1/models                   │
│   └─ history CRUD                                                     │
│  storage.py  : conversations in HA Store, per HA user_id              │
└───────────────┬───────────────────────────────────────────────────────┘
                │ reuses
┌───────────────▼─── core litellm integration ──────────────────────────┐
│  coordinator.client (AsyncOpenAI, holds URL + API key)                │
│  conversation agent entities (subentries, model + prompt + tools)     │
└───────────────────────────────────────────────────────────────────────┘
```

**Key decisions**

- **No own connection config.** Auto-attach to existing `litellm` config entry at setup.
  Options flow only for card defaults (per-user history, max conversations).
- **Two chat paths:**
  - **Chat mode** (default): direct SSE via reused `AsyncOpenAI` client → streaming,
    any model from `/v1/models`, own system prompt, temperature. No HA tools.
  - **Assist mode**: routes through `conversation/process` with an agent entity →
    LLM API tools (home control), agent's own persona prompt. No streaming (spinner + burst).
- **Key stays in backend.** Frontend only speaks HA WS.
- Card ships as `www/litellm-assist-chat.js` inside the integration; integration registers
  static path + injects Lovelace resource (storage mode; YAML instructions in README).
- Panel mode: `panel_custom` → same card fullscreen = "complete dashboard entry".

## 2. Repo layout

```
custom_components/litellm_assist/
├── manifest.json           # domain litellm_assist, no deps, after_dependencies: [litellm, conversation, frontend]
├── const.py
├── __init__.py             # attach to litellm entry, static path, lovelace resource, panel
├── options_flow.py         # defaults (max conversations, per-user history)
├── api.py                  # thin wrapper: list_models, chat_completions stream over coordinator.client
├── storage.py              # conversation Store
├── websocket_api.py        # stream / assist_process / models / history
├── services.yaml + services.py   # litellm_assist.chat, litellm_assist.clear_history
├── translations/en.json
└── www/litellm-assist-chat.js
```

Plus repo root (this repo is HA config, not repo-root-shaped for HACS — for HACS later,
carve out a dedicated repo or publish subtree with `custom_components/litellm_assist` at top):
`hacs.json`, `README.md`.

## 3. WebSocket API (draft)

| command | request | response / stream |
|---|---|---|
| `litellm_assist/models` | – | `{agents: [{entity_id, model, name}], models: [str]}` |
| `litellm_assist/stream` | `{conversation_id, model, messages/history_ref, system_prompt?, temperature?, max_tokens?}` | streamed events: `{type: delta, content}`, `{type: done, usage, message_id}`, `{type: error}`; `cancel` supported |
| `litellm_assist/assist_process` | `{conversation_id, agent_id, text}` | full result (`conversation/process` payload) |
| `litellm_assist/conversations` | `{action: list/get/create/rename/delete, ...}` | history data |
| `litellm_assist/cancel_stream` | `{conversation_id}` | ack |

SSE → WS relay line-by-line; heartbeat deltas to survive proxies; mid-stream reconnect = degrade to non-stream.

## 4. Card UX

- Single Lit element `litellm-assist-chat`. Config: `title`, `default_model`,
  `welcome`, `show_history`, `height: full|fixed`, `default_mode`.
- Streaming text with live cursor, Stop button, markdown + code blocks + copy.
- Message actions: edit, regenerate, delete. Error bubble with retry.
- Model dropdown (all models), agent dropdown (agent entities) or per-conversation mode badge 💬/🏠.
- History: side drawer ≥768px, overlay drawer on phone (dvh-aware, keyboard safe).
- Big card on tablet dashboard fills parent height; phone = compact chat; panel mode = fullscreen app feel.

## 5. Milestones

- **M1 backend** — ✅ DONE 2026-10-04: attach, WS stream + models + history CRUD, storage, options flow. Full WS test pass (dev/ws_test.py). Note: agx:gemma4:26b cold-loads >60 s — slow for tests, fine for use.
- **M2 card MVP** — ✅ DONE 2026-10-04: `www/litellm-assist-chat.js` (vendored lit 3.3.2 ESM in `www/lit.js`; no bare `lit` importmap in HA). Streaming, model picker, stop, markdown-lite, persistence, dark-theme fixes. Verified: fullscreen panel view on dashboard. Gaps → M3.
- **M3 polish** — assist mode, panel mode, mobile ergonomics, edit/regenerate.
- **M4 HACS** — hacs.json, README, tag release.
- **M5 later** — tool-bridge (llm API tools on direct chat mode), cost/usage sensor, multimodal input, per-conversation params UI.

## 6. Risks

- Frontend API churn → pin `homeassistant` min version in hacs.json; test on 2026.9.1.
- Long SSE connections → HA WS timeouts; heartbeat + reconnect handling.
- Lovelace YAML mode can't auto-inject resource → README fallback.
- This repo = full HA config, not HACS-shaped → subtree export for release.

## 7. Decisions

1. Default mode for new conversations: **chat** (assist per conversation toggle).
2. History: **per HA user**, single Store file keyed by user_id (small code).
3. Multimodal: **later** (M5+).

## 8. Open questions

- none
