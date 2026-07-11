"""Config flow for Duplicati Monitor."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.util import slugify

from .const import CONF_WEBHOOK_ID, DOMAIN

DEFAULT_NAME = "Duplicati Monitor"


def _unique_webhook_id(hass, suggested: str) -> str:
    """Return `suggested`, or `suggested-2`, `-3`, ... if already taken."""
    existing = {
        entry.data.get(CONF_WEBHOOK_ID)
        for entry in hass.config_entries.async_entries(DOMAIN)
    }
    candidate = suggested
    suffix = 2
    while candidate in existing:
        candidate = f"{suggested}-{suffix}"
        suffix += 1
    return candidate


class DuplicatiMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Duplicati Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        self._name: str | None = None
        self._webhook_id: str | None = None

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Step 1: name the collector and choose/confirm the webhook id."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input["name"].strip() or DEFAULT_NAME
            webhook_id = slugify(user_input["webhook_id"].strip())
            if not webhook_id:
                errors["webhook_id"] = "invalid_webhook_id"
            elif webhook_id in {
                e.data.get(CONF_WEBHOOK_ID)
                for e in self._async_current_entries()
            }:
                errors["webhook_id"] = "webhook_id_taken"
            else:
                self._name = name
                self._webhook_id = webhook_id
                return await self.async_step_confirm()

        suggested_name = (user_input or {}).get("name", DEFAULT_NAME)
        suggested_id = _unique_webhook_id(self.hass, slugify(suggested_name))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=suggested_name): str,
                    vol.Required("webhook_id", default=suggested_id): str,
                }
            ),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Step 2: show the exact webhook URL before creating the entry."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_WEBHOOK_ID: self._webhook_id},
            )

        url = webhook.async_generate_url(self.hass, self._webhook_id)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"webhook_url": url},
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Allow renaming the collector. The webhook id/URL never changes here."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry, title=user_input["name"], data=entry.data
            )
        url = webhook.async_generate_url(self.hass, entry.data[CONF_WEBHOOK_ID])
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required("name", default=entry.title): str}
            ),
            description_placeholders={"webhook_url": url},
        )
