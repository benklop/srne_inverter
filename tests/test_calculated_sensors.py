"""Tests for calculated sensors defined via YAML formulas."""

from unittest.mock import MagicMock

import pytest

from custom_components.srne_inverter.entities.configurable_sensor import (
    ConfigurableSensor,
)


@pytest.fixture
def mock_config_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Test SRNE Inverter"
    entry.data = {}
    return entry


def _coordinator(data):
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.is_register_failed = MagicMock(return_value=False)
    coordinator.is_entity_unavailable = MagicMock(return_value=False)
    return coordinator


def test_self_sufficiency_formula(mock_config_entry):
    coordinator = _coordinator(
        {"pv_power": 1500, "load_power": 3000, "connected": True}
    )
    cfg = {
        "entity_id": "self_sufficiency",
        "name": "Self Sufficiency",
        "source_type": "calculated",
        "depends_on": ["pv_power", "load_power"],
        "formula": "{{ ([100, (pv_power / load_power * 100)] | min) if load_power else 100 }}",
        "unit_of_measurement": "%",
    }
    sensor = ConfigurableSensor(coordinator, mock_config_entry, cfg)
    assert sensor.native_value == 50.0


def test_self_sufficiency_clamped_to_100(mock_config_entry):
    coordinator = _coordinator(
        {"pv_power": 5000, "load_power": 3000, "connected": True}
    )
    cfg = {
        "entity_id": "self_sufficiency",
        "name": "Self Sufficiency",
        "source_type": "calculated",
        "depends_on": ["pv_power", "load_power"],
        "formula": "{{ ([100, (pv_power / load_power * 100)] | min) if load_power else 100 }}",
    }
    sensor = ConfigurableSensor(coordinator, mock_config_entry, cfg)
    assert sensor.native_value == 100.0


def test_battery_power_signed_sum(mock_config_entry):
    coordinator = _coordinator(
        {
            "pv_power": 2000,
            "load_power": 1500,
            "grid_power": -200,
            "connected": True,
        }
    )
    cfg = {
        "entity_id": "battery_power",
        "name": "Battery Power",
        "source_type": "calculated",
        "depends_on": ["pv_power", "load_power", "grid_power"],
        "formula": "{{ pv_power - load_power - grid_power }}",
        "unit_of_measurement": "W",
    }
    sensor = ConfigurableSensor(coordinator, mock_config_entry, cfg)
    assert sensor.native_value == 700.0
