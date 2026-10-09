"""Data update coordinator for Warmup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Room, WarmupAuthError, WarmupClient, WarmupError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type WarmupConfigEntry = ConfigEntry[WarmupCoordinator]


class WarmupCoordinator(DataUpdateCoordinator[dict[int, Room]]):
    """Polls every room on the account in one request."""

    config_entry: WarmupConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: WarmupConfigEntry, client: WarmupClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, Room]:
        try:
            return await self.client.get_rooms()
        except WarmupAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WarmupError as err:
            raise UpdateFailed(str(err)) from err
