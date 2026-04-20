"""Tests that the YAML-driven entity architecture is in place."""

from pathlib import Path

from custom_components.srne_inverter.entity_factory import EntityFactory
from custom_components.srne_inverter.entities.configurable_base import (
    ConfigurableBaseEntity,
)
from custom_components.srne_inverter.entities.configurable_sensor import (
    ConfigurableSensor,
)
from custom_components.srne_inverter.entities.configurable_switch import (
    ConfigurableSwitch,
)
from custom_components.srne_inverter.entities.configurable_select import (
    ConfigurableSelect,
)


def test_configurable_entities_share_base():
    assert issubclass(ConfigurableSensor, ConfigurableBaseEntity)
    assert issubclass(ConfigurableSwitch, ConfigurableBaseEntity)
    assert issubclass(ConfigurableSelect, ConfigurableBaseEntity)


def test_entity_factory_exposes_creation_api():
    assert hasattr(EntityFactory, "create_entities_from_config")
    assert hasattr(EntityFactory, "create_sensor")


def test_sensor_platform_delegates_to_entity_factory():
    """sensor.py should remain a thin setup shim (factory + learned-timeout helpers)."""
    sensor_file = Path(__file__).parent.parent / "custom_components/srne_inverter/sensor.py"
    text = sensor_file.read_text(encoding="utf-8")
    assert "async_setup_entry" in text
    assert "EntityFactory.create_entities_from_config" in text
    assert "create_learned_timeout_sensors" in text
