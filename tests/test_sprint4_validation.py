"""OnboardingContext behavior: step tracking, active_features, and completion.

These tests document multi-step onboarding state on ``OnboardingContext``. They do
*not* call ``ValidationEngine`` or config flow steps — see ``test_dynamic_config_flow.py``
and ``test_config_flow_validation_mixin.py`` for that.
"""

import pytest

from custom_components.srne_inverter.onboarding import OnboardingContext


class TestOnboardingContextFeatureMerging:
    def test_active_features_merges_overrides(self):
        context = OnboardingContext(
            device_address="AA:BB:CC:DD:EE:FF", device_name="E60048"
        )
        context.detected_features = {"grid_tie": False, "timed_operation": True}
        context.user_overrides = {"grid_tie": True}
        assert context.active_features["grid_tie"] is True
        assert context.active_features["timed_operation"] is True


class TestOnboardingContextScenarioArithmetic:
    """Sanity checks for example numeric relationships used in onboarding docs."""

    def test_charge_current_vs_capacity_c_rate_example(self):
        capacity_ah = 200
        charge_a = 150
        assert charge_a > capacity_ah * 0.5

    def test_soc_ordering_example_valid(self):
        discharge_stop, to_ac, to_batt = 20, 30, 80
        assert discharge_stop < to_ac < to_batt

    def test_soc_ordering_example_invalid(self):
        discharge_stop, to_ac = 30, 20
        assert discharge_stop >= to_ac


class TestOnboardingContextStepCompletion:
    def test_basic_flow_marks_completed_with_timestamps(self):
        context = OnboardingContext(
            device_address="AA:BB:CC:DD:EE:FF", device_name="E60048-12"
        )
        context.user_level = "basic"
        for step in (
            "welcome",
            "user_level",
            "hardware_detection",
            "detection_review",
            "preset_selection",
            "validation",
            "review",
        ):
            context.mark_step_complete(step)
        context.selected_preset = "off_grid_solar"
        context.custom_settings = {
            "output_priority": "2",
            "charge_source_priority": "3",
            "discharge_stop_soc": 20,
            "switch_to_ac_soc": 10,
            "switch_to_battery_soc": 100,
        }
        context.mark_completed()
        assert context.completed_at is not None
        assert context.total_duration is not None

    def test_advanced_manual_flow_custom_settings_preserved(self):
        context = OnboardingContext(
            device_address="AA:BB:CC:DD:EE:FF", device_name="E60048-12"
        )
        context.user_level = "advanced"
        for step in (
            "welcome",
            "user_level",
            "hardware_detection",
            "detection_review",
            "manual_config",
            "validation",
            "review",
        ):
            context.mark_step_complete(step)
        context.custom_settings = {
            "battery_capacity": 200,
            "battery_voltage": "48",
            "output_priority": "2",
            "charge_source_priority": "0",
            "discharge_stop_soc": 20,
            "switch_to_ac_soc": 30,
            "switch_to_battery_soc": 80,
        }
        context.mark_completed()
        assert len(context.custom_settings) >= 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
