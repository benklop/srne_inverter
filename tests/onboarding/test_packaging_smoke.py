"""Repository smoke tests: onboarding files and translation keys exist.

These guard against accidental deletion of onboarding assets; behavior is
covered in test_onboarding_state_machine.py and config flow tests.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = REPO_ROOT / "custom_components" / "srne_inverter"
ONBOARDING_PKG = INTEGRATION / "onboarding"
CONFIG_FLOW_ONBOARDING = INTEGRATION / "config_flow" / "onboarding.py"
TRANSLATIONS = INTEGRATION / "translations" / "en.json"


def test_onboarding_package_layout():
    assert ONBOARDING_PKG.is_dir()
    assert (ONBOARDING_PKG / "__init__.py").is_file()
    assert (ONBOARDING_PKG / "state_machine.py").is_file()
    assert (ONBOARDING_PKG / "context.py").is_file()
    assert (ONBOARDING_PKG / "detection.py").is_file()
    assert CONFIG_FLOW_ONBOARDING.is_file()
    content = CONFIG_FLOW_ONBOARDING.read_text(encoding="utf-8")
    assert "OnboardingContext" in content
    assert "OnboardingStateMachine" in content
    assert "FeatureDetector" in content
    assert "class SRNEConfigFlow" in content


def test_presets_exported():
    from custom_components.srne_inverter.config_flow import CONFIGURATION_PRESETS

    assert isinstance(CONFIGURATION_PRESETS, dict)
    assert len(CONFIGURATION_PRESETS) >= 1
    assert "off_grid_solar" in CONFIGURATION_PRESETS


def test_translations_onboarding_steps_and_progress():
    data = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    steps = data["config"]["step"]
    for key in (
        "welcome",
        "user_level",
        "hardware_detection",
        "detection_review",
    ):
        assert key in steps
    assert "detect_hardware" in data["config"]["progress"]
    assert "detection_failed" in data["config"]["error"]
