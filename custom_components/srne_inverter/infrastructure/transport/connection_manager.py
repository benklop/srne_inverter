"""Connection managers for transport lifecycle (BLE vs USB serial).

Shared logic: exponential backoff, failure tracking, and connection state machine.
BLE uses a Bleak disconnect callback; USB serial opens the port without that path.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from ...domain.interfaces import IConnectionManager, ITransport
from ..decorators import handle_transport_errors
from ..state_machines import (
    ConnectionStateMachine,
    ConnectionState,
    ConnectionEvent,
)

_LOGGER = logging.getLogger(__name__)


class _BaseConnectionManager(IConnectionManager, ABC):
    """Shared connection policy: backoff, failures, and state machine."""

    MAX_CONSECUTIVE_FAILURES = 5
    INITIAL_BACKOFF = 1.0  # seconds
    MAX_BACKOFF = 300.0  # 5 minutes

    def __init__(self, transport: ITransport):
        self._transport = transport
        self._address: Optional[str] = None
        self._consecutive_failures = 0
        self._last_connection_attempt = 0.0
        self._backoff_time = self.INITIAL_BACKOFF
        self._state_machine = ConnectionStateMachine()

        self._state_machine.on_state(ConnectionState.CONNECTED, self._on_connected)
        self._state_machine.on_state(ConnectionState.FAILED, self._on_failed)

    def _on_connected(self):
        _LOGGER.info("Connection established successfully")

    def _on_failed(self):
        _LOGGER.warning("Connection failed")

    @abstractmethod
    async def _connect_transport(self, address: str) -> bool:
        """Open the underlying transport to *address* (BLE vs serial-specific)."""

    @handle_transport_errors("Ensure connection", reraise=False, default_return=False)
    async def ensure_connected(self, address: str, max_retries: int = 3) -> bool:
        self._address = address

        if self._state_machine.is_connected:
            return True

        if not self._state_machine.can_connect:
            _LOGGER.warning(
                "Cannot connect in state: %s", self._state_machine.state.name
            )
            return False

        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            time_since_last = time.time() - self._last_connection_attempt

            if time_since_last >= self.MAX_BACKOFF:
                _LOGGER.info(
                    "Resetting failure counter after %.1fs - attempting recovery",
                    time_since_last,
                )
                self._consecutive_failures = 0
                self._backoff_time = self.INITIAL_BACKOFF
            else:
                _LOGGER.error(
                    "Maximum consecutive connection failures (%d) reached. "
                    "Waiting %.1fs before reset attempt.",
                    self.MAX_CONSECUTIVE_FAILURES,
                    self.MAX_BACKOFF - time_since_last,
                )
                self._state = "failed"
                return False

        if self._consecutive_failures > 0:
            current_time = time.time()
            time_since_last = current_time - self._last_connection_attempt

            if time_since_last < self._backoff_time:
                wait_time = self._backoff_time - time_since_last
                _LOGGER.debug(
                    "Waiting %.1fs before reconnection (backoff: %.1fs, failures: %d/%d)",
                    wait_time,
                    self._backoff_time,
                    self._consecutive_failures,
                    self.MAX_CONSECUTIVE_FAILURES,
                )
                await asyncio.sleep(wait_time)

        self._last_connection_attempt = time.time()

        if self._state_machine.state == ConnectionState.RECONNECTING:
            self._state_machine.transition(ConnectionEvent.RETRY)
        else:
            self._state_machine.transition(ConnectionEvent.CONNECT)

        try:
            _LOGGER.debug("Attempting connection to %s", address)
            success = await self._connect_transport(address)

            if success:
                _LOGGER.info("Connected successfully to %s", address)
                self._consecutive_failures = 0
                self._backoff_time = self.INITIAL_BACKOFF
                self._state_machine.transition(ConnectionEvent.CONNECT_SUCCESS)
                return True
            self._handle_connection_failure()
            self._state_machine.transition(ConnectionEvent.CONNECT_FAILED)
            return False
        except Exception:
            self._handle_connection_failure()
            self._state_machine.transition(ConnectionEvent.CONNECT_FAILED)
            raise

    async def handle_connection_lost(self) -> None:
        _LOGGER.warning("Connection lost to %s", self._address)
        self._consecutive_failures += 1
        self._backoff_time = min(self._backoff_time * 2, self.MAX_BACKOFF)

        if not self._state_machine.transition(ConnectionEvent.CONNECTION_LOST):
            self._state_machine.force_state(ConnectionState.RECONNECTING)

        _LOGGER.debug(
            "Connection lost, backoff increased to %.1fs (failures: %d/%d)",
            self._backoff_time,
            self._consecutive_failures,
            self.MAX_CONSECUTIVE_FAILURES,
        )

    @property
    def connection_state(self) -> str:
        return self._state_machine.state.name.lower()

    @property
    def is_connected(self) -> bool:
        return self._state_machine.is_connected

    def _handle_connection_failure(self) -> None:
        self._consecutive_failures += 1
        self._backoff_time = min(self._backoff_time * 2, self.MAX_BACKOFF)

        _LOGGER.debug(
            "Connection failed, backoff increased to %.1fs (failures: %d/%d)",
            self._backoff_time,
            self._consecutive_failures,
            self.MAX_CONSECUTIVE_FAILURES,
        )

    def reset_failures(self) -> None:
        _LOGGER.info("Resetting connection failure tracking")
        self._consecutive_failures = 0
        self._backoff_time = self.INITIAL_BACKOFF
        self._state_machine.reset()

    def get_failure_info(self) -> dict:
        return {
            "consecutive_failures": self._consecutive_failures,
            "backoff_time": self._backoff_time,
            "last_attempt": self._last_connection_attempt,
            "state": self.connection_state,
        }


class ConnectionManager(_BaseConnectionManager):
    """BLE transport: exponential backoff plus Bleak disconnect callback."""

    def _handle_disconnect(self, client):
        """Handle unexpected BLE disconnect (Bleak callback; must stay non-async)."""
        client_address = getattr(client, "address", "unknown")
        is_connected = getattr(client, "is_connected", None)

        rssi = None
        try:
            if hasattr(client, "_backend"):
                rssi = getattr(client._backend, "rssi", None)
        except Exception:
            pass

        _LOGGER.warning(
            "BLE disconnect callback triggered - Address: %s, Client connected state: %s, RSSI: %s, "
            "Current failures: %d, Current state: %s",
            client_address,
            is_connected,
            f"{rssi}dBm" if rssi is not None else "unavailable",
            self._consecutive_failures,
            self._state_machine.state.name if self._state_machine else "unknown",
        )

        asyncio.create_task(self.handle_connection_lost())

    async def _connect_transport(self, address: str) -> bool:
        return await self._transport.connect(
            address, disconnected_callback=self._handle_disconnect
        )


class SerialConnectionManager(_BaseConnectionManager):
    """USB serial: same backoff/state machine; no BLE disconnect callback."""

    async def _connect_transport(self, address: str) -> bool:
        return await self._transport.connect(address)
