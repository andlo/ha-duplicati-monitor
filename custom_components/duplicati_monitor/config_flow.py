"""Config flow for Duplicati Monitor."""
from __future__ import annotations

import secrets

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_WEBHOOK_ID, DOMAIN

DEFAULT_NAME = "Duplicati Monitor"


class DuplicatiMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Duplicati Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """First (and only) step: name the collector, auto-generate a webhook id."""
        if user_input is not None:
            webhook_id = secrets.token_hex(16)
            return self.async_create_entry(
                title=user_input["name"],
                data={CONF_WEBHOOK_ID: webhook_id},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("name", default=DEFAULT_NAME): str}),
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Allow renaming the collector without changing the webhook id."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry, title=user_input["name"], data=entry.data
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required("name", default=entry.title): str}
            ),
        )
