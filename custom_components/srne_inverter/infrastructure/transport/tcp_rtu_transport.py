"""TCP socket transport for Modbus RTU frames.

This transport connects to a host:port TCP socket and exchanges raw Modbus RTU
ADUs (including CRC-16) over the TCP stream.

Note: This is *not* Modbus TCP (no MBAP header). Some Wi-Fi/RS-485 gateways
expose a plain TCP socket that forwards RTU frames unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ...const import (
    DEFAULT_TCP_PORT,
    FUNC_READ_HOLDING,
    FUNC_WRITE_MULTIPLE,
    FUNC_WRITE_SINGLE,
    MODBUS_RESPONSE_TIMEOUT,
)
from ...domain.interfaces import ITransport
from ..decorators import handle_transport_errors

_LOGGER = logging.getLogger(__name__)


def _expected_rtu_response_length(prefix: bytes) -> Optional[int]:
    """Return expected RTU response length, or None if unknown yet.

    prefix is the bytes we have already read (starting at slave id).
    """
    if len(prefix) < 2:
        return None
    function_code = prefix[1]

    # Exception response: [slave][fc|0x80][exception][crc_lo][crc_hi]
    if function_code & 0x80:
        return 5

    # Read holding registers: [slave][0x03][byte_count][data...][crc]
    if function_code == FUNC_READ_HOLDING:
        if len(prefix) < 3:
            return None
        byte_count = prefix[2]
        return 3 + byte_count + 2

    # Write single/multiple responses are fixed 8 bytes.
    if function_code in (FUNC_WRITE_SINGLE, FUNC_WRITE_MULTIPLE):
        return 8

    # Unknown function code; fall back to read-until-timeout behavior.
    return None


class TcpRtuTransport(ITransport):
    """TCP transport for Modbus RTU over a socket."""

    def __init__(self, hass=None, timing_collector=None, port: int = DEFAULT_TCP_PORT):
        del hass
        self._timing_collector = timing_collector
        self._host: Optional[str] = None
        self._port: int = int(port)
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected: bool = False
        self._lock = asyncio.Lock()

    async def connect(self, address: str, disconnected_callback=None) -> bool:
        del disconnected_callback
        self._host = address
        self._connected = False

        try:
            self._reader, self._writer = await asyncio.open_connection(
                host=address, port=self._port
            )
            self._connected = True
            _LOGGER.info("TCP RTU transport connected to %s:%d", address, self._port)
            return True
        except Exception as err:
            _LOGGER.error("Failed to connect TCP RTU %s:%d: %s", address, self._port, err)
            self._reader = None
            self._writer = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as err:
                _LOGGER.debug("TCP RTU close warning for %s:%d: %s", self._host, self._port, err)

        self._reader = None
        self._writer = None
        self._connected = False

    @handle_transport_errors("TCP RTU send", reraise=True)
    async def send(self, data: bytes, timeout: float = MODBUS_RESPONSE_TIMEOUT) -> bytes:
        if not data:
            raise ValueError("TCP RTU send requires non-empty data")
        if not self._connected or self._reader is None or self._writer is None:
            raise RuntimeError("TCP RTU transport not connected")

        # Ensure requests are serialized on a single TCP stream.
        async with self._lock:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=timeout)

            # Read a single RTU response frame.
            buf = bytearray()

            async def _read_exactly(n: int) -> bytes:
                return await asyncio.wait_for(self._reader.readexactly(n), timeout=timeout)

            # First, get enough bytes to determine expected length.
            buf += await _read_exactly(2)  # slave + function

            # If we can determine exact length, do so; otherwise read a bit and return whatever we got.
            expected = _expected_rtu_response_length(bytes(buf))
            if expected is None:
                # Try to read one more byte (often byte count) then re-evaluate.
                try:
                    buf += await _read_exactly(1)
                    expected = _expected_rtu_response_length(bytes(buf))
                except asyncio.IncompleteReadError:
                    expected = None

            if expected is not None and len(buf) < expected:
                buf += await _read_exactly(expected - len(buf))
                raw = bytes(buf)
                _LOGGER.debug("TCP RTU RX from %s:%d: %s", self._host, self._port, raw.hex())
                return raw

            # Unknown length: read until timeout or EOF, but cap to a sane size.
            cap = 512
            while len(buf) < cap:
                try:
                    chunk = await asyncio.wait_for(self._reader.read(256), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
                maybe = _expected_rtu_response_length(bytes(buf))
                if maybe is not None and len(buf) >= maybe:
                    buf = buf[:maybe]
                    break

            if not buf:
                raise asyncio.TimeoutError("No response received")

            raw = bytes(buf)
            _LOGGER.debug("TCP RTU RX from %s:%d: %s", self._host, self._port, raw.hex())
            return raw

    @property
    def is_connected(self) -> bool:
        return self._connected and self._writer is not None and not self._writer.is_closing()

