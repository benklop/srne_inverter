"""ConfigurableNumber write verification reads the device, not stale coordinator.data."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry

from custom_components.srne_inverter.entities.configurable_number import ConfigurableNumber


def _minimal_entry(battery_voltage: int | None = None) -> ConfigEntry:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "e1"
    data = {"address": "192.168.1.1"}
    if battery_voltage is not None:
        data["battery_voltage"] = battery_voltage
    entry.data = data
    entry.options = {}
    return entry


@pytest.mark.asyncio
async def test_verify_write_uses_fresh_register_read_not_coordinator_cache():
    coordinator = MagicMock()
    coordinator.data = {
        "discharge_cutoff_soc": 10,
        "connected": True,
    }
    coordinator.async_write_register = AsyncMock(
        return_value=MagicMock(success=True, error=None)
    )
    coordinator.async_read_register = AsyncMock(return_value=25)

    reg = {
        "address": 0xE00F,
        "_address_int": 0xE00F,
        "type": "read_write",
        "scaling": 1.0,
        "data_type": "uint16",
    }
    device_config = {"_register_by_name": {"discharge_cutoff_soc": reg}}
    entity_cfg = {
        "entity_id": "discharge_cutoff_soc",
        "register": "discharge_cutoff_soc",
        "name": "Discharge Cutoff SOC",
        "min": 0,
        "max": 100,
        "step": 1,
        "scale": 1.0,
        "optimistic": False,
    }

    ent = ConfigurableNumber(coordinator, _minimal_entry(), entity_cfg, device_config)
    await ent.async_set_native_value(25.0)

    coordinator.async_read_register.assert_awaited()
    assert coordinator.async_read_register.await_args[0][0] == 0xE00F


@pytest.mark.asyncio
async def test_verify_write_fails_when_readback_mismatches():
    coordinator = MagicMock()
    coordinator.data = {"discharge_cutoff_soc": 25, "connected": True}
    coordinator.async_write_register = AsyncMock(
        return_value=MagicMock(success=True, error=None)
    )
    coordinator.async_read_register = AsyncMock(return_value=99)

    reg = {
        "address": 0xE00F,
        "_address_int": 0xE00F,
        "type": "read_write",
        "scaling": 1.0,
        "data_type": "uint16",
    }
    device_config = {"_register_by_name": {"discharge_cutoff_soc": reg}}
    entity_cfg = {
        "entity_id": "discharge_cutoff_soc",
        "register": "discharge_cutoff_soc",
        "name": "Discharge Cutoff SOC",
        "min": 0,
        "max": 100,
        "step": 1,
        "scale": 1.0,
        "optimistic": False,
    }

    ent = ConfigurableNumber(coordinator, _minimal_entry(), entity_cfg, device_config)
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError, match="Write verification failed"):
        await ent.async_set_native_value(25.0)


def test_per_12v_register_scales_display_to_pack_voltage():
    """Coordinator holds per-12V volts; UI shows pack volts using battery_voltage."""
    coordinator = MagicMock()
    coordinator.data = {"battery_overvoltage": 15.0, "connected": True}

    reg = {
        "address": 0xE005,
        "_address_int": 0xE005,
        "type": "read_write",
        "scaling": 0.1,
        "data_type": "uint16",
        "per_12v_reference": True,
    }
    device_config = {"_register_by_name": {"battery_overvoltage": reg}}
    entity_cfg = {
        "entity_id": "battery_overvoltage",
        "register": "battery_overvoltage",
        "name": "Battery Overvoltage Protection",
        "min": 9.0,
        "max": 15.5,
        "step": 0.1,
        "optimistic": False,
    }

    ent = ConfigurableNumber(
        coordinator, _minimal_entry(48), entity_cfg, device_config
    )
    assert ent.native_value == 60.0
    assert ent.native_min_value == 36.0
    assert ent.native_max_value == 62.0
    assert ent._encode_value(60.0) == 150


def test_per_12v_register_unchanged_when_battery_voltage_is_12():
    coordinator = MagicMock()
    coordinator.data = {"battery_low_voltage": 11.5, "connected": True}

    reg = {
        "address": 0xE00D,
        "_address_int": 0xE00D,
        "type": "read_write",
        "scaling": 0.1,
        "data_type": "uint16",
        "per_12v_reference": True,
    }
    device_config = {"_register_by_name": {"battery_low_voltage": reg}}
    entity_cfg = {
        "entity_id": "battery_low_voltage",
        "register": "battery_low_voltage",
        "name": "Battery Low Voltage Cutoff",
        "min": 9.0,
        "max": 15.5,
        "step": 0.1,
        "optimistic": False,
    }

    ent = ConfigurableNumber(
        coordinator, _minimal_entry(12), entity_cfg, device_config
    )
    assert ent.native_value == 11.5
    assert ent._encode_value(11.5) == 115
