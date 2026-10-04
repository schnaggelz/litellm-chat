"""WebSocket API for LiteLLM Assist."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.conversation import async_converse
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from . import RuntimeData
from .api import LiteLLMAPIError, list_models, stream_chat
from .const import (
    LOGGER,
    MODE_ASSIST,
    WS_ASSIST_PROCESS,
    WS_CANCEL_STREAM,
    WS_CONVERSATIONS,
    WS_MODELS,
    WS_STREAM,
)

# conversation_id -> cancel event for in-flight streams
_cancel_registry: dict[str, asyncio.Event] = {}


def _get_runtime(hass: HomeAssistant) -> RuntimeData:
    """Return the runtime data of our loaded entry, or raise."""
    for entry in hass.config_entries.async_entries("litellm_assist"):
        if entry.state is ConfigEntryState.LOADED and isinstance(
            entry.runtime_data, RuntimeData
        ):
            return entry.runtime_data
    raise HomeAssistantError("litellm_assist is not loaded")


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    websocket_api.async_register_command(hass, ws_models)
    websocket_api.async_register_command(hass, ws_stream)
    websocket_api.async_register_command(hass, ws_cancel_stream)
    websocket_api.async_register_command(hass, ws_assist_process)
    websocket_api.async_register_command(hass, ws_conversations)


# -- models ------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_MODELS,
    }
)
@websocket_api.async_response
async def ws_models(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return agent entities and proxy models."""
    runtime = _get_runtime(hass)
    agents: list[dict[str, Any]] = []
    registry = er.async_get(hass)
    for reg_entry in registry.entities.values():
        if reg_entry.platform != "litellm" or reg_entry.domain != "conversation":
            continue
        if reg_entry.disabled_by is not None:
            continue
        state = hass.states.get(reg_entry.entity_id)
        agents.append(
            {
                "entity_id": reg_entry.entity_id,
                "name": state.name if state else reg_entry.entity_id,
            }
        )
    try:
        models = await list_models(runtime.client) if runtime.client else []
    except LiteLLMAPIError as err:
        connection.send_error(msg["id"], "litellm_assist_error", str(err))
        return
    connection.send_result(msg["id"], {"agents": agents, "models": models})


