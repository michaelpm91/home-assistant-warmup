"""Calendar platform for Warmup: the thermostat's weekly schedule."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import WarmupConfigEntry, WarmupCoordinator
from .entity import WarmupEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WarmupConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        WarmupScheduleCalendar(coordinator, room_id) for room_id in coordinator.data
    )


def _at(day: date, value: str) -> datetime:
    """Combine a day with an HH:MM time, where 24:00 is the next midnight."""
    hours, minutes = (int(part) for part in value.split(":")[:2])
    midnight = datetime.combine(day, datetime.min.time(), dt_util.get_default_time_zone())
    return midnight + timedelta(hours=hours, minutes=minutes)


class WarmupScheduleCalendar(WarmupEntity, CalendarEntity):
    """Shows the heating periods of the weekly schedule.

    The periods repeat every week. They only drive the thermostat while it is
    in schedule mode.
    """

    _attr_translation_key = "schedule"

    def __init__(self, coordinator: WarmupCoordinator, room_id: int) -> None:
        super().__init__(coordinator, room_id, "schedule")

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        schedule = self.room.schedule
        if len(schedule) != 7:
            return []
        events: list[CalendarEvent] = []
        day = dt_util.as_local(start).date() - timedelta(days=1)
        last = dt_util.as_local(end).date()
        while day <= last:
            for period in schedule[day.weekday()]:
                try:
                    period_start = _at(day, period.start)
                    period_end = _at(day, period.end)
                except ValueError:
                    continue
                if period_end <= period_start:
                    period_end += timedelta(days=1)
                if period_end > start and period_start < end:
                    events.append(
                        CalendarEvent(
                            start=period_start,
                            end=period_end,
                            summary=f"{period.temperature:g} °C",
                        )
                    )
            day += timedelta(days=1)
        return sorted(events, key=lambda event: event.start)

    @property
    def event(self) -> CalendarEvent | None:
        """The current period, or else the next one."""
        now = dt_util.now()
        events = self._events(now, now + timedelta(days=8))
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return self._events(start_date, end_date)
