"""Pytest configuration and fixtures for SRNE Inverter tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to Python path so we can import custom_components
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from custom_components.srne_inverter.const import DOMAIN


def configure_mock_hass_core(hass: Mock, config_dir: str) -> None:
    """Attach config + async_add_executor_job so HA Store / entity_registry work.

    MagicMock(spec=HomeAssistant) omits ``config`` (set only in HomeAssistant.__init__).
    """
    import asyncio

    base = Path(config_dir)

    hass.config = MagicMock()
    hass.config.config_dir = config_dir
    hass.config.components = set()

    def _path(*parts: str) -> str:
        if not parts:
            return str(base)
        return str(base.joinpath(*parts))

    hass.config.path = _path
    hass.loop = asyncio.get_event_loop()

    async def _async_add_executor_job(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    hass.async_add_executor_job = AsyncMock(side_effect=_async_add_executor_job)


@pytest.fixture
def full_device_config():
    """Fully processed entities_pilot.yaml (for integration setup tests)."""
    import yaml

    from custom_components.srne_inverter.config_loader import (
        _apply_entity_defaults,
        _process_register_definitions,
        _validate_configuration,
        _validate_device_profile,
    )

    path = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "srne_inverter"
        / "config"
        / "entities_pilot.yaml"
    )
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate_device_profile(config)
    _process_register_definitions(config)
    _apply_entity_defaults(config)
    _validate_configuration(config)
    return config


@pytest.fixture(autouse=True)
def _silence_homeassistant_frame_report():
    """DataUpdateCoordinator calls frame.report_usage; tests use mock hass without setup."""
    with patch("homeassistant.helpers.frame.report_usage", lambda *args, **kwargs: None):
        yield


@pytest.fixture
def mock_config_entry() -> ConfigEntry:
    """Return a mock config entry."""
    return ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="SRNE Inverter",
        data={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF"},
        source="user",
        entry_id="test_entry_id",
    )


@pytest.fixture
def round3_coordinator_data():
    """Mock coordinator data with all Round 3 sensors."""
    return {
        # Existing Round 2
        "battery_soc": 75,
        "machine_state": 5,
        # Round 3 - Battery details
        "battery_voltage": 52.4,
        "battery_current": 12.5,  # Charging
        # Round 3 - Power monitoring
        "pv_power": 3500,
        "grid_power": -1200,  # Exporting (negative)
        "load_power": 2300,
        # Round 3 - Temperatures
        "inverter_temperature": 45.2,
        "battery_temperature": 28.5,
        # Round 3 - Priority
        "energy_priority": 0,  # Solar First
        "connected": True,
    }


@pytest.fixture
def round3_coordinator_data_discharging():
    """Mock data with battery discharging."""
    return {
        "battery_soc": 65,
        "battery_voltage": 51.2,
        "battery_current": -8.3,  # Discharging (negative)
        "pv_power": 500,  # Low solar
        "grid_power": 1800,  # Importing (positive)
        "load_power": 2300,
        "inverter_temperature": 38.5,
        "battery_temperature": 26.1,
        "machine_state": 5,
        "energy_priority": 2,  # Battery First
        "connected": True,
    }


@pytest.fixture
def mock_ble_device():
    """Mock BLE device."""
    device = Mock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "E60000231107692658"
    return device


@pytest.fixture
def mock_bleak_client():
    """Mock BleakClient for BLE communication tests."""
    client = AsyncMock()
    client.is_connected = True
    return client


@pytest.fixture
def mock_coordinator(round3_coordinator_data):
    """Create a mock coordinator with data."""
    from datetime import datetime
    from unittest.mock import PropertyMock

    coordinator = Mock()
    coordinator.data = round3_coordinator_data
    coordinator.last_update_success_time = "2024-02-03T12:00:00"
    coordinator.async_request_refresh = AsyncMock()
    from custom_components.srne_inverter.application.use_cases.write_register_result import (
        WriteRegisterResult,
    )

    coordinator.async_write_register = AsyncMock(
        return_value=WriteRegisterResult(success=True)
    )

    # Use PropertyMock to ensure last_update_success returns actual datetime
    type(coordinator).last_update_success = PropertyMock(
        return_value=datetime.fromisoformat("2024-02-03T12:00:00")
    )

    return coordinator


@pytest.fixture
async def hass():
    """Create a mock HomeAssistant instance."""
    from homeassistant.core import HomeAssistant

    hass_instance = Mock(spec=HomeAssistant)
    hass_instance.data = {}
    return hass_instance


# Pytest configuration
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line("markers", "asyncio: mark test as an asyncio test")
