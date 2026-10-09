"""Async client for the Warmup cloud API.

Login goes through the legacy app endpoint and returns a long-lived token.
Everything else is GraphQL. Temperatures are tenths of a degree on the wire
and are converted to floats here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOGIN_URL = "https://api.warmup.com/apps/app/v1"
GRAPHQL_URL = "https://apil.warmup.com/graphql"
APP_TOKEN = 'M=;He<Xtg"$}4N%5k{$:PD+WA"]D<;#PriteY|VTuA>_iyhs+vA"4lic{6-LqNM:'
HEADERS = {
    "user-agent": "WARMUP_APP",
    "accept": "*/*",
    "content-type": "application/json",
    "app-token": APP_TOKEN,
    "app-version": "1.8.1",
    "accept-language": "en-gb",
}
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

ERROR_UNAUTHORIZED = 110

RUN_MODE_OFF = "off"
RUN_MODE_SCHEDULE = "schedule"
RUN_MODE_OVERRIDE = "override"
RUN_MODE_FIXED = "fixed"
RUN_MODE_FROST = "anti_frost"
RUN_MODE_HOLIDAY = "holiday"

ROOM_MODE_PROGRAM = "program"
ROOM_MODE_FIXED = "fixed"

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_STATE_QUERY = """{
  user {
    locations {
      id name locMode
      address { currency }
      holiday { holStart holEnd holTemp }
      rooms {
        id type roomName serial runMode roomMode
        targetTemp currentTemp mainLabel fixedTemp overrideTemp overrideDur
        comfortTemp sleepTemp awayTemp
        energy cost schedule isUnavailable lastPoll
        thermostat4ies {
          deviceSN appFw airTemp floor1Temp floor2Temp minTemp maxTemp
          isFaultAir isFaultFloor1 isFaultFloor2 heatingTarget
          parameters { outputStatus systemPower }
        }
      }
    }
  }
}"""


class WarmupError(Exception):
    """Base error for the Warmup API."""


class WarmupAuthError(WarmupError):
    """Credentials or token were rejected."""


class WarmupConnectionError(WarmupError):
    """The API could not be reached."""


class WarmupApiError(WarmupError):
    """The API returned an error."""


def _temp(value: Any) -> float | None:
    """Convert a tenths-of-a-degree value to degrees."""
    if value is None or value == "":
        return None
    try:
        return int(value) / 10
    except (TypeError, ValueError):
        return None


def _to_tenths(temperature: float) -> int:
    return round(temperature * 10)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class SchedulePeriod:
    """One heating period of a day's program."""

    start: str
    end: str
    temperature: float

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "temperature": self.temperature}


@dataclass(frozen=True)
class Room:
    """A room, which for Warmup means one thermostat."""

    id: int
    location_id: int
    location_name: str
    name: str
    serial: str
    model: str | None
    run_mode: str | None
    room_mode: str | None
    target_temperature: float | None
    current_temperature: float | None
    main_probe: str | None
    floor_temperature: float | None
    air_temperature: float | None
    fixed_temperature: float | None
    override_temperature: float | None
    override_minutes: int
    comfort_temperature: float | None
    sleep_temperature: float | None
    away_temperature: float | None
    min_temperature: float | None
    max_temperature: float | None
    energy_today: float | None
    cost_today: float | None
    currency: int | None
    heating: bool
    rated_power: int | None
    firmware: str | None
    unavailable: bool
    fault_air: bool
    fault_floor: bool
    last_poll: int | None
    holiday_start: str | None
    holiday_end: str | None
    # Weekly program, index 0 = Monday.
    schedule: tuple[tuple[SchedulePeriod, ...], ...] = field(default=())

    def schedule_as_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            day: [period.as_dict() for period in periods]
            for day, periods in zip(DAYS, self.schedule)
        }


