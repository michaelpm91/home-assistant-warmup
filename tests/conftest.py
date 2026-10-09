"""Shared fixtures for the Warmup tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.warmup.api import GRAPHQL_URL
from custom_components.warmup.const import DOMAIN
from homeassistant.const import CONF_EMAIL, CONF_TOKEN

STATE = json.loads((Path(__file__).parent / "fixtures" / "state.json").read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration under test."""


@pytest.fixture
def state() -> dict:
    """A mutable copy of the API state response."""
    return copy.deepcopy(STATE)


def room_of(state: dict) -> dict:
    return state["data"]["user"]["locations"][0]["rooms"][0]


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={CONF_EMAIL: "user@example.com", CONF_TOKEN: "tok"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup(hass, config_entry, aioclient_mock, state):
    """Set the integration up against a mocked API and return the entry."""
    aioclient_mock.post(GRAPHQL_URL, json=state)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
