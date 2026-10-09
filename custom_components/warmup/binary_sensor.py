"""Binary sensor platform for Warmup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Room
from .coordinator import WarmupConfigEntry, WarmupCoordinator
from .entity import WarmupEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WarmupBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Room], bool | None]


BINARY_SENSORS: tuple[WarmupBinarySensorDescription, ...] = (
    WarmupBinarySensorDescription(
        key="air_sensor_fault",
        translation_key="air_sensor_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.fault_air,
    ),
    WarmupBinarySensorDescription(
        key="floor_sensor_fault",
        translation_key="floor_sensor_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.fault_floor,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        WarmupBinarySensor(coordinator, room_id, description)
        for room_id in coordinator.data
        for description in BINARY_SENSORS
    )


class WarmupBinarySensor(WarmupEntity, BinarySensorEntity):
    """An on/off reading from a Warmup room."""

    entity_description: WarmupBinarySensorDescription

    def __init__(
        self,
        coordinator: WarmupCoordinator,
        room_id: int,
        description: WarmupBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, room_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.room)
