"""Tests for ConfigFlowValidationMixin (shared config-flow validation helpers)."""

import pytest

from custom_components.srne_inverter.config_flow.base import ConfigFlowValidationMixin


class TestValidateBatterySettings:
    def test_accepts_standard_voltages(self):
        for v in (12, 24, 48):
            ConfigFlowValidationMixin.validate_battery_settings({"battery_voltage": v})

    def test_rejects_nonstandard_voltage(self):
        with pytest.raises(ValueError, match="Battery voltage"):
            ConfigFlowValidationMixin.validate_battery_settings({"battery_voltage": 36})

    def test_discharge_stop_soc_out_of_range(self):
        with pytest.raises(ValueError, match="0-100"):
            ConfigFlowValidationMixin.validate_battery_settings(
                {"discharge_stop_soc": 101}
            )

    def test_switch_to_ac_soc_out_of_range(self):
        with pytest.raises(ValueError, match="0-100"):
            ConfigFlowValidationMixin.validate_battery_settings({"switch_to_ac_soc": -1})

    def test_battery_capacity_non_positive(self):
        with pytest.raises(ValueError, match="positive"):
            ConfigFlowValidationMixin.validate_battery_settings(
                {"battery_capacity_ah": 0}
            )


class TestValidateInverterOutputSettings:
    def test_valid_voltage_and_frequency(self):
        ConfigFlowValidationMixin.validate_inverter_output_settings(
            {"output_voltage": 120, "output_frequency": 60}
        )

    def test_invalid_output_voltage(self):
        with pytest.raises(ValueError, match="Output voltage"):
            ConfigFlowValidationMixin.validate_inverter_output_settings(
                {"output_voltage": 117}
            )

    def test_invalid_frequency(self):
        with pytest.raises(ValueError, match="frequency"):
            ConfigFlowValidationMixin.validate_inverter_output_settings(
                {"output_frequency": 55}
            )


class TestValidateEssentialSettings:
    def test_missing_required_field(self):
        with pytest.raises(ValueError, match="battery_capacity"):
            ConfigFlowValidationMixin.validate_essential_settings(
                {"battery_voltage": 48}
            )

    def test_complete_passes(self):
        ConfigFlowValidationMixin.validate_essential_settings(
            {"battery_voltage": 48, "battery_capacity_ah": 100}
        )
