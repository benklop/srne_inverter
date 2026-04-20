"""Tests for learned-timeout diagnostic sensors."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import UnitOfTime

from custom_components.srne_inverter.const import DOMAIN, MODBUS_RESPONSE_TIMEOUT
from custom_components.srne_inverter.entities.learned_timeout_sensor import (
    LearnedTimeoutSensor,
)


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.unique_id = None
    entry.title = "Test SRNE Inverter"
    entry.data = {"name": "Test Inverter"}
    return entry


def test_learned_timeout_sensor_uses_defaults_without_storage(mock_entry):
    coordinator = MagicMock(
        spec=["last_update_success", "data"],
    )
    coordinator.last_update_success = True
    coordinator.data = {"connected": True}

    sensor = LearnedTimeoutSensor(
        coordinator, mock_entry, "modbus_read", "Modbus Read Timeout"
    )

    assert sensor._attr_unique_id == "test_entry_id_learned_timeout_modbus_read"
    assert sensor._attr_native_unit_of_measurement == UnitOfTime.SECONDS
    assert sensor.native_value == MODBUS_RESPONSE_TIMEOUT


def test_learned_timeout_sensor_reads_coordinator_map(mock_entry):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = {"connected": True}
    coordinator._learned_timeouts = {"modbus_read": 0.812}

    sensor = LearnedTimeoutSensor(
        coordinator, mock_entry, "modbus_read", "Modbus Read Timeout"
    )

    assert sensor.native_value == 0.812


def test_learned_timeout_device_grouping(mock_entry):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = {"connected": True}
    sensor = LearnedTimeoutSensor(
        coordinator, mock_entry, "ble_send", "BLE Send Timeout"
    )
    assert sensor.device_info["identifiers"] == {(DOMAIN, mock_entry.entry_id)}
