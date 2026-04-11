"""USB serial transport implementation for SRNE inverter.

Modbus RTU framing, timing, and I/O are delegated to pymodbus
(:class:`pymodbus.client.AsyncModbusSerialClient`). This class only adapts the
integration's raw-frame :class:`~...domain.interfaces.ITransport` contract to
that client.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusIOException
from pymodbus.framer import FramerType
from pymodbus.framer.rtu import FramerRTU
from pymodbus.pdu import DecodePDU, ModbusPDU
from pymodbus.pdu.register_message import (
    ReadHoldingRegistersRequest,
    WriteMultipleRegistersRequest,
    WriteSingleRegisterRequest,
)

from ...const import (
    BAUDRATE,
    BYTESIZE,
    FUNC_READ_HOLDING,
    FUNC_WRITE_MULTIPLE,
    FUNC_WRITE_SINGLE,
    PARITY,
    STOPBITS,
    MODBUS_RESPONSE_TIMEOUT,
)
from ...domain.interfaces import ITransport
from ..decorators import handle_transport_errors

_LOGGER = logging.getLogger(__name__)

# Client-side RTU framer (matches pymodbus AsyncModbusSerialClient defaults).
_RTU_FRAMER = FramerRTU(DecodePDU(False))


def _validate_rtu_crc(data: bytes) -> None:
    if len(data) < 4:
        raise ValueError(f"Modbus RTU frame too short: {len(data)} bytes")
    check = int.from_bytes(data[-2:], "big")
    if not FramerRTU.check_CRC(data[:-2], check):
        raise ValueError("Modbus RTU CRC mismatch on request")


def _bytes_to_request_pdu(data: bytes) -> ModbusPDU:
    """Parse a full Modbus RTU request (including CRC) into a pymodbus request PDU."""
    _validate_rtu_crc(data)
    slave = data[0]
    fc = data[1]
    body = data[2:-2]

    if fc == FUNC_READ_HOLDING:
        if len(body) != 4:
            raise ValueError("Read holding registers request must be 8 bytes total")
        addr, count = struct.unpack(">HH", body)
        return ReadHoldingRegistersRequest(
            address=addr, count=count, dev_id=slave
        )

    if fc == FUNC_WRITE_SINGLE:
        if len(body) != 4:
            raise ValueError("Write single register request must be 8 bytes total")
        addr, value = struct.unpack(">HH", body)
        return WriteSingleRegisterRequest(
            address=addr, registers=[value], dev_id=slave
        )

    if fc == FUNC_WRITE_MULTIPLE:
        if len(body) < 5:
            raise ValueError("Write multiple registers request too short")
        addr, qty = struct.unpack(">HH", body[:4])
        byte_count = body[4]
        reg_bytes = body[5 : 5 + byte_count]
        if len(reg_bytes) != byte_count or byte_count != 2 * qty:
            raise ValueError("Write multiple registers byte count mismatch")
        registers = list(struct.unpack(f">{qty}H", reg_bytes))
        return WriteMultipleRegistersRequest(
            address=addr, registers=registers, dev_id=slave
        )

    raise ValueError(f"Unsupported Modbus function code for serial: 0x{fc:02X}")


def _response_to_rtu_bytes(response: ModbusPDU) -> bytes:
    """Serialize a pymodbus response PDU to raw Modbus RTU (for existing protocol decode)."""
    return _RTU_FRAMER.buildFrame(response)


class SerialTransport(ITransport):
    """Serial transport for SRNE inverter communication (pymodbus RTU client)."""

    def __init__(self, hass=None, timing_collector=None):
        """Initialize serial transport.

        Args:
            hass: Kept for constructor compatibility with DI container.
            timing_collector: Optional timing collector (unused for serial).
        """
        self._hass = hass
        self._timing_collector = timing_collector
        self._port: Optional[str] = None
        self._client: Optional[AsyncModbusSerialClient] = None
        self._connected = False

    async def connect(self, address: str, disconnected_callback=None) -> bool:
        """Connect to serial device path.

        Args:
            address: Serial device path (for example /dev/ttyUSB0)
            disconnected_callback: Unused for serial transport

        Returns:
            True if connected, False otherwise
        """
        del disconnected_callback

        self._port = address
        self._connected = False
        self._client = AsyncModbusSerialClient(
            address,
            framer=FramerType.RTU,
            baudrate=BAUDRATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=MODBUS_RESPONSE_TIMEOUT,
            retries=0,
            reconnect_delay=0.0,
            reconnect_delay_max=0.0,
        )

        try:
            ok = await self._client.connect()
            if not ok:
                _LOGGER.error("Failed to connect serial port %s", address)
                self._client.close()
                self._client = None
                return False
            # Pymodbus clears recv_buffer when the gap between incoming read()
            # chunks exceeds 3.5 character times. At 9600 baud that is only a few
            # milliseconds; USB serial often delivers one RTU frame across
            # multiple chunks with larger scheduling gaps, which truncates the
            # buffer and produces ModbusIOException timeouts even though the
            # bytes arrive. Pymodbus already uses ~1s for baud rates above 38k;
            # apply the same threshold here so frames can assemble reliably.
            self._client.ctx.inter_frame_time = 10**9
            self._connected = True
            _LOGGER.info("Serial transport connected to %s", address)
            return True
        except Exception as err:
            _LOGGER.error("Failed to connect serial port %s: %s", address, err)
            if self._client is not None:
                self._client.close()
            self._client = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect serial transport."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception as err:
                _LOGGER.debug("Serial close warning for %s: %s", self._port, err)

        self._client = None
        self._connected = False

    @handle_transport_errors("Serial send", reraise=True)
    async def send(
        self, data: bytes, timeout: float = MODBUS_RESPONSE_TIMEOUT
    ) -> bytes:
        """Send a Modbus RTU request and return the raw RTU response."""
        if not self._connected or self._client is None:
            raise RuntimeError("Serial transport not connected")

        request = _bytes_to_request_pdu(data)
        self._client.ctx.comm_params.timeout_connect = timeout

        try:
            response = await self._client.execute(False, request)
        except ModbusIOException as err:
            raise asyncio.TimeoutError(str(err)) from err

        raw = _response_to_rtu_bytes(response)
        _LOGGER.debug("Serial RX from %s: %s", self._port, raw.hex())
        return raw

    @property
    def is_connected(self) -> bool:
        """Return connection state."""
        return self._connected and self._client is not None and self._client.connected
