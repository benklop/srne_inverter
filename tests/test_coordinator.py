"""Tests for SRNEDataUpdateCoordinator (current constructor and helpers)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.srne_inverter.coordinator import SRNEDataUpdateCoordinator
from custom_components.srne_inverter.domain.helpers.transformations import (
    convert_to_signed_int16,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_config_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"address": "AA:BB:CC:DD:EE:FF"}
    entry.options = {"update_interval": 60}
    return entry


def test_coordinator_requires_device_config(mock_hass, mock_config_entry):
    coord = SRNEDataUpdateCoordinator(
        mock_hass,
        mock_config_entry,
        device_config={"registers": {}, "device": {}},
    )
    assert coord._address == "AA:BB:CC:DD:EE:FF"


async def test_async_read_register_uses_protocol_and_ensure_connected(
    mock_hass, mock_config_entry
):
    """Regression: must not call nonexistent connect() / read_holding_registers()."""
    transport = MagicMock()
    transport.is_connected = True
    transport.send = AsyncMock(return_value=b"\x01\x03\x02\x12\x34\x00\x00")

    cm = MagicMock()
    cm.ensure_connected = AsyncMock(return_value=True)

    protocol = MagicMock()
    protocol.build_read_command = MagicMock(return_value=b"request-bytes")
    protocol.decode_response = MagicMock(return_value={0: 0x1234})

    coord = SRNEDataUpdateCoordinator(
        mock_hass,
        mock_config_entry,
        device_config={"registers": {}, "device": {}},
        transport=transport,
        connection_manager=cm,
        protocol=protocol,
    )

    value = await coord.async_read_register(0x0100)
    assert value == 0x1234
    cm.ensure_connected.assert_awaited_once_with("AA:BB:CC:DD:EE:FF")
    protocol.build_read_command.assert_called_once_with(start_address=0x0100, count=1)
    transport.send.assert_awaited_once()


def test_signed_int16_matches_domain_helper():
    assert convert_to_signed_int16(0) == 0
    assert convert_to_signed_int16(32767) == 32767
    assert convert_to_signed_int16(65535) == -1
