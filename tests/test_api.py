"""Tests for the API client."""

from __future__ import annotations

import json

import pytest

from custom_components.warmup.api import (
    GRAPHQL_URL,
    LOGIN_URL,
    SchedulePeriod,
    WarmupApiError,
    WarmupAuthError,
    WarmupClient,
    WarmupConnectionError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import room_of


def _client(hass, token="tok"):
    return WarmupClient(async_get_clientsession(hass), token)


async def test_login(hass, aioclient_mock):
    aioclient_mock.post(
        LOGIN_URL,
        json={"status": {"result": "success"}, "response": {"token": "abc"}},
    )
    assert await _client(hass, None).login("user@example.com", "pw") == "abc"
    assert aioclient_mock.mock_calls[0][2]["request"]["method"] == "userLogin"


async def test_login_rejected(hass, aioclient_mock):
    aioclient_mock.post(
        LOGIN_URL, json={"status": {"result": "error"}, "response": {"errorCode": 124}}
    )
    with pytest.raises(WarmupAuthError):
        await _client(hass, None).login("user@example.com", "bad")


async def test_get_rooms(hass, aioclient_mock, state):
    aioclient_mock.post(GRAPHQL_URL, json=state)
    rooms = await _client(hass).get_rooms()
    room = rooms[2002]
    assert room.name == "Bathroom"
    assert room.model == "7ie"
    assert room.location_id == 1001
    assert room.target_temperature == 19.0
    assert room.current_temperature == 20.5
    assert room.floor_temperature == 20.5
    assert room.air_temperature == 21.0
    assert (room.min_temperature, room.max_temperature) == (7.0, 30.0)
    assert room.energy_today == 0.25
    assert room.cost_today == 0.05
    assert room.heating is False
    assert room.rated_power == 300
    assert room.schedule[0] == (
        SchedulePeriod("06:00", "08:00", 21.0),
        SchedulePeriod("20:00", "23:00", 20.0),
    )
    assert room.schedule_as_dict()["saturday"] == []
    assert aioclient_mock.mock_calls[0][3]["warmup-authorization"] == "tok"


async def test_off_has_no_target(hass, aioclient_mock, state):
    room_of(state).update(runMode="off", targetTemp=0)
    aioclient_mock.post(GRAPHQL_URL, json=state)
    room = (await _client(hass).get_rooms())[2002]
    assert room.target_temperature is None


async def test_unauthorized(hass, aioclient_mock):
    aioclient_mock.post(
        GRAPHQL_URL,
        status=401,
        json={"status": "error", "errors": [{"errorCode": 110, "message": "Unauthorized."}]},
    )
    with pytest.raises(WarmupAuthError):
        await _client(hass).get_rooms()


async def test_api_error(hass, aioclient_mock):
    aioclient_mock.post(
        GRAPHQL_URL,
        status=409,
        json={"status": "error", "errors": [{"errorCode": 191, "message": "Internal server error"}]},
    )
    with pytest.raises(WarmupApiError, match="Internal server error"):
        await _client(hass).get_rooms()


async def test_connection_error(hass, aioclient_mock):
    aioclient_mock.post(GRAPHQL_URL, exc=TimeoutError())
    with pytest.raises(WarmupConnectionError):
        await _client(hass).get_rooms()


async def test_mutations(hass, aioclient_mock):
    aioclient_mock.post(GRAPHQL_URL, json={"status": "success", "data": {}})
    client = _client(hass)
    await client.set_fixed(1, 2, 21.5)
    await client.set_fixed(1, 2)
    await client.set_override(1, 2, 22, 90)
    await client.set_schedule(
        1, 2, [[SchedulePeriod("06:00", "08:00", 21.0)]] + [[] for _ in range(6)]
    )
    queries = [call[2] for call in aioclient_mock.mock_calls]
    assert "deviceFixed(lid: 1, rid: 2, temperature: 215)" in queries[0]["query"]
    assert "deviceFixed(lid: 1, rid: 2)" in queries[1]["query"]
    assert (
        "deviceOverride(lid: 1, rid: 2, temperature: 220, minutes: 90)"
        in queries[2]["query"]
    )
    sent = json.loads(queries[3]["variables"]["s"])
    assert sent[0] == [{"start": "06:00", "end": "08:00", "temp": "210"}]
    assert sent[1:] == [[]] * 6
