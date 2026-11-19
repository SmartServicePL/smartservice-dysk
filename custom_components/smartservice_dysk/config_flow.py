# © Smart Service Tczew. Wszelkie prawa zastrzeżone.
"""The one entry: made and renewed by Smart Service HA with the panel's Dysk key (no screens for the owner)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_KEY, DOMAIN

SCHEMA = vol.Schema({vol.Required(CONF_KEY): vol.All(str, vol.Length(min=20, max=200))})


class SmartServiceDyskFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=SCHEMA)
        return self.async_create_entry(title="Smart Service — Dysk Google", data={CONF_KEY: user_input[CONF_KEY]})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A new key from the panel (the old one was not known any more)."""

        if user_input is None:
            return self.async_show_form(step_id="reconfigure", data_schema=SCHEMA)
        return self.async_update_reload_and_abort(
            self._get_reconfigure_entry(), data={CONF_KEY: user_input[CONF_KEY]}
        )