def _parse_schedule(raw: Any) -> tuple[tuple[SchedulePeriod, ...], ...]:
    if not isinstance(raw, list):
        return ()
    days: dict[int, tuple[SchedulePeriod, ...]] = {}
    for entry in raw:
        try:
            day = int(entry["day"])
            days[day] = tuple(
                SchedulePeriod(p["start"], p["end"], int(p["temp"]) / 10)
                for p in entry.get("value") or []
            )
        except (KeyError, TypeError, ValueError):
            _LOGGER.debug("Ignoring unparsable schedule entry: %s", entry)
    if not days:
        return ()
    return tuple(days.get(day, ()) for day in range(7))


def _parse_room(location: dict[str, Any], room: dict[str, Any]) -> Room:
    thermostats = room.get("thermostat4ies") or [{}]
    thermostat = thermostats[0] or {}
    parameters = thermostat.get("parameters") or {}
    holiday = location.get("holiday") or {}
    run_mode = room.get("runMode")

    floor = _temp(thermostat.get("floor1Temp"))
    target = _temp(room.get("targetTemp"))
    current = _temp(room.get("currentTemp"))
    # The 7iE never raises outputStatus, so fall back to comparing the
    # controlling probe with the target.
    heating = run_mode != RUN_MODE_OFF and (
        bool(parameters.get("outputStatus"))
        or (target is not None and current is not None and current < target)
    )

    return Room(
        id=room["id"],
        location_id=location["id"],
        location_name=location.get("name") or "",
        name=room.get("roomName") or f"Room {room['id']}",
        serial=room.get("serial") or thermostat.get("deviceSN") or str(room["id"]),
        model=room.get("type"),
        run_mode=run_mode,
        room_mode=room.get("roomMode"),
        target_temperature=None if run_mode == RUN_MODE_OFF else target,
        current_temperature=current,
        main_probe=room.get("mainLabel"),
        # A probe that is not fitted reports 0.
        floor_temperature=floor if floor else None,
        air_temperature=_temp(thermostat.get("airTemp")),
        fixed_temperature=_temp(room.get("fixedTemp")),
        override_temperature=_temp(room.get("overrideTemp")),
        override_minutes=int(room.get("overrideDur") or 0),
        comfort_temperature=_temp(room.get("comfortTemp")),
        sleep_temperature=_temp(room.get("sleepTemp")),
        away_temperature=_temp(room.get("awayTemp")),
        min_temperature=_temp(thermostat.get("minTemp")),
        max_temperature=_temp(thermostat.get("maxTemp")),
        energy_today=_number(room.get("energy")),
        cost_today=_number(room.get("cost")),
        currency=(location.get("address") or {}).get("currency"),
        heating=heating,
        rated_power=parameters.get("systemPower") or None,
        firmware=thermostat.get("appFw") or None,
        unavailable=bool(room.get("isUnavailable")),
        fault_air=bool(thermostat.get("isFaultAir")),
        fault_floor=bool(
            thermostat.get("isFaultFloor1") or thermostat.get("isFaultFloor2")
        ),
        last_poll=room.get("lastPoll"),
        holiday_start=holiday.get("holStart"),
        holiday_end=holiday.get("holEnd"),
        schedule=_parse_schedule(room.get("schedule")),
    )


