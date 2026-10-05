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
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import RuntimeData
from .api import LiteLLMAPIError, list_models, stream_chat
from .const import (
    LOGGER,
    MODE_ASSIST,
    SIGNAL_USAGE_UPDATED,
    WS_ASSIST_PROCESS,
    WS_CANCEL_STREAM,
    WS_CONVERSATIONS,
    WS_MODELS,
    WS_PREFS,
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
    websocket_api.async_register_command(hass, ws_prefs)


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
    meta = await runtime.storage.async_append_message(
        user_id,
        conv_id,
        {"role": "user", "content": msg["text"], "ts": now},
        title_if_new=msg["text"],
    )
    if meta is None:
        connection.send_error(
            msg["id"], "litellm_assist_not_found", f"conversation {conv_id} vanished"
        )
        return

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in conv["messages"]
        if m.get("role") in ("system", "user", "assistant")
    ]
    system_prompt = conv.get("system_prompt") or runtime.entry.options.get(
        "default_system_prompt"
    )
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    cancel = asyncio.Event()
    _cancel_registry[conv_id] = cancel
    usage_accum: dict[str, Any] | None = None
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
                elif event["type"] == "usage":
                    usage_accum = event
                connection.send_event(msg["id"], event)
        except LiteLLMAPIError as err:
            # Keep whatever the model produced before failing.
            if assistant_content:
                await runtime.storage.async_append_message(
                    user_id,
                    conv_id,
                    {
                        "role": "assistant",
                        "content": "".join(assistant_content),
                        "ts": _now(),
                        "model": msg["model"],
                        "error": True,
                    },
                )
            connection.send_error(msg["id"], "litellm_assist_error", str(err))
            return
        if cancel.is_set():
            connection.send_event(msg["id"], {"type": "cancelled"})
        if assistant_content:
            msg_record = {
                "role": "assistant",
                "content": "".join(assistant_content),
                "ts": _now(),
                "model": msg["model"],
            }
            if usage_accum is not None:
                msg_record["usage"] = {
                    k: usage_accum[k]
                    for k in ("prompt_tokens", "completion_tokens", "cost")
                    if k in usage_accum
                }
            await runtime.storage.async_append_message(user_id, conv_id, msg_record)
            if usage_accum is not None:
                await runtime.storage.async_add_usage(user_id, msg["model"], usage_accum)
                async_dispatcher_send(hass, SIGNAL_USAGE_UPDATED)
            await runtime.storage.async_set_prefs(user_id, {"model": msg["model"]})
        connection.send_result(
            msg["id"],
            {"cancelled": cancel.is_set(), "message_count": meta["message_count"]},
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
    meta = await runtime.storage.async_append_message(
        user_id,
        conv["id"],
        {"role": "user", "content": msg["text"], "ts": now},
        title_if_new=msg["text"],
    )
    if meta is None:
        connection.send_error(
            msg["id"], "litellm_assist_not_found", "conversation vanished"
        )
        return

    result = await async_converse(
        hass=hass,
        text=msg["text"],
        conversation_id=conv["id"],
        context=connection.context(msg),
        agent_id=msg["agent_id"],
    )
    payload = result.as_dict()
    meta = await runtime.storage.async_append_message(
        user_id,
        conv["id"],
        {
            "role": "assistant",
            "content": payload.get("speech", {}).get("plain", {}).get("speech", ""),
            "ts": _now(),
            "agent_id": msg["agent_id"],
        },
    )
    if meta is None:
        connection.send_error(msg["id"], "litellm_assist_not_found", "conversation vanished")
        return
    await runtime.storage.async_set_prefs(user_id, {"agent": msg["agent_id"]})
    connection.send_result(msg["id"], payload)


# -- prefs -------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_PREFS,
        vol.Required("action"): vol.In(["get", "set"]),
        vol.Optional("data"): dict,
    }
)
@websocket_api.async_response
async def ws_prefs(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Get or set per-user UI prefs (last model/agent)."""
    runtime = _get_runtime(hass)
    user_id = connection.user.id if connection.user else None
    if msg["action"] == "get":
        connection.send_result(msg["id"], await runtime.storage.async_get_prefs(user_id))
        return
    prefs = await runtime.storage.async_set_prefs(user_id, msg.get("data") or {})
    connection.send_result(msg["id"], prefs)


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
        if not data.get("system_prompt"):
            data["system_prompt"] = runtime.entry.options.get("default_system_prompt")
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
