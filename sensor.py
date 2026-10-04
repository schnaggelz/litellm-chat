"""Usage/cost sensor fed by proxy-reported costs (chat mode)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from . import LitellmAssistConfigEntry
from .const import SIGNAL_USAGE_UPDATED


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LitellmAssistConfigEntry,
    async_add_entities,
) -> None:
    """Add the usage sensor."""
    async_add_entities([LiteLLMAssistUsageSensor(entry)])


class LiteLLMAssistUsageSensor(SensorEntity):
    """Reports accumulated chat cost from proxy-reported usage."""

    _attr_name = "LiteLLM Assist usage"
    _attr_unique_id = "litellm_assist_usage"
    _attr_icon = "mdi:cash-multiple"
    _attr_state_class = "total"

    def __init__(self, entry: LitellmAssistConfigEntry) -> None:
        """Initialize the sensor."""
        self._entry = entry
        self._usage: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Refresh on startup and on every recorded exchange."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_USAGE_UPDATED, self._async_refresh
            )
        )
        await self._async_refresh()

    async def _async_refresh(self) -> None:
        """Reload usage from storage and update state."""
        runtime = self._entry.runtime_data
        if runtime and runtime.storage:
            self._usage = await runtime.storage.async_get_usage()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Today's cost (sum over users), proxy-reported only."""
        today = dt_util.now().date().isoformat()
        return round(self._bucket_cost(today), 4)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Follow the instance currency."""
        return self.hass.config.currency or None

    @staticmethod
    def _bucket_cost(day_bucket: dict[str, Any]) -> float:
        """Cost of one day bucket across users."""
        if not isinstance(day_bucket, dict):
            return 0.0
        return float(day_bucket.get("cost", 0.0) or 0.0)

    def _buckets(self) -> dict[str, dict[str, Any]]:
        """Flatten usage: {user: {day: bucket}} → merged {day: bucket}."""
        merged: dict[str, dict[str, Any]] = {}
        for user_days in self._usage.values():
            if not isinstance(user_days, dict):
                continue
            for day, bucket in user_days.items():
                if not isinstance(bucket, dict):
                    continue
                target = merged.setdefault(
                    day, {"in": 0, "out": 0, "cost": 0.0, "by_model": {}}
                )
                target["in"] += bucket.get("in", 0)
                target["out"] += bucket.get("out", 0)
                target["cost"] = round(target["cost"] + bucket.get("cost", 0.0), 6)
                for model, mb in bucket.get("by_model", {}).items():
                    model_target = target["by_model"].setdefault(
                        model, {"in": 0, "out": 0, "cost": 0.0}
                    )
                    model_target["in"] += mb.get("in", 0)
                    model_target["out"] += mb.get("out", 0)
                    model_target["cost"] = round(
                        model_target["cost"] + mb.get("cost", 0.0), 6
                    )
        return merged

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Today/month/all-time breakdown."""
        buckets = self._buckets()
        today = dt_util.now().date().isoformat()
        month_prefix = today[:7]
        today_b = buckets.get(today, {})
        month_cost = round(
            sum(b.get("cost", 0.0) for d, b in buckets.items() if d.startswith(month_prefix)),
            4,
        )
        total_cost = round(sum(b.get("cost", 0.0) for b in buckets.values()), 4)
        return {
            "today_tokens_in": today_b.get("in", 0),
            "today_tokens_out": today_b.get("out", 0),
            "today_by_model": today_b.get("by_model", {}),
            "this_month_cost": month_cost,
            "total_cost": total_cost,
            "source": "proxy-reported (chat mode only)",
        }
