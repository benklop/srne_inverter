"""TCP socket transport for Modbus RTU frames.

This transport connects to a host:port TCP socket and exchanges raw Modbus RTU
ADUs (including CRC-16) over the TCP stream.

Note: This is *not* Modbus TCP (no MBAP header). Some Wi-Fi/RS-485 gateways
expose a plain TCP socket that forwards RTU frames unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

from ...const import (
    DEFAULT_TCP_PORT,
    FUNC_READ_HOLDING,
    FUNC_WRITE_MULTIPLE,
    FUNC_WRITE_SINGLE,
    MODBUS_RESPONSE_TIMEOUT,
)
from ...domain.interfaces import ITransport
from ..protocol.modbus_crc16 import ModbusCRC16
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
        self._rxbuf = bytearray()
        self._crc = ModbusCRC16()

    async def _drain_rx(self) -> None:
        """Drain any pending bytes after connect to start from clean framing."""
        if self._reader is None:
            return
        drained = 0
        while True:
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=0.05)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            drained += len(chunk)
        if drained and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("TCP RTU drained %d stale byte(s) on connect", drained)

    def _crc_valid(self, frame: bytes) -> bool:
        if len(frame) < 5:
            return False
        received = struct.unpack("<H", frame[-2:])[0]
        return received == self._crc.calculate(frame[:-2])

    def _expected_from_request(self, request: bytes) -> Optional[int]:
        """Compute expected RTU response length for request (if possible)."""
        if len(request) < 2:
            return None
        fc = request[1]
        if fc == FUNC_READ_HOLDING:
            if len(request) < 6:
                return None
            reg_count = struct.unpack(">H", request[4:6])[0]
            if not 1 <= reg_count <= 125:
                return None
            return 5 + (2 * reg_count)  # slave+fc+bytecount + data + crc
        if fc in (FUNC_WRITE_SINGLE, FUNC_WRITE_MULTIPLE):
            return 8
        return None

    def _extract_one_frame(self, request: bytes) -> Optional[bytes]:
        """Extract a single valid RTU response from internal buffer.

        Uses request as a hint to determine expected frame length and to resync
        if the TCP stream delivered extra bytes.
        """
        if not self._rxbuf:
            return None

        slave = request[0] if request else None
        expected = self._expected_from_request(request)

        # Scan for a CRC-valid frame in a bounded window.
        # We prefer the expected length, but fall back to RTU heuristic if unknown.
        max_scan = min(64, len(self._rxbuf))
        for off in range(0, max_scan):
            if slave is not None and self._rxbuf[off] != slave:
                continue

            # Try expected-length candidate first.
            if expected is not None and off + expected <= len(self._rxbuf):
                cand = bytes(self._rxbuf[off : off + expected])
                if self._crc_valid(cand):
                    del self._rxbuf[: off + expected]
                    return cand

            # Heuristic: attempt parse based on what bytes we have.
            if off + 3 > len(self._rxbuf):
                continue
            prefix = bytes(self._rxbuf[off : off + 3])
            maybe_len = _expected_rtu_response_length(prefix)
            if maybe_len is None:
                continue
            if off + maybe_len <= len(self._rxbuf):
                cand = bytes(self._rxbuf[off : off + maybe_len])
                if self._crc_valid(cand):
                    del self._rxbuf[: off + maybe_len]
                    return cand

        return None

    async def connect(self, address: str, disconnected_callback=None) -> bool:
        del disconnected_callback
        self._host = address
        self._connected = False

        try:
            self._reader, self._writer = await asyncio.open_connection(
                host=address, port=self._port
            )
            self._connected = True
            self._rxbuf.clear()
            await self._drain_rx()
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
        self._rxbuf.clear()

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

            # Read until we can extract one CRC-valid RTU response.
            cap = 2048
            end = asyncio.get_running_loop().time() + float(timeout)
            while True:
                frame = self._extract_one_frame(data)
                if frame is not None:
                    _LOGGER.debug(
                        "TCP RTU RX from %s:%d: %s", self._host, self._port, frame.hex()
                    )
                    return frame

                if len(self._rxbuf) > cap:
                    # Avoid unbounded growth if gateway spews bytes.
                    self._rxbuf = self._rxbuf[-512:]

                remaining = end - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break

                try:
                    chunk = await asyncio.wait_for(
                        self._reader.read(256), timeout=min(remaining, 0.5)
                    )
                except asyncio.TimeoutError:
                    continue
                if not chunk:
                    break
                self._rxbuf += chunk

            raise asyncio.TimeoutError("No valid RTU response received")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._writer is not None and not self._writer.is_closing()

