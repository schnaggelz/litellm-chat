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


async def list_models(client: Any) -> list[str]:
    """Return sorted model ids offered by the proxy."""
    try:
        page = await client.models.list()
        models = {model.id async for model in page}
    except asyncio.CancelledError:
        raise
    except Exception as err:
        LOGGER.exception("Listing models failed")
        raise LiteLLMAPIError(f"Could not list models: {err}") from err
    return sorted(models)


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
