"""Tests for hardware feature detection (register probe + model fallback)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.srne_inverter.onboarding.detection import (
    FEATURE_TEST_REGISTERS,
    FeatureDetector,
)


@pytest.mark.asyncio
async def test_detect_all_features_true_when_register_reads_succeed():
    coordinator = MagicMock()
    coordinator.async_read_register = AsyncMock(return_value=0x0001)

    detector = FeatureDetector(coordinator)
    results = await detector.detect_all_features()

    assert len(results) == len(FEATURE_TEST_REGISTERS)
    assert all(results.values()) is True
    assert coordinator.async_read_register.await_count == len(FEATURE_TEST_REGISTERS)


@pytest.mark.asyncio
async def test_detect_all_features_false_for_dash_pattern():
    coordinator = MagicMock()
    coordinator.async_read_register = AsyncMock(return_value=0x2D2D)

    detector = FeatureDetector(coordinator)
    results = await detector.detect_all_features()

    assert not any(results.values())


@pytest.mark.asyncio
async def test_detect_all_features_false_when_read_returns_none():
    coordinator = MagicMock()
    coordinator.async_read_register = AsyncMock(return_value=None)

    detector = FeatureDetector(coordinator)
    results = await detector.detect_all_features()

    assert not any(results.values())


def test_infer_features_grid_tie_from_model_suffix():
    detector = FeatureDetector(None)
    inferred = detector.infer_features_from_model("E60G48")
    assert inferred["grid_tie"] is True


def test_infer_features_split_phase_from_m_suffix():
    detector = FeatureDetector(None)
    inferred = detector.infer_features_from_model("E60M48")
    assert inferred["split_phase"] is True


def test_infer_features_three_phase_from_t_suffix():
    detector = FeatureDetector(None)
    inferred = detector.infer_features_from_model("E60T48")
    assert inferred["three_phase"] is True
