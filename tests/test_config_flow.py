"""Smoke tests for SRNE config flow (current multi-step onboarding)."""

from unittest.mock import MagicMock

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.srne_inverter.config_flow import SRNEConfigFlow
from custom_components.srne_inverter.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_BLE,
    CONNECTION_TYPE_TCP,
)
from custom_components.srne_inverter.onboarding.state_machine import (
    OnboardingState,
    OnboardingStateMachine,
)


@pytest.mark.asyncio
async def test_async_step_user_shows_connection_choice():
    flow = SRNEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    result = await flow.async_step_user()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "errors" not in result or result.get("errors") in (None, {})


@pytest.mark.asyncio
async def test_async_step_user_ble_selection_continues_flow():
    flow = SRNEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    result = await flow.async_step_user(
        user_input={CONF_CONNECTION_TYPE: CONNECTION_TYPE_BLE}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "ble_device"


@pytest.mark.asyncio
async def test_async_step_user_tcp_selection_shows_tcp_form():
    flow = SRNEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    result = await flow.async_step_user(
        user_input={CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "tcp"


@pytest.mark.asyncio
async def test_welcome_initializes_context_and_fixes_state_from_device_selected():
    """BLE/USB/TCP paths end at DEVICE_SELECTED; first welcome view must enter WELCOME FSM state."""
    flow = SRNEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow._connection_type = CONNECTION_TYPE_TCP
    flow._selected_address = "192.168.1.50"
    flow._selected_port = 8899
    flow._discovered_devices = {"192.168.1.50": "Test TCP"}
    flow._state_machine = OnboardingStateMachine()
    assert flow._state_machine.transition(OnboardingState.DEVICE_SELECTED) is True

    result = await flow.async_step_welcome(user_input=None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "welcome"
    assert flow._state_machine.current_state == OnboardingState.WELCOME
    assert flow._onboarding_context is not None
    assert flow._onboarding_context.device_address == "192.168.1.50"
    assert flow._onboarding_context.connection_type == CONNECTION_TYPE_TCP
    assert flow._onboarding_context.device_port == 8899
