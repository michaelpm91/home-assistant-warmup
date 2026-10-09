"""Config flow for Warmup."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WarmupAuthError, WarmupClient, WarmupError
from .const import CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class WarmupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Warmup."""

    VERSION = 1

    async def _login(self, email: str, password: str) -> tuple[str | None, str | None]:
        """Return (token, error)."""
        client = WarmupClient(async_get_clientsession(self.hass))
        try:
            return await client.login(email, password), None
        except WarmupAuthError:
            return None, "invalid_auth"
        except WarmupError:
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error logging in to Warmup")
            return None, "unknown"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            token, error = await self._login(email, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()
                # The token does not expire, so the password is not kept.
                return self.async_create_entry(
                    title=email, data={CONF_EMAIL: email, CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token, error = await self._login(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WarmupOptionsFlow:
        return WarmupOptionsFlow()


class WarmupOptionsFlow(OptionsFlow):
    """Options for Warmup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OVERRIDE_MINUTES,
                    default=self.config_entry.options.get(
                        CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=1440)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
