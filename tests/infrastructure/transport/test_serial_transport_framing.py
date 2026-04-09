import asyncio
import struct

import pytest

from custom_components.srne_inverter.infrastructure.transport.serial_transport import (
    _read_one_modbus_rtu_frame,
)
from custom_components.srne_inverter.infrastructure.protocol.modbus_crc16 import ModbusCRC16


@pytest.mark.asyncio
async def test_read_one_frame_read_holding_with_leading_noise():
    reader = asyncio.StreamReader()
    crc = ModbusCRC16()

    # Build a valid 0x03 response for slave 0x01, 2 registers (byte_count=4)
    pdu = bytes([0x01, 0x03, 0x04, 0x00, 0x63, 0x02, 0x14])
    frame = pdu + struct.pack("<H", crc.calculate(pdu))

    # Feed noise + a frame from another slave + our valid frame
    other_pdu = bytes([0x02, 0x03, 0x02, 0x00, 0x01])
    other_frame = other_pdu + struct.pack("<H", crc.calculate(other_pdu))
    reader.feed_data(b"\xff\xfe" + other_frame + frame)
    reader.feed_eof()

    deadline = asyncio.get_running_loop().time() + 1.0
    got = await _read_one_modbus_rtu_frame(reader, expected_slave=0x01, deadline=deadline)
    assert got == frame


@pytest.mark.asyncio
async def test_read_one_frame_exception_response():
    reader = asyncio.StreamReader()
    crc = ModbusCRC16()

    pdu = bytes([0x01, 0x83, 0x02])
    frame = pdu + struct.pack("<H", crc.calculate(pdu))
    reader.feed_data(b"\x00\x00" + frame)
    reader.feed_eof()

    deadline = asyncio.get_running_loop().time() + 1.0
    got = await _read_one_modbus_rtu_frame(reader, expected_slave=0x01, deadline=deadline)
    assert got == frame


@pytest.mark.asyncio
async def test_read_one_frame_write_single_fixed_length():
    reader = asyncio.StreamReader()
    crc = ModbusCRC16()

    pdu = bytes([0x01, 0x06, 0x01, 0x00, 0x01, 0x2C])
    frame = pdu + struct.pack("<H", crc.calculate(pdu))
    reader.feed_data(frame)
    reader.feed_eof()

    deadline = asyncio.get_running_loop().time() + 1.0
    got = await _read_one_modbus_rtu_frame(reader, expected_slave=0x01, deadline=deadline)
    assert got == frame

