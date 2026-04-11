"""Unit tests for serial transport Modbus RTU helpers (pymodbus-backed path)."""

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.srne_inverter.infrastructure.protocol.modbus_crc16 import (
    ModbusCRC16,
)
from custom_components.srne_inverter.infrastructure.transport.serial_transport import (
    SerialTransport,
    _bytes_to_request_pdu,
    _response_to_rtu_bytes,
    _validate_rtu_crc,
)
from pymodbus.pdu.register_message import ReadHoldingRegistersResponse


def _frame_with_crc(pdu: bytes) -> bytes:
    crc = ModbusCRC16()
    return pdu + struct.pack("<H", crc.calculate(pdu))


def test_validate_rtu_crc_accepts_valid_read_request():
    pdu = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x02])
    _validate_rtu_crc(_frame_with_crc(pdu))


def test_validate_rtu_crc_rejects_bad_crc():
    pdu = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x02])
    bad = pdu + b"\x00\x00"
    with pytest.raises(ValueError, match="CRC"):
        _validate_rtu_crc(bad)


def test_bytes_to_request_read_holding():
    pdu = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x02])
    full = _frame_with_crc(pdu)
    req = _bytes_to_request_pdu(full)
    assert req.dev_id == 1
    assert req.function_code == 0x03
    assert req.address == 0x0100
    assert req.count == 2


def test_response_to_rtu_bytes_read_holding():
    r = ReadHoldingRegistersResponse(
        dev_id=1, address=0, count=2, registers=[100, 200], bits=[]
    )
    raw = _response_to_rtu_bytes(r)
    assert raw[0] == 0x01
    assert raw[1] == 0x03
    _validate_rtu_crc(raw)


@pytest.mark.asyncio
async def test_serial_connect_sets_relaxed_inter_frame_time():
    """Avoid pymodbus recv_buffer clears on slow USB chunk delivery (9600 RTU)."""
    mock_ctx = MagicMock()
    mock_client = MagicMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.ctx = mock_ctx

    transport = SerialTransport()
    with patch(
        "custom_components.srne_inverter.infrastructure.transport.serial_transport.AsyncModbusSerialClient",
        return_value=mock_client,
    ):
        ok = await transport.connect("/dev/ttyUSB0")
    assert ok is True
    assert mock_ctx.inter_frame_time == 10**9
