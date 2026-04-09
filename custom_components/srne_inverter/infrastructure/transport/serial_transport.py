"""USB serial transport implementation for SRNE inverter.

This module implements the ITransport interface for Modbus RTU over
USB serial adapters (for example /dev/ttyUSB0).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Any

try:
    import serial_asyncio_fast as serial_asyncio
except ImportError:  # Fallback for environments with standard pyserial-asyncio
    import serial_asyncio

from ...const import (
    BAUDRATE,
    BYTESIZE,
    PARITY,
    STOPBITS,
    MODBUS_RESPONSE_TIMEOUT,
)
from ...domain.interfaces import ITransport
from ..decorators import handle_transport_errors

_LOGGER = logging.getLogger(__name__)


def _get_underlying_serial(writer: asyncio.StreamWriter) -> Any | None:
    """Best-effort access to the underlying pyserial object."""
    transport = getattr(writer, "transport", None)
    if transport is None:
        return None
    serial_obj = getattr(transport, "serial", None)
    if serial_obj is not None:
        return serial_obj
    try:
        return transport.get_extra_info("serial")
    except Exception:
        return None


async def _readexactly_with_timeout(
    reader: asyncio.StreamReader, n: int, *, deadline: float
) -> bytes:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise asyncio.TimeoutError("Serial read timed out")
    return await asyncio.wait_for(reader.readexactly(n), timeout=remaining)


async def _read_one_modbus_rtu_frame(
    reader: asyncio.StreamReader,
    *,
    expected_slave: int,
    deadline: float,
) -> bytes:
    """Read exactly one Modbus RTU response frame from a byte stream.

    This is deterministic framing based on Modbus RTU structure:
    - [slave][func][...][crc_lo][crc_hi]
    - For 0x03: [slave][0x03][byte_count][data...][crc]
    - For exception: [slave][func|0x80][exc_code][crc]
    - For 0x06/0x10: fixed-length 8 bytes total

    If the stream contains other traffic (other slave IDs or noise), bytes are
    dropped until a candidate frame begins with expected_slave.
    """
    # Scan until we see the expected slave address AND a plausible function code.
    # The slave byte may appear inside other frames/noise, so we must validate fc too.
    pending: bytes | None = None
    while True:
        if pending is not None:
            b = pending
            pending = None
        else:
            b = await _readexactly_with_timeout(reader, 1, deadline=deadline)

        if b[0] != expected_slave:
            continue

        func = await _readexactly_with_timeout(reader, 1, deadline=deadline)
        fc = func[0]

        is_exception = bool(fc & 0x80)
        base_fc = fc & 0x7F
        if base_fc not in (0x03, 0x06, 0x10):
            # Not a function we understand for this integration; treat as noise.
            # Re-process this byte as a potential slave start.
            pending = func
            continue

        slave = b
        break

    if fc & 0x80:
        rest = await _readexactly_with_timeout(reader, 3, deadline=deadline)
        return slave + func + rest

    if fc == 0x03:
        byte_count_b = await _readexactly_with_timeout(reader, 1, deadline=deadline)
        byte_count = byte_count_b[0]
        rest = await _readexactly_with_timeout(reader, byte_count + 2, deadline=deadline)
        return slave + func + byte_count_b + rest

    if fc in (0x06, 0x10):
        rest = await _readexactly_with_timeout(reader, 6, deadline=deadline)
        return slave + func + rest

    # Unknown function code: read whatever arrives for a short period,
    # but keep it bounded so we don't glue multiple frames.
    chunks: list[bytes] = [slave, func]
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            chunk = await asyncio.wait_for(reader.read(256), timeout=min(remaining, 0.01))
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


class SerialTransport(ITransport):
    """Serial transport for SRNE inverter communication."""

    def __init__(self, hass=None, timing_collector=None):
        """Initialize serial transport.

        Args:
            hass: Kept for constructor compatibility with DI container.
            timing_collector: Optional timing collector (currently unused).
        """
        self._hass = hass
        self._timing_collector = timing_collector
        self._port: Optional[str] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
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

        try:
            self._reader, self._writer = (
                await serial_asyncio.open_serial_connection(
                    url=address,
                    baudrate=BAUDRATE,
                    bytesize=BYTESIZE,
                    parity=PARITY,
                    stopbits=STOPBITS,
                )
            )
            self._connected = True
            _LOGGER.info("Serial transport connected to %s", address)
            return True
        except Exception as err:
            _LOGGER.error("Failed to connect serial port %s: %s", address, err)
            self._reader = None
            self._writer = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect serial transport."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as err:
                _LOGGER.debug(
                    "Serial close warning for %s: %s", self._port, err
                )

        self._reader = None
        self._writer = None
        self._connected = False

    @handle_transport_errors("Serial send", reraise=True)
    async def send(
        self, data: bytes, timeout: float = MODBUS_RESPONSE_TIMEOUT
    ) -> bytes:
        """Send request and read a Modbus RTU response.

        USB serial Modbus RTU should be framed deterministically; returning
        arbitrary buffered bytes (gap-based) can concatenate multiple frames and
        trigger CRC mismatches in the protocol layer.
        """
        if not self._connected or self._writer is None or self._reader is None:
            raise RuntimeError("Serial transport not connected")

        # Flush any stale buffered data before issuing a request
        serial_obj = _get_underlying_serial(self._writer)
        if serial_obj is not None:
            try:
                serial_obj.reset_input_buffer()
            except Exception:
                # Best-effort only; not all transports expose this
                pass

        deadline = asyncio.get_running_loop().time() + timeout

        self._writer.write(data)
        await self._writer.drain()

        expected_slave = data[0] if data else 0x01
        response = await _read_one_modbus_rtu_frame(
            self._reader, expected_slave=expected_slave, deadline=deadline
        )
        _LOGGER.debug("Serial RX from %s: %s", self._port, response.hex())
        return response

    @property
    def is_connected(self) -> bool:
        """Return connection state."""
        return self._connected
