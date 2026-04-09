"""USB serial transport implementation for SRNE inverter.

This module implements the ITransport interface for Modbus RTU over
USB serial adapters (for example /dev/ttyUSB0).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

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


def _strip_request_echo(response: bytes, request: bytes) -> bytes:
    """Remove a leading copy of the transmitted frame from RX.

    Some USB–RS485 adapters or wiring configurations feed the TX line back into
    RX, so the read buffer is ``[request][response]``. Modbus CRC is then taken
    from the wrong position and validation fails.
    """
    if not request or len(response) < len(request):
        return response
    if response.startswith(request):
        stripped = response[len(request) :]
        _LOGGER.debug(
            "Stripped serial TX echo (%d bytes); RX now %d bytes",
            len(request),
            len(stripped),
        )
        return stripped
    return response


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

        The response length varies by function code, so this reads until a
        short inter-byte gap is observed or the timeout is reached.
        """
        if not self._connected or self._writer is None or self._reader is None:
            raise RuntimeError("Serial transport not connected")

        self._writer.write(data)
        await self._writer.drain()

        chunks: list[bytes] = []
        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break

            try:
                # A short inter-byte gap usually indicates end-of-frame.
                read_timeout = min(remaining, 0.15)
                chunk = await asyncio.wait_for(
                    self._reader.read(256),
                    timeout=read_timeout,
                )
            except asyncio.TimeoutError:
                break

            if not chunk:
                break

            chunks.append(chunk)

        if not chunks:
            raise asyncio.TimeoutError(
                "No serial response received from "
                f"{self._port} within {timeout:.2f}s"
            )

        response = b"".join(chunks)
        response = _strip_request_echo(response, data)
        _LOGGER.debug("Serial RX from %s: %s", self._port, response.hex())
        return response

    @property
    def is_connected(self) -> bool:
        """Return connection state."""
        return self._connected
