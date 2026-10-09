"""Sensor platform for Warmup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RUN_MODE_OVERRIDE, Room
from .const import CURRENCIES
from .coordinator import WarmupConfigEntry, WarmupCoordinator
from .entity import WarmupEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WarmupSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Room], float | int | None]
    exists_fn: Callable[[Room], bool] = lambda room: True


SENSORS: tuple[WarmupSensorDescription, ...] = (
    WarmupSensorDescription(
        key="floor_temperature",
        translation_key="floor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda room: room.floor_temperature,
        exists_fn=lambda room: room.floor_temperature is not None,
    ),
    WarmupSensorDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda room: room.air_temperature,
    ),
    WarmupSensorDescription(
        key="override_remaining",
        translation_key="override_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda room: (
            room.override_minutes if room.run_mode == RUN_MODE_OVERRIDE else 0
        ),
    ),
    WarmupSensorDescription(
        key="rated_power",
        translation_key="rated_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.rated_power,
        exists_fn=lambda room: room.rated_power is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for room_id, room in coordinator.data.items():
        entities.extend(
            WarmupSensor(coordinator, room_id, description)
            for description in SENSORS
            if description.exists_fn(room)
        )
        entities.append(WarmupEnergySensor(coordinator, room_id))
        entities.append(WarmupCostSensor(coordinator, room_id))
    async_add_entities(entities)


class WarmupSensor(WarmupEntity, SensorEntity):
    """A plain reading from a Warmup room."""

    entity_description: WarmupSensorDescription

    def __init__(
        self,
        coordinator: WarmupCoordinator,
        room_id: int,
        description: WarmupSensorDescription,
    ) -> None:
        super().__init__(coordinator, room_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.room)


class WarmupEnergySensor(WarmupEntity, SensorEntity):
    """Energy used today, as counted by Warmup.

    The counter restarts every day, which total_increasing reports to the
    Energy dashboard as a meter reset. A drop has to be seen on two polls in
    a row before it is passed on, so a one-off bad reading is not counted as
    a reset.
    """

    _attr_translation_key = "energy_today"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: WarmupCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id, "energy_today")
        self._attr_native_value = self.room.energy_today
        self._pending_drop = False

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._room_id in self.coordinator.data:
            new = self.room.energy_today
            current = self._attr_native_value
            if new is not None:
                if current is not None and new < current and not self._pending_drop:
                    self._pending_drop = True
                else:
                    self._pending_drop = False
                    self._attr_native_value = new
        super()._handle_coordinator_update()


class WarmupCostSensor(WarmupEntity, SensorEntity):
    """Cost of today's energy at the tariff set in the Warmup account."""

    _attr_translation_key = "cost_today"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: WarmupCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id, "cost_today")

    @property
    def native_unit_of_measurement(self) -> str:
        return CURRENCIES.get(self.room.currency, self.hass.config.currency)

    @property
    def native_value(self) -> float | None:
        return self.room.cost_today
