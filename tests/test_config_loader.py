"""Tests for entity YAML loading and defaults."""

from custom_components.srne_inverter.config_loader import _apply_entity_defaults


def test_apply_entity_defaults_merges_sensor_state_class_top_level():
    """Sensor defaults must flatten onto each sensor for HA statistics."""
    config = {
        "defaults": {
            "sensor": {"state_class": "measurement", "enabled_by_default": True},
            "switch": {"optimistic": False},
        },
        "sensors": [{"entity_id": "grid_power", "name": "Grid Power"}],
        "switches": [{"entity_id": "ac", "name": "AC"}],
    }
    _apply_entity_defaults(config)

    sensor = config["sensors"][0]
    assert sensor["state_class"] == "measurement"
    assert sensor["enabled_by_default"] is True
    assert "switch" not in sensor
    assert "sensor" not in sensor

    switch = config["switches"][0]
    assert switch["optimistic"] is False
    assert "sensor" not in switch


def test_apply_entity_defaults_does_not_override_explicit_keys():
    config = {
        "defaults": {"sensor": {"state_class": "measurement"}},
        "sensors": [
            {"entity_id": "x", "name": "X", "state_class": "total_increasing"}
        ],
    }
    _apply_entity_defaults(config)
    assert config["sensors"][0]["state_class"] == "total_increasing"


def test_apply_entity_defaults_skips_state_class_for_value_mapping():
    config = {
        "_register_by_name": {
            "charge_state": {"data_type": "uint16"},
        },
        "defaults": {"sensor": {"state_class": "measurement"}},
        "sensors": [
            {
                "entity_id": "charge_state",
                "name": "Charge State",
                "value_mapping": {0: "Off"},
            }
        ],
    }
    _apply_entity_defaults(config)
    assert "state_class" not in config["sensors"][0]


def test_apply_entity_defaults_skips_state_class_for_string_register():
    config = {
        "_register_by_name": {
            "product_sn_str": {"data_type": "string_low_bytes"},
        },
        "defaults": {"sensor": {"state_class": "measurement"}},
        "sensors": [
            {
                "entity_id": "product_serial_number",
                "name": "SN",
                "register": "product_sn_str",
            }
        ],
    }
    _apply_entity_defaults(config)
    assert "state_class" not in config["sensors"][0]


def test_apply_entity_defaults_skips_state_class_for_timestamp_device_class():
    config = {
        "_register_by_name": {},
        "defaults": {"sensor": {"state_class": "measurement"}},
        "sensors": [
            {
                "entity_id": "last_update",
                "name": "Last Update",
                "device_class": "timestamp",
            }
        ],
    }
    _apply_entity_defaults(config)
    assert "state_class" not in config["sensors"][0]