# -- stream ------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_STREAM,
        vol.Required("conversation_id"): str,
        vol.Required("text"): str,
        vol.Required("model"): str,
        vol.Optional("temperature"): float,
        vol.Optional("max_tokens"): int,
    }
)
@websocket_api.async_response
async def ws_stream(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream a chat answer and persist both messages."""
    runtime = _get_runtime(hass)
    if runtime.client is None:
        connection.send_error(
            msg["id"], "litellm_assist_not_attached", "litellm client not attached"
        )
        return
    if runtime.storage is None:  # pragma: no cover
        connection.send_error(msg["id"], "litellm_assist_error", "no storage")
        return

    conv_id: str = msg["conversation_id"]
    user_id = connection.user.id if connection.user else None

    conv = await runtime.storage.async_get(user_id, conv_id)
    if conv is None:
        connection.send_error(
            msg["id"], "litellm_assist_not_found", f"conversation {conv_id} not found"
        )
        return

    # Persist the user message first so history survives a failed request.
    now = _now()
    user_msg = {"role": "user", "content": msg["text"], "ts": now}
    conv["messages"].append(user_msg)
    if conv.get("title") in (None, "", "New chat"):
        conv["title"] = msg["text"][:40]
    conv["updated"] = now
    await runtime.storage.async_update(user_id, conv_id, conv)

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in conv["messages"]
        if m.get("role") in ("system", "user", "assistant")
    ]
    if conv.get("system_prompt"):
        messages.insert(0, {"role": "system", "content": conv["system_prompt"]})

    cancel = asyncio.Event()
    _cancel_registry[conv_id] = cancel
    try:
        assistant_content: list[str] = []
        try:
            async for event in stream_chat(
                runtime.client,
                model=msg["model"],
                messages=messages,
                temperature=msg.get("temperature"),
                max_tokens=msg.get("max_tokens"),
                cancel=cancel,
            ):
                if event["type"] == "delta":
                    assistant_content.append(event["content"])
                connection.send_event(msg["id"], event)
        except LiteLLMAPIError as err:
            # Keep whatever the model produced before failing.
            if assistant_content:
                conv["messages"].append(
                    {
                        "role": "assistant",
                        "content": "".join(assistant_content),
                        "ts": _now(),
                        "model": msg["model"],
                        "error": True,
                    }
                )
                await runtime.storage.async_update(user_id, conv_id, conv)
            connection.send_error(msg["id"], "litellm_assist_error", str(err))
            return
        if cancel.is_set():
            connection.send_event(msg["id"], {"type": "cancelled"})
        if assistant_content:
            conv["messages"].append(
                {
                    "role": "assistant",
                    "content": "".join(assistant_content),
                    "ts": _now(),
                    "model": msg["model"],
                }
            )
            await runtime.storage.async_update(user_id, conv_id, conv)
        connection.send_result(
            msg["id"], {"cancelled": cancel.is_set(), "message_count": len(conv["messages"])}
        )
    except LiteLLMAPIError as err:
        connection.send_error(msg["id"], "litellm_assist_error", str(err))
    finally:
        _cancel_registry.pop(conv_id, None)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CANCEL_STREAM,
        vol.Required("conversation_id"): str,
    }
)
@callback
def ws_cancel_stream(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Cancel an in-flight stream."""
    event = _cancel_registry.get(msg["conversation_id"])
    if event is not None:
        event.set()
    connection.send_result(msg["id"], {"cancelled": event is not None})


# -- assist ------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_ASSIST_PROCESS,
        vol.Required("conversation_id"): str,
        vol.Required("agent_id"): str,
        vol.Required("text"): str,
    }
)
@websocket_api.async_response
async def ws_assist_process(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Run text through a conversation agent (assist mode) and store the exchange."""
    runtime = _get_runtime(hass)
    user_id = connection.user.id if connection.user else None
    conv = await runtime.storage.async_get(user_id, msg["conversation_id"])
    if conv is None:
        connection.send_error(
            msg["id"],
            "litellm_assist_not_found",
            f"conversation {msg['conversation_id']} not found",
        )
        return

    now = _now()
    conv["messages"].append({"role": "user", "content": msg["text"], "ts": now})
    conv["updated"] = now
    await runtime.storage.async_update(user_id, conv["id"], conv)

    result = await async_converse(
        hass=hass,
        text=msg["text"],
        conversation_id=conv["id"],
        context=connection.context(msg),
        agent_id=msg["agent_id"],
    )
    payload = result.as_dict()
    conv["messages"].append(
        {
            "role": "assistant",
            "content": payload.get("speech", {}).get("plain", {}).get("speech", ""),
            "ts": _now(),
            "agent_id": msg["agent_id"],
        }
    )
    await runtime.storage.async_update(user_id, conv["id"], conv)
    connection.send_result(msg["id"], payload)


# -- conversations CRUD ------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CONVERSATIONS,
        vol.Required("action"): vol.In(["list", "get", "create", "update", "delete"]),
        vol.Optional("conversation_id"): str,
        vol.Optional("data"): dict,
    }
)
@websocket_api.async_response
async def ws_conversations(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """CRUD conversations for the connected user."""
    runtime = _get_runtime(hass)
    user_id = connection.user.id if connection.user else None
    action: str = msg["action"]
    conv_id = msg.get("conversation_id")
    data: dict[str, Any] = msg.get("data") or {}
    storage = runtime.storage

    if action == "list":
        connection.send_result(msg["id"], {"conversations": await storage.async_list(user_id)})
        return
    if action == "get":
        conv = await storage.async_get(user_id, conv_id)
        connection.send_result(msg["id"], {"conversation": conv})
        return
    if action == "create":
        conv = await storage.async_create(user_id, data)
        connection.send_result(msg["id"], {"conversation": conv})
        return
    if action == "update":
        conv = await storage.async_update(user_id, conv_id, data)
        connection.send_result(msg["id"], {"conversation": conv})
        return
    # delete
    deleted = await storage.async_delete(user_id, conv_id)
    connection.send_result(msg["id"], {"deleted": deleted})


def _now() -> str:
    """ISO timestamp helper."""
    from homeassistant.util import dt as dt_util

    return dt_util.utcnow().isoformat()
