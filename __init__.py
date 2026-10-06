"""LiteLLM Assist integration: chat frontend riding on the core litellm integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    CARD_RESOURCE_URL,
    LOGGER,
    PANEL_RESOURCE_URL,
    STATIC_PATH,
    STATIC_URL,
)
from .storage import ChatStorage


@dataclass(slots=True)
class RuntimeData:
    """Runtime data for the config entry."""

    entry: ConfigEntry | None = None
    client: object | None = None  # openai.AsyncOpenAI from litellm coordinator
    storage: ChatStorage | None = None


type LitellmAssistConfigEntry = ConfigEntry[RuntimeData]

ATTACH_RETRY_SECONDS = 30.0
ATTACH_MAX_RETRIES = 10


def _get_litellm_client(hass: HomeAssistant) -> object | None:
    """Return the AsyncOpenAI client owned by a loaded litellm entry, if any."""
    for entry in hass.config_entries.async_entries("litellm"):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if (runtime := entry.runtime_data) is not None:
            return runtime.client
    return None


async def _attach(hass: HomeAssistant, entry: LitellmAssistConfigEntry) -> bool:
    """Try to grab the litellm client; return True when attached."""
    if (client := _get_litellm_client(hass)) is not None:
        entry.runtime_data.client = client
        LOGGER.info("Attached to litellm proxy client")
        return True
    return False


async def _attach_retry(
    hass: HomeAssistant, entry: LitellmAssistConfigEntry
) -> None:
    """Retry attaching in the background until it works or we give up."""
    for attempt in range(1, ATTACH_MAX_RETRIES + 1):
        await asyncio.sleep(ATTACH_RETRY_SECONDS)
        if await _attach(hass, entry):
            return
    LOGGER.error(
        "Giving up attaching to litellm after %s attempts; "
        "chat streaming unavailable until reload",
        ATTACH_MAX_RETRIES,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: LitellmAssistConfigEntry
) -> bool:
    """Set up LiteLLM Assist from a config entry."""
    runtime = entry.runtime_data = RuntimeData(entry=entry)
    runtime.storage = ChatStorage(hass, entry)

    # Ensure the asset dir exists before HA checks it at registration time.
    (Path(__file__).parent / STATIC_PATH).mkdir(exist_ok=True)

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=STATIC_URL,
                path=str(Path(__file__).parent / STATIC_PATH),
                cache_headers=False,
            )
        ]
    )
    await _register_lovelace_resource(hass)
    await _register_sidebar_panel(hass)

    if not await _attach(hass, entry):
        LOGGER.warning(
            "No loaded litellm entry yet; retrying every %.0f s", ATTACH_RETRY_SECONDS
        )
        entry.async_create_background_task(
            hass, _attach_retry(hass, entry), "litellm_assist-attach"
        )

    # Importing the module registers the decorated handlers.
    from . import websocket_api  # noqa: F401

    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: LitellmAssistConfigEntry
) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if (runtime := entry.runtime_data) and runtime.storage:
        await runtime.storage.async_close()
    entry.runtime_data = None
    return True


async def _register_sidebar_panel(hass: HomeAssistant) -> None:
    """Register the fullscreen Chat panel in the sidebar."""
    from homeassistant.components import panel_custom

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="litellm-assist",
        webcomponent_name="litellm-assist-panel",
        sidebar_title="Chat",
        sidebar_icon="mdi:star-face",
        module_url=PANEL_RESOURCE_URL,
        require_admin=False,
    )
    LOGGER.info("Registered sidebar panel")


async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    """Inject the card as a Lovelace resource (storage mode only)."""
    lovelace_data = hass.data.get("lovelace")
    if lovelace_data is None:
        LOGGER.warning("Lovelace not available; add card resource manually")
        return
    if getattr(lovelace_data, "resource_mode", "storage") != "storage":
        LOGGER.warning(
            "Lovelace resources run in YAML mode; add to configuration.yaml: "
            "lovelace: resources: - url: %s type: module",
            CARD_RESOURCE_URL,
        )
        return

    collection = lovelace_data.resources
    await collection.async_get_info()  # forces load
    base = CARD_RESOURCE_URL.split("?")[0]
    for item in collection.async_items():
        if item.get("url", "").split("?")[0] == base:
            if item["url"] == CARD_RESOURCE_URL:
                return  # already current
            await collection.async_update_item(item["id"], {"url": CARD_RESOURCE_URL})
            LOGGER.info("Updated Lovelace resource to %s", CARD_RESOURCE_URL)
            return
    await collection.async_create_item({"res_type": "module", "url": CARD_RESOURCE_URL})
    LOGGER.info("Registered Lovelace resource %s", CARD_RESOURCE_URL)
