"""Tests for the config flow."""

from __future__ import annotations

from custom_components.warmup.api import LOGIN_URL
from custom_components.warmup.const import CONF_OVERRIDE_MINUTES, DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType

from .conftest import GRAPHQL_URL

LOGIN_OK = {"status": {"result": "success"}, "response": {"token": "abc"}}
LOGIN_BAD = {"status": {"result": "error"}, "response": {"errorCode": 124}}
CREDENTIALS = {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "pw"}


async def test_user_flow(hass, aioclient_mock, state):
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    aioclient_mock.post(GRAPHQL_URL, json=state)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_EMAIL: "user@example.com", CONF_TOKEN: "abc"}


async def test_user_flow_bad_password_then_ok(hass, aioclient_mock, state):
    aioclient_mock.post(LOGIN_URL, json=LOGIN_BAD)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    aioclient_mock.post(GRAPHQL_URL, json=state)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect(hass, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_account(hass, aioclient_mock, config_entry):
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "User@Example.com", CONF_PASSWORD: "pw"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, aioclient_mock, setup):
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    result = await setup.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert setup.data[CONF_TOKEN] == "abc"


async def test_options(hass, setup):
    result = await hass.config_entries.options.async_init(setup.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_OVERRIDE_MINUTES: 120}
    )
    await hass.async_block_till_done()
    assert setup.options == {CONF_OVERRIDE_MINUTES: 120}
