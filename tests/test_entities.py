"""Tests for setup, entities and services."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.warmup.const import DOMAIN, SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from .conftest import GRAPHQL_URL, room_of

CLIMATE = "climate.bathroom"


async def _poll(hass, aioclient_mock, state):
    aioclient_mock.clear_requests()
    aioclient_mock.post(GRAPHQL_URL, json=state)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)


def _last_query(aioclient_mock) -> dict:
    mutations = [c[2] for c in aioclient_mock.mock_calls if "mutation" in c[2]["query"]]
    return mutations[-1]


async def test_entities(hass, setup):
    climate = hass.states.get(CLIMATE)
    assert climate.state == "heat"
    assert climate.attributes["current_temperature"] == 20.5
    assert climate.attributes["temperature"] == 19.0
    assert climate.attributes["min_temp"] == 7.0
    assert climate.attributes["max_temp"] == 30.0
    assert climate.attributes["hvac_action"] == "idle"
    assert climate.attributes["preset_mode"] == "none"
    assert climate.attributes["schedule"]["monday"][0] == {
        "start": "06:00",
        "end": "08:00",
        "temperature": 21.0,
    }

    assert hass.states.get("sensor.bathroom_floor_temperature").state == "20.5"
    assert hass.states.get("sensor.bathroom_air_temperature").state == "21.0"
    assert hass.states.get("binary_sensor.bathroom_floor_sensor_fault").state == "off"
    assert hass.states.get("sensor.bathroom_cost_today").attributes[
        "unit_of_measurement"
    ] == "GBP"

    energy = hass.states.get("sensor.bathroom_energy_today")
    assert energy.state == "0.25"
    assert energy.attributes["device_class"] == "energy"
    assert energy.attributes["state_class"] == "total_increasing"
    assert energy.attributes["unit_of_measurement"] == "kWh"


async def test_modes(hass, setup, aioclient_mock, state):
    room_of(state).update(runMode="schedule", roomMode="program", targetTemp=160)
    await _poll(hass, aioclient_mock, state)
    climate = hass.states.get(CLIMATE)
    assert climate.state == "auto"
    assert climate.attributes["hvac_action"] == "idle"

    # Below target counts as heating.
    room_of(state).update(targetTemp=210)
    await _poll(hass, aioclient_mock, state)
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == "heating"

    room_of(state).update(runMode="off", targetTemp=0)
    await _poll(hass, aioclient_mock, state)
    climate = hass.states.get(CLIMATE)
    assert climate.state == "off"
    assert climate.attributes["temperature"] is None

    room_of(state).update(runMode="anti_frost", roomMode="fixed", targetTemp=70)
    await _poll(hass, aioclient_mock, state)
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "away"


async def test_energy_reset_needs_two_polls(hass, setup, aioclient_mock, state):
    entity = "sensor.bathroom_energy_today"
    room_of(state)["energy"] = "0.31"
    await _poll(hass, aioclient_mock, state)
    assert hass.states.get(entity).state == "0.31"

    room_of(state)["energy"] = "0.00"
    await _poll(hass, aioclient_mock, state)
    assert hass.states.get(entity).state == "0.31"
    await _poll(hass, aioclient_mock, state)
    assert hass.states.get(entity).state == "0.0"

    # A single low reading followed by recovery is ignored.
    room_of(state)["energy"] = "0.10"
    await _poll(hass, aioclient_mock, state)
    room_of(state)["energy"] = "0.02"
    await _poll(hass, aioclient_mock, state)
    room_of(state)["energy"] = "0.11"
    await _poll(hass, aioclient_mock, state)
    assert hass.states.get(entity).state == "0.11"


async def test_set_temperature_fixed(hass, setup, aioclient_mock):
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 21.5}, blocking=True
    )
    assert "deviceFixed(lid: 1001, rid: 2002, temperature: 215)" in _last_query(aioclient_mock)["query"]


async def test_set_temperature_in_program_overrides(hass, setup, aioclient_mock, state):
    room_of(state).update(runMode="schedule", roomMode="program")
    await _poll(hass, aioclient_mock, state)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 22}, blocking=True
    )
    assert (
        "deviceOverride(lid: 1001, rid: 2002, temperature: 220, minutes: 60)"
        in _last_query(aioclient_mock)["query"]
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("off", "deviceOff("), ("auto", "deviceProgram("), ("heat", "deviceFixed(lid: 1001, rid: 2002)")],
)
async def test_set_hvac_mode(hass, setup, aioclient_mock, mode, expected):
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": mode}, blocking=True
    )
    assert expected in _last_query(aioclient_mock)["query"]


async def test_preset_away(hass, setup, aioclient_mock):
    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": CLIMATE, "preset_mode": "away"}, blocking=True
    )
    assert "deviceFrost(" in _last_query(aioclient_mock)["query"]


async def test_override_services(hass, setup, aioclient_mock):
    await hass.services.async_call(
        DOMAIN,
        "set_override",
        {"entity_id": CLIMATE, "temperature": 23, "duration": {"minutes": 45}},
        blocking=True,
    )
    assert "temperature: 230, minutes: 45" in _last_query(aioclient_mock)["query"]
    await hass.services.async_call(
        DOMAIN, "cancel_override", {"entity_id": CLIMATE}, blocking=True
    )
    assert "cancelOverride(" in _last_query(aioclient_mock)["query"]


async def test_set_schedule_keeps_other_days(hass, setup, aioclient_mock):
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entity_id": CLIMATE,
            "schedule": {
                "saturday": [
                    {"start": "09:00", "end": "11:00", "temperature": 22},
                    {"start": "07:00", "end": "08:00", "temperature": 21},
                ]
            },
        },
        blocking=True,
    )
    sent = json.loads(_last_query(aioclient_mock)["variables"]["s"])
    assert len(sent) == 7
    assert sent[0][0] == {"start": "06:00", "end": "08:00", "temp": "210"}
    assert sent[5] == [
        {"start": "07:00", "end": "08:00", "temp": "210"},
        {"start": "09:00", "end": "11:00", "temp": "220"},
    ]


async def test_set_schedule_rejects_overlap(hass, setup):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {
                "entity_id": CLIMATE,
                "schedule": {
                    "monday": [
                        {"start": "06:00", "end": "09:00", "temperature": 21},
                        {"start": "08:00", "end": "10:00", "temperature": 21},
                    ]
                },
            },
            blocking=True,
        )


async def test_command_error(hass, setup, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        GRAPHQL_URL,
        status=409,
        json={"status": "error", "errors": [{"errorCode": 191, "message": "nope"}]},
    )
    with pytest.raises(HomeAssistantError, match="nope"):
        await hass.services.async_call(
            "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 21}, blocking=True
        )


async def test_auth_failure_starts_reauth(hass, setup, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        GRAPHQL_URL,
        status=401,
        json={"status": "error", "errors": [{"errorCode": 110, "message": "Unauthorized."}]},
    )
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(CLIMATE).state == "unavailable"
    assert any(setup.async_get_active_flows(hass, {"reauth"}))


async def test_unload(hass, setup):
    assert await hass.config_entries.async_unload(setup.entry_id)
    assert setup.state is ConfigEntryState.NOT_LOADED
