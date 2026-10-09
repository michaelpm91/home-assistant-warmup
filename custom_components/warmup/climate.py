"""Climate platform for Warmup."""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    DAYS,
    ROOM_MODE_PROGRAM,
    RUN_MODE_FROST,
    RUN_MODE_HOLIDAY,
    RUN_MODE_OFF,
    RUN_MODE_OVERRIDE,
    SchedulePeriod,
    WarmupError,
)
from .const import (
    ATTR_DURATION,
    ATTR_END,
    ATTR_SCHEDULE,
    ATTR_START,
    CONF_OVERRIDE_MINUTES,
    DEFAULT_OVERRIDE_MINUTES,
    SERVICE_CANCEL_OVERRIDE,
    SERVICE_SET_OVERRIDE,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import WarmupConfigEntry, WarmupCoordinator
from .entity import WarmupEntity

PARALLEL_UPDATES = 1

PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_START): cv.time,
        vol.Required(ATTR_END): cv.time,
        vol.Required(ATTR_TEMPERATURE): vol.Coerce(float),
    }
)
SCHEDULE_SCHEMA = vol.All(
    {vol.Optional(day): [PERIOD_SCHEMA] for day in DAYS}, vol.Length(min=1)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        WarmupClimate(coordinator, room_id) for room_id in coordinator.data
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_OVERRIDE,
        {
            vol.Required(ATTR_TEMPERATURE): vol.Coerce(float),
            vol.Optional(ATTR_DURATION): vol.All(
                cv.time_period, cv.positive_timedelta
            ),
        },
        "async_set_override",
    )
    platform.async_register_entity_service(
        SERVICE_CANCEL_OVERRIDE, None, "async_cancel_override"
    )
    platform.async_register_entity_service(
        SERVICE_SET_SCHEDULE,
        {vol.Required(ATTR_SCHEDULE): SCHEDULE_SCHEMA},
        "async_set_schedule",
    )


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


class WarmupClimate(WarmupEntity, ClimateEntity):
    """A Warmup thermostat."""

    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = PRECISION_HALVES
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_preset_modes = [PRESET_NONE, PRESET_AWAY]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: WarmupCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id, "climate")

    @property
    def current_temperature(self) -> float | None:
        return self.room.current_temperature

    @property
    def target_temperature(self) -> float | None:
        return self.room.target_temperature

    @property
    def min_temp(self) -> float:
        return self.room.min_temperature or super().min_temp

    @property
    def max_temp(self) -> float:
        return self.room.max_temperature or super().max_temp

    @property
    def hvac_mode(self) -> HVACMode:
        room = self.room
        if room.run_mode == RUN_MODE_OFF:
            return HVACMode.OFF
        # Overrides, frost and holidays sit on top of the underlying room mode.
        if room.room_mode == ROOM_MODE_PROGRAM:
            return HVACMode.AUTO
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        room = self.room
        if room.run_mode == RUN_MODE_OFF:
            return HVACAction.OFF
        return HVACAction.HEATING if room.heating else HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        if self.room.run_mode in (RUN_MODE_FROST, RUN_MODE_HOLIDAY):
            return PRESET_AWAY
        return PRESET_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        room = self.room
        attributes: dict[str, Any] = {
            "run_mode": room.run_mode,
            "room_mode": room.room_mode,
            "fixed_temperature": room.fixed_temperature,
            "schedule": room.schedule_as_dict(),
        }
        if room.run_mode == RUN_MODE_OVERRIDE:
            attributes["override_temperature"] = room.override_temperature
            attributes["override_minutes_remaining"] = room.override_minutes
        if room.holiday_start:
            attributes["holiday_start"] = room.holiday_start
            attributes["holiday_end"] = room.holiday_end
        return attributes

    async def _call(self, action) -> None:
        try:
            await action
        except WarmupError as err:
            raise HomeAssistantError(f"Warmup rejected the command: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        room = self.room
        client = self.coordinator.client
        if (
            room.room_mode == ROOM_MODE_PROGRAM
            and room.run_mode not in (RUN_MODE_OFF, RUN_MODE_FROST)
        ):
            # Same as turning the dial on the thermostat: a temporary
            # override, after which the program resumes.
            minutes = self.coordinator.config_entry.options.get(
                CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES
            )
            await self._call(
                client.set_override(room.location_id, room.id, temperature, minutes)
            )
        else:
            await self._call(client.set_fixed(room.location_id, room.id, temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        room = self.room
        client = self.coordinator.client
        if hvac_mode == HVACMode.OFF:
            await self._call(client.set_off(room.location_id, room.id))
        elif hvac_mode == HVACMode.AUTO:
            await self._call(client.set_program(room.location_id, room.id))
        elif hvac_mode == HVACMode.HEAT:
            await self._call(client.set_fixed(room.location_id, room.id))

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        """Go back to whichever of program or fixed was in use before."""
        if self.room.room_mode == ROOM_MODE_PROGRAM:
            await self.async_set_hvac_mode(HVACMode.AUTO)
        else:
            await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        room = self.room
        if preset_mode == PRESET_AWAY:
            await self._call(
                self.coordinator.client.set_frost(room.location_id, room.id)
            )
        elif room.run_mode == RUN_MODE_FROST:
            await self.async_turn_on()

    async def async_set_override(
        self, temperature: float, duration: timedelta | None = None
    ) -> None:
        room = self.room
        if duration is None:
            minutes = self.coordinator.config_entry.options.get(
                CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES
            )
        else:
            minutes = max(1, round(duration.total_seconds() / 60))
        await self._call(
            self.coordinator.client.set_override(
                room.location_id, room.id, temperature, minutes
            )
        )

    async def async_cancel_override(self) -> None:
        room = self.room
        await self._call(
            self.coordinator.client.cancel_override(room.location_id, room.id)
        )

    async def async_set_schedule(self, schedule: dict[str, list[dict]]) -> None:
        """Replace the program for the given days, keeping the others."""
        room = self.room
        if len(room.schedule) != 7:
            current: list[list[SchedulePeriod]] = [[] for _ in DAYS]
        else:
            current = [list(day) for day in room.schedule]
        for index, day in enumerate(DAYS):
            if day not in schedule:
                continue
            periods = sorted(schedule[day], key=lambda p: p[ATTR_START])
            previous_end: time | None = None
            for period in periods:
                if period[ATTR_END] <= period[ATTR_START] or (
                    previous_end is not None and period[ATTR_START] < previous_end
                ):
                    raise ServiceValidationError(
                        f"Periods for {day} must not overlap and must end "
                        "after they start"
                    )
                previous_end = period[ATTR_END]
            current[index] = [
                SchedulePeriod(
                    _format_time(period[ATTR_START]),
                    _format_time(period[ATTR_END]),
                    period[ATTR_TEMPERATURE],
                )
                for period in periods
            ]
        await self._call(
            self.coordinator.client.set_schedule(room.location_id, room.id, current)
        )
