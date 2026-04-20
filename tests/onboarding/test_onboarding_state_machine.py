"""Behavioral tests for onboarding FSM (not file-layout checks)."""

from custom_components.srne_inverter.onboarding.state_machine import (
    OnboardingState,
    OnboardingStateMachine,
)


def test_initial_state_is_device_scan():
    sm = OnboardingStateMachine()
    assert sm.current_state == OnboardingState.DEVICE_SCAN
    assert sm.history == [OnboardingState.DEVICE_SCAN]


def test_valid_transition_updates_current_and_history():
    sm = OnboardingStateMachine()
    assert sm.transition(OnboardingState.DEVICE_SELECTED) is True
    assert sm.current_state == OnboardingState.DEVICE_SELECTED
    assert sm.history[-2:] == [
        OnboardingState.DEVICE_SCAN,
        OnboardingState.DEVICE_SELECTED,
    ]


def test_invalid_transition_returns_false_and_preserves_state():
    sm = OnboardingStateMachine()
    assert sm.transition(OnboardingState.DETECTION_REVIEW) is False
    assert sm.current_state == OnboardingState.DEVICE_SCAN


def test_welcome_to_user_level_path_used_by_config_flow():
    sm = OnboardingStateMachine()
    assert sm.transition(OnboardingState.DEVICE_SELECTED) is True
    assert sm.transition(OnboardingState.WELCOME) is True
    assert sm.transition(OnboardingState.USER_LEVEL) is True
    assert sm.current_state == OnboardingState.USER_LEVEL


def test_hardware_detection_to_detection_review_path():
    sm = OnboardingStateMachine()
    for step in (
        OnboardingState.DEVICE_SELECTED,
        OnboardingState.WELCOME,
        OnboardingState.USER_LEVEL,
        OnboardingState.HARDWARE_DETECTION,
    ):
        assert sm.transition(step) is True
    assert sm.transition(OnboardingState.DETECTION_REVIEW) is True
    assert sm.current_state == OnboardingState.DETECTION_REVIEW


def test_go_back_restores_previous_state():
    sm = OnboardingStateMachine()
    sm.transition(OnboardingState.DEVICE_SELECTED)
    sm.transition(OnboardingState.WELCOME)
    prev = sm.go_back()
    assert prev == OnboardingState.DEVICE_SELECTED
    assert sm.current_state == OnboardingState.DEVICE_SELECTED


def test_reset_returns_to_device_scan():
    sm = OnboardingStateMachine()
    sm.transition(OnboardingState.DEVICE_SELECTED)
    sm.reset()
    assert sm.current_state == OnboardingState.DEVICE_SCAN
    assert sm.history == [OnboardingState.DEVICE_SCAN]
