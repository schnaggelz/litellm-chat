"""Conversation storage for LiteLLM Assist, bucketed per HA user."""

from __future__ import annotations

import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MAX_CONVERSATIONS,
    CONF_PER_USER_HISTORY,
    DEFAULT_MAX_CONVERSATIONS,
    DEFAULT_PER_USER_HISTORY,
    LOGGER,
    STORAGE_KEY,
    STORAGE_VERSION,
)

SHARED_BUCKET = "shared"


class ChatStorage:
    """CRUD for chat conversations, persisted as one JSON file.

    Shape:
      {"users": {bucket: {conv_id: conv}}}
    bucket = HA user_id (per-user history) or "shared" (history for everyone).
    """

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        """Initialize the store."""
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY, private=True
        )
        self._entry = entry
        self._data: dict[str, Any] | None = None

    async def async_close(self) -> None:
        """Nothing buffered; every mutation saves immediately."""
        return

    def _max_conversations(self) -> int:
        """Return the configured per-user conversation cap."""
        try:
            return int(
                self._entry.options.get(
                    CONF_MAX_CONVERSATIONS, DEFAULT_MAX_CONVERSATIONS
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_MAX_CONVERSATIONS

    def _per_user(self) -> bool:
        """Return whether history is isolated per HA user."""
        return bool(
            self._entry.options.get(CONF_PER_USER_HISTORY, DEFAULT_PER_USER_HISTORY)
        )

    def _bucket(self, user_id: str | None) -> str:
        """Return the storage bucket for this user."""
        if not self._per_user() or not user_id:
            return SHARED_BUCKET
        return user_id

    async def _ensure_loaded(self) -> dict[str, Any]:
        """Load data once; mutate via helpers that re-save."""
        if self._data is None:
            self._data = await self._store.async_load() or {"users": {}}
            self._data.setdefault("users", {})
            self._data.setdefault("prefs", {})
        return self._data

    async def _save(self) -> None:
        """Persist current data."""
        await self._store.async_save(self._data)

    def _conv_meta(self, conv: dict[str, Any]) -> dict[str, Any]:
        """Return a conversation without its messages (for listings)."""
        return {k: v for k, v in conv.items() if k != "messages"}

    # -- CRUD ----------------------------------------------------------------

    async def async_list(self, user_id: str | None) -> list[dict[str, Any]]:
        """List conversations for a user, newest first, without messages."""
        data = await self._ensure_loaded()
        bucket = data["users"].get(self._bucket(user_id), {})
        metas = [self._conv_meta(conv) for conv in bucket.values()]
        metas.sort(key=lambda c: c.get("updated", ""), reverse=True)
        return metas

    async def async_get(self, user_id: str | None, conv_id: str) -> dict | None:
        """Return one conversation with messages, or None."""
        data = await self._ensure_loaded()
        return data["users"].get(self._bucket(user_id), {}).get(conv_id)

    async def async_create(
        self, user_id: str | None, defaults: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a conversation and return it."""
        data = await self._ensure_loaded()
        bucket = data["users"].setdefault(self._bucket(user_id), {})
        conv_id = uuid.uuid4().hex[:12]
        while conv_id in bucket:  # paranoia; space is huge
            conv_id = uuid.uuid4().hex[:12]
        conv: dict[str, Any] = {
            "id": conv_id,
            "title": defaults.get("title") or "New chat",
            "mode": defaults.get("mode", "chat"),
            "model": defaults.get("model"),
            "agent_id": defaults.get("agent_id"),
            "system_prompt": defaults.get("system_prompt"),
            "messages": [],
            "created": defaults.get("created"),
            "updated": defaults.get("updated"),
        }
        bucket[conv_id] = conv
        self._prune(bucket)
        await self._save()
        return conv

    async def async_update(
        self, user_id: str | None, conv_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Patch a conversation (title/model/mode/system_prompt/messages)."""
        data = await self._ensure_loaded()
        conv = data["users"].get(self._bucket(user_id), {}).get(conv_id)
        if conv is None:
            return None
        for key in ("title", "mode", "model", "agent_id", "system_prompt", "updated"):
            if key in updates:
                conv[key] = updates[key]
        if "messages" in updates:
            conv["messages"] = updates["messages"]
        await self._save()
        return conv

    async def async_delete(self, user_id: str | None, conv_id: str) -> bool:
        """Delete a conversation; return True if it existed."""
        data = await self._ensure_loaded()
        bucket = data["users"].get(self._bucket(user_id), {})
        if conv_id not in bucket:
            return False
        del bucket[conv_id]
        await self._save()
        return True

    def _prune(self, bucket: dict[str, Any]) -> None:
        """Drop oldest conversations beyond the cap."""
        max_convs = self._max_conversations()
        if len(bucket) <= max_convs:
            return
        by_age = sorted(bucket.items(), key=lambda kv: kv[1].get("updated", ""))
        for conv_id, _ in by_age[: len(bucket) - max_convs]:
            LOGGER.debug("Pruning conversation %s", conv_id)
            del bucket[conv_id]

    # -- prefs ---------------------------------------------------------------

    async def async_get_prefs(self, user_id: str | None) -> dict[str, Any]:
        """Return stored UI prefs for a user (model, agent, ...)."""
        data = await self._ensure_loaded()
        return dict(data["prefs"].get(user_id or SHARED_BUCKET, {}))

    async def async_set_prefs(self, user_id: str | None, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge UI prefs for a user and persist."""
        data = await self._ensure_loaded()
        key = user_id or SHARED_BUCKET
        prefs = data["prefs"].setdefault(key, {})
        prefs.update(updates)
        await self._save()
        return dict(prefs)

    # -- usage (proxy-reported cost only) -------------------------------------

    async def async_add_usage(
        self, user_id: str | None, model: str, usage: dict[str, Any]
    ) -> None:
        """Accumulate one exchange into the user's daily usage bucket."""
        data = await self._ensure_loaded()
        usage_root = data.setdefault("usage", {})
        user_usage = usage_root.setdefault(user_id or SHARED_BUCKET, {})
        day = dt_util.now().date().isoformat()
        bucket = user_usage.setdefault(
            day, {"in": 0, "out": 0, "cost": 0.0, "by_model": {}}
        )
        bucket["in"] += usage.get("prompt_tokens", 0)
        bucket["out"] += usage.get("completion_tokens", 0)
        cost = usage.get("cost")
        if isinstance(cost, (int, float)):
            bucket["cost"] = round(bucket["cost"] + cost, 6)
        model_bucket = bucket["by_model"].setdefault(
            model, {"in": 0, "out": 0, "cost": 0.0}
        )
        model_bucket["in"] += usage.get("prompt_tokens", 0)
        model_bucket["out"] += usage.get("completion_tokens", 0)
        if isinstance(cost, (int, float)):
            model_bucket["cost"] = round(model_bucket["cost"] + cost, 6)
        await self._save()

    async def async_get_usage(self) -> dict[str, Any]:
        """Return the whole usage tree (all users, all days)."""
        data = await self._ensure_loaded()
        return data.get("usage", {})