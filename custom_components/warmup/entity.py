"""Base entity for Warmup."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Room
from .const import DOMAIN, MANUFACTURER, MODELS
from .coordinator import WarmupCoordinator


class WarmupEntity(CoordinatorEntity[WarmupCoordinator]):
    """An entity belonging to one Warmup room."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WarmupCoordinator, room_id: int, key: str) -> None:
        super().__init__(coordinator)
        self._room_id = room_id
        room = self.room
        self._attr_unique_id = f"{room.serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.serial)},
            manufacturer=MANUFACTURER,
            model=MODELS.get(room.model or "", room.model),
            name=room.name,
            serial_number=room.serial,
            sw_version=room.firmware,
            suggested_area=room.name,
        )

    @property
    def room(self) -> Room:
        return self.coordinator.data[self._room_id]

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._room_id in self.coordinator.data
            and not self.room.unavailable
        )
