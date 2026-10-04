"""Config flow: one-click bootstrap entry plus options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_DEFAULT_MODE,
    CONF_DEFAULT_SYSTEM_PROMPT,
    CONF_MAX_CONVERSATIONS,
    CONF_PER_USER_HISTORY,
    DEFAULT_MAX_CONVERSATIONS,
    DEFAULT_PER_USER_HISTORY,
    DOMAIN,
)

MODE_OPTIONS = [
    SelectOptionDict(value="chat", label="Chat (streaming)"),
    SelectOptionDict(value="assist", label="Assist (home control)"),
]

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEFAULT_MODE, default="chat"): SelectSelector(
            SelectSelectorConfig(options=MODE_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_PER_USER_HISTORY, default=DEFAULT_PER_USER_HISTORY): cv.boolean,
        vol.Required(
            CONF_MAX_CONVERSATIONS, default=DEFAULT_MAX_CONVERSATIONS
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional(CONF_DEFAULT_SYSTEM_PROMPT): TextSelector(
            TextSelectorConfig(multiline=True)
        ),
    }
)


class LiteLLMAssistConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the bootstrap config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LiteLLMAssistOptionsFlowHandler:
        """Return the options flow handler."""
        return LiteLLMAssistOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single entry; nothing to configure (uses litellm entry)."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="LiteLLM Assist", data={})
        return self.async_show_form(step_id="user")


class LiteLLMAssistOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