class WarmupClient:
    """Talks to the Warmup cloud."""

    def __init__(self, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._session = session
        self._token = token

    async def login(self, email: str, password: str) -> str:
        """Exchange credentials for an API token."""
        body = {
            "request": {
                "email": email,
                "password": password,
                "method": "userLogin",
                "appId": "WARMUP-APP-V001",
            }
        }
        data = await self._post(LOGIN_URL, HEADERS, body)
        if (data.get("status") or {}).get("result") != "success":
            raise WarmupAuthError("Login was rejected")
        try:
            self._token = data["response"]["token"]
        except (KeyError, TypeError) as err:
            raise WarmupApiError("Login response had no token") from err
        return self._token

    async def get_rooms(self) -> dict[int, Room]:
        """Fetch every room on the account, keyed by room id."""
        data = await self._graphql(_STATE_QUERY)
        rooms: dict[int, Room] = {}
        for location in (data.get("user") or {}).get("locations") or []:
            for room in location.get("rooms") or []:
                rooms[room["id"]] = _parse_room(location, room)
        return rooms

    async def set_fixed(
        self, location_id: int, room_id: int, temperature: float | None = None
    ) -> None:
        """Hold a fixed temperature, or the last one used when not given."""
        args = f"lid: {location_id}, rid: {room_id}"
        if temperature is not None:
            args += f", temperature: {_to_tenths(temperature)}"
        await self._graphql(f"mutation {{ deviceFixed({args}) }}")

    async def set_program(self, location_id: int, room_id: int) -> None:
        """Follow the weekly program."""
        await self._graphql(
            f"mutation {{ deviceProgram(lid: {location_id}, rid: {room_id}) }}"
        )

    async def set_override(
        self, location_id: int, room_id: int, temperature: float, minutes: int
    ) -> None:
        """Hold a temperature for a number of minutes, then resume."""
        await self._graphql(
            f"mutation {{ deviceOverride(lid: {location_id}, rid: {room_id}, "
            f"temperature: {_to_tenths(temperature)}, minutes: {int(minutes)}) }}"
        )

    async def cancel_override(self, location_id: int, room_id: int) -> None:
        await self._graphql(
            f"mutation {{ cancelOverride(lid: {location_id}, rid: {room_id}) "
            "{ runMode } }"
        )

    async def set_off(self, location_id: int, room_id: int) -> None:
        await self._graphql(
            f"mutation {{ deviceOff(lid: {location_id}, rid: {room_id}) }}"
        )

    async def set_frost(self, location_id: int, room_id: int) -> None:
        """Frost protection: hold the thermostat's minimum temperature."""
        await self._graphql(
            f"mutation {{ deviceFrost(lid: {location_id}, rid: {room_id}) }}"
        )

    async def set_schedule(
        self,
        location_id: int,
        room_id: int,
        schedule: list[list[SchedulePeriod]],
    ) -> None:
        """Replace the weekly program. Takes seven days, Monday first."""
        if len(schedule) != 7:
            raise ValueError("A schedule needs exactly seven days")
        payload = [
            [
                {
                    "start": period.start,
                    "end": period.end,
                    "temp": str(_to_tenths(period.temperature)),
                }
                for period in day
            ]
            for day in schedule
        ]
        await self._graphql(
            "mutation($s: String!) { deviceSchedule("
            f"lid: {location_id}, rid: {room_id}, schedule: $s) {{ runMode }} }}",
            {"s": json.dumps(payload)},
        )

    async def _graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._token is None:
            raise WarmupAuthError("Not logged in")
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        headers = {**HEADERS, "warmup-authorization": self._token}
        data = await self._post(GRAPHQL_URL, headers, body)
        if data.get("status") != "success":
            errors = data.get("errors") or []
            message = "; ".join(
                str(e.get("message")) for e in errors if isinstance(e, dict)
            )
            if any(
                isinstance(e, dict) and e.get("errorCode") == ERROR_UNAUTHORIZED
                for e in errors
            ):
                raise WarmupAuthError(message or "Unauthorized")
            raise WarmupApiError(message or "Unknown API error")
        return data.get("data") or {}

    async def _post(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                url, headers=headers, json=body, timeout=REQUEST_TIMEOUT
            ) as response:
                # Errors come back as JSON with a 4xx status, so parse first.
                try:
                    data = await response.json(content_type=None)
                except ValueError as err:
                    if response.status == 401:
                        raise WarmupAuthError("Unauthorized") from err
                    raise WarmupApiError(
                        f"Unexpected response (HTTP {response.status})"
                    ) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WarmupConnectionError(str(err) or type(err).__name__) from err
        if not isinstance(data, dict):
            raise WarmupApiError("Unexpected response shape")
        return data
