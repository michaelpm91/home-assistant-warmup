"""Diagnostics for Warmup."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import WarmupConfigEntry

TO_REDACT = {"serial", "location_name", "email", "token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WarmupConfigEntry
) -> dict[str, Any]:
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "rooms": [
            async_redact_data(asdict(room), TO_REDACT)
            for room in entry.runtime_data.data.values()
        ],
    }
