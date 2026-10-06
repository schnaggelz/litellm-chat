"""Thin wrapper around the AsyncOpenAI client owned by the core litellm integration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .const import LOGGER

STREAM_TIMEOUT_SECONDS = 300.0


class LiteLLMAPIError(HomeAssistantError):
    """Error talking to the LiteLLM proxy."""


async def list_models(client: Any) -> list[dict[str, Any]]:
    """Return model ids enriched with local/ctx info from /model/info."""
    try:
        raw = {m.id async for m in await client.models.list()}
    except asyncio.CancelledError:
        raise
    except Exception as err:
        LOGGER.exception("Listing models failed")
        raise LiteLLMAPIError(f"Could not list models: {err}") from err

    info_map: dict[str, dict[str, Any]] = {}
    try:
        info = await client.get("/model/info")
        for m in info.get("data") or []:
            lp = m.get("litellm_params") or {}
            api_base = str(lp.get("api_base") or "")
            provider = str((m.get("model_info") or {}).get("provider") or "")
            info_map[m.get("model_name")] = {
                "local": "11434" in api_base or "ollama" in provider.lower(),
                "ctx": (m.get("model_info") or {}).get("max_input_tokens"),
            }
    except asyncio.CancelledError:
        raise
    except Exception as err:  # info is optional; ids without info stay plain
        LOGGER.debug("/model/info unavailable: %s", err)

    def _entry(mid: str) -> dict[str, Any]:
        base = {"id": mid, "local": False, "ctx": None}
        base.update(info_map.get(mid, {}))
        return base

    entries = [_entry(mid) for mid in sorted(raw)]
    # Remote models first: local ones hog the shared GPU host.
    entries.sort(key=lambda e: e["local"])
    return entries


async def stream_chat(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    cancel: asyncio.Event | None = None,
) -> AsyncGenerator[dict[str, Any]]:
    """Stream a chat completion, yielding delta/done events.

    Events:
      {"type": "delta", "content": str}
      {"type": "usage", "prompt_tokens": int, "completion_tokens": int}
      {"type": "done"}
    Raises LiteLLMAPIError on failure. Honors cancel event between chunks.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        stream = await _create_stream(client, kwargs)
    except Exception as err:
        LOGGER.exception("Chat request failed")
        raise LiteLLMAPIError(f"Chat request failed: {err}") from err

    try:
        async for chunk in stream:
            if cancel is not None and cancel.is_set():
                return
            for choice in chunk.choices or ():
                delta = choice.delta
                if delta is not None and delta.content:
                    yield {"type": "delta", "content": delta.content}
            usage = getattr(chunk, "usage", None)
            if usage is not None and getattr(usage, "total_tokens", 0):
                yield {
                    "type": "usage",
                    "prompt_tokens": usage.prompt_tokens or 0,
                    "completion_tokens": usage.completion_tokens or 0,
                    # LiteLLM proxy reports cost when it knows model pricing.
                    "cost": getattr(usage, "cost", None),
                }
        yield {"type": "done"}
    except asyncio.CancelledError:
        raise
    except Exception as err:
        LOGGER.exception("Streaming failed")
        raise LiteLLMAPIError(f"Streaming failed: {err}") from err
    finally:
        await stream.close()


async def _create_stream(client: Any, kwargs: dict[str, Any]) -> Any:
    """Create a streaming completion, falling back when stream_options is rejected."""
    try:
        return await client.with_options(timeout=STREAM_TIMEOUT_SECONDS) \
            .chat.completions.create(**kwargs)
    except Exception as err:
        if "stream_options" not in str(err).lower():
            raise
        LOGGER.debug("stream_options rejected, retrying without it: %s", err)
        kwargs = {k: v for k, v in kwargs.items() if k != "stream_options"}
        return await client.with_options(timeout=STREAM_TIMEOUT_SECONDS) \
            .chat.completions.create(**kwargs)


async def complete_chat(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Non-streaming completion (fallback for reconnects)."""
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    try:
        result = await client.with_options(timeout=STREAM_TIMEOUT_SECONDS) \
            .chat.completions.create(**kwargs)
        return result.choices[0].message.content or ""
    except Exception as err:
        LOGGER.exception("Chat request failed")
        raise LiteLLMAPIError(f"Chat request failed: {err}") from err
