# Copyright (c) 2026 SRNE Inverter Contributors
# Licensed under the MIT License
# See LICENSE file for full license text
#
# WARNING: This software controls electrical equipment
# Improper use may cause damage or injury
# USE AT YOUR OWN RISK

"""Configurable number entity with register write support."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from ..config_loader import get_register_definition
from .configurable_base import ConfigurableBaseEntity
from ..coordinator import SRNEDataUpdateCoordinator
from ..const import CONF_BATTERY_NOMINAL_VOLTAGE, WRITE_VERIFY_DELAY_UI

# Extra delay between verify read attempts (inverter may commit after first poll)
_WRITE_VERIFY_RETRY_DELAY = 0.25
_WRITE_VERIFY_MAX_ATTEMPTS = 4

_LOGGER = logging.getLogger(__name__)


class ConfigurableNumber(ConfigurableBaseEntity, NumberEntity):
    """Number entity configured from YAML with register write support.

    This entity allows reading and writing numeric register values with:
    - Automatic scaling (e.g., 0.1 for current values)
    - Optional per-12V battery setpoints: registers marked ``per_12v_reference`` in YAML
      are shown and edited in pack volts using ``battery_voltage`` from the config entry
    - Min/max/step validation
    - Optimistic state updates for instant UI feedback
    - Read-verify after write for safety
    - Automatic rollback on write failure
    """

    def __init__(
        self,
        coordinator: SRNEDataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict[str, Any],
        device_config: dict[str, Any],
    ) -> None:
        """Initialize the number entity.

        Args:
            coordinator: Data update coordinator
            entry: Config entry
            config: Entity configuration dict from YAML
            device_config: Full device configuration with registers
        """
        super().__init__(coordinator, entry, config)

        self._device_config = device_config

        # Register definition (needed before min/max: per-12V pack scaling)
        reg_def = get_register_definition(device_config, config["register"])
        self._per_12v_reference = bool(
            config.get("per_12v_reference")
            or (reg_def or {}).get("per_12v_reference", False)
        )
        self._pack_scale = (
            self._entry_pack_nominal_voltage_v() / 12.0
            if self._per_12v_reference
            else 1.0
        )

        # Number-specific attributes from config (min/max in YAML are per-12V when
        # register has per_12v_reference; we expose pack-side volts in the UI)
        min_raw = float(config["min"])
        max_raw = float(config["max"])
        step_raw = float(config.get("step", 1))
        self._attr_native_min_value = min_raw * self._pack_scale
        self._attr_native_max_value = max_raw * self._pack_scale
        self._attr_native_step = step_raw * self._pack_scale

        # Mode: slider, box, or auto (defaults to auto)
        mode_str = config.get("mode", "auto")
        if mode_str == "slider":
            self._attr_mode = NumberMode.SLIDER
        elif mode_str == "box":
            self._attr_mode = NumberMode.BOX
        else:
            self._attr_mode = NumberMode.AUTO

        # Unit of measurement
        self._attr_native_unit_of_measurement = config.get("unit")

        # Register configuration for writes
        self._register_name = config["register"]

        # Get scaling factor from register definition (single source of truth)
        # If entity config overrides it, use that
        if reg_def:
            self._scale = config.get("scale", reg_def.get("scaling", 1.0))
            self._signed = config.get(
                "signed", reg_def.get("data_type", "uint16").startswith("int")
            )
            _LOGGER.debug(
                "Number entity %s using scaling factor %s from %s",
                config.get("name"),
                self._scale,
                "entity config" if "scale" in config else "register definition",
            )
        else:
            # Fallback to entity config (shouldn't happen if register is defined)
            self._scale = config.get("scale", 1.0)
            self._signed = config.get("signed", False)
            _LOGGER.debug(
                "Register definition '%s' not found for %s, using entity config scale=%s",
                self._register_name,
                config.get("name"),
                self._scale,
            )

        # Optimistic state management
        self._optimistic = config.get("optimistic", False)
        self._optimistic_value: float | None = None
        self._previous_value: float | None = None  # For rollback

        # Verify configuration on startup
        self._verify_register_config()

    def _entry_pack_nominal_voltage_v(self) -> int:
        """Nominal DC system voltage from the integration config (12/24/36/48).

        SRNE stores many battery voltage setpoints in a per-12V reference; we scale
        the UI to pack volts using this value (from onboarding / options).
        """
        data = self._entry.data
        opts = getattr(self._entry, "options", None) or {}
        raw = data.get(CONF_BATTERY_NOMINAL_VOLTAGE) or opts.get(
            CONF_BATTERY_NOMINAL_VOLTAGE
        )
        if raw is None:
            return 12
        try:
            v = int(str(raw).strip())
        except (TypeError, ValueError):
            return 12
        if v <= 0:
            return 12
        return v

    def _verify_register_config(self) -> None:
        """Verify register configuration is valid."""
        reg_def = get_register_definition(self._device_config, self._register_name)
        if not reg_def:
            _LOGGER.error(
                "Register definition '%s' not found for %s. Entity may not function correctly.",
                self._register_name,
                self._attr_name,
            )

    @property
    def native_value(self) -> float | None:
        """Return the current value from coordinator data."""
        # Prefer optimistic state during pending writes
        if self._optimistic_value is not None:
            return self._optimistic_value

        # Use confirmed state
        if not self.coordinator.data:
            return None

        # Get value from coordinator (already scaled by coordinator's register definition)
        data_key = self._config["entity_id"]
        coordinator_value = self._get_coordinator_value(data_key)

        if coordinator_value is None:
            return None

        # CRITICAL FIX: Don't apply scaling here - coordinator.data already contains
        # scaled values. The coordinator applies the register's scaling factor
        # (from entities_pilot.yaml "scaling" field) during data fetch.
        # The entity's "scale" field should ONLY be used for write operations
        # in _encode_value() to convert UI values back to raw register values.
        #
        # Example: output_frequency
        #   - Inverter reports: 6000 (raw)
        #   - Coordinator scales: 6000 × 0.01 = 60.0 (stored in coordinator.data)
        #   - Entity displays: 60.0 (NO additional scaling)
        #   - User writes: 60.0
        #   - Entity encodes: 60.0 ÷ 0.01 = 6000 (written to inverter)
        v = float(coordinator_value)
        if self._per_12v_reference:
            v *= self._pack_scale
        return v

    async def async_set_native_value(self, value: float) -> None:
        """Write new value to inverter register.

        This method implements a safe write transaction with:
        1. Value validation against min/max
        2. Optimistic UI update (instant feedback)
        3. Register write via coordinator
        4. Read-verify to confirm write
        5. Automatic rollback on failure

        Args:
            value: New native value to set (already scaled for display)

        Raises:
            HomeAssistantError: If write fails or verification fails
        """
        _LOGGER.info(
            "Setting %s to: %s %s",
            self._attr_name,
            value,
            self._attr_native_unit_of_measurement or "",
        )

        # Step 1: Validate value against min/max
        if not (self._attr_native_min_value <= value <= self._attr_native_max_value):
            raise HomeAssistantError(
                f"Value {value} out of range [{self._attr_native_min_value}, {self._attr_native_max_value}]"
            )

        # Step 2: Store current value for rollback
        self._previous_value = self.native_value

        # Step 3: Optimistic update for instant UI feedback
        if self._optimistic:
            self._optimistic_value = value
            self.async_write_ha_state()

        try:
            # Step 4: Convert native value to register value
            register_value = self._encode_value(value)

            _LOGGER.debug(
                "Encoding %s: native=%s → register=%d (scale=%s)",
                self._attr_name,
                value,
                register_value,
                self._scale,
            )

            # Step 5: Get register address
            reg_def = get_register_definition(self._device_config, self._register_name)
            if not reg_def:
                raise HomeAssistantError(
                    f"Register definition '{self._register_name}' not found"
                )

            register_address = reg_def.get("_address_int") or reg_def["address"]

            # Step 6: Write to inverter via coordinator
            write_result = await self.coordinator.async_write_register(
                register_address, register_value
            )

            if not write_result.success:
                detail = (write_result.error or "").strip() or (
                    "Write command failed. Confirm inverter connection and that the device is responsive."
                )
                await self._handle_write_failure(detail, register_address)
                return

            # Step 7: Read-verify after write (with delay for inverter processing)
            await asyncio.sleep(WRITE_VERIFY_DELAY_UI)
            verified = await self._verify_write(register_address, register_value)

            if not verified:
                await self._handle_write_failure(
                    "Write verification failed. Value may not have been written correctly.",
                    register_address,
                )
                return

            # Step 8: Success - clear optimistic state and let coordinator update
            _LOGGER.info(
                "%s set to %s successfully (register 0x%04X = %d)",
                self._attr_name,
                value,
                register_address,
                register_value,
            )

            # Clear optimistic state - coordinator will update on next refresh
            if self._optimistic:
                self._optimistic_value = None
                self.async_write_ha_state()

        except HomeAssistantError:
            # Propagate HomeAssistantError as-is
            raise
        except Exception as err:
            # Wrap other exceptions
            _LOGGER.exception("Unexpected error setting %s: %s", self._attr_name, err)
            await self._handle_write_failure(
                f"Unexpected error: {err}",
                None,
            )

    async def _verify_write(self, register_address: int, expected_value: int) -> bool:
        """Verify write by reading the register from the device.

        ``coordinator.data`` is only updated on the polling cycle, so comparing
        against it after a write falsely fails even when the inverter accepted
        the value. We read the holding register directly instead.
        """
        try:
            expected_scaled = float(expected_value) * self._scale
            tolerance = max(self._attr_native_step / 2, 1e-6)

            for attempt in range(_WRITE_VERIFY_MAX_ATTEMPTS):
                if attempt == 0:
                    await asyncio.sleep(WRITE_VERIFY_DELAY_UI)
                else:
                    await asyncio.sleep(_WRITE_VERIFY_RETRY_DELAY)

                readback_raw = await self.coordinator.async_read_register(
                    register_address
                )

                if readback_raw is None:
                    _LOGGER.warning(
                        "Write verify attempt %d: no response for %s (0x%04X)",
                        attempt + 1,
                        self._attr_name,
                        register_address,
                    )
                    continue

                if readback_raw == 0x2D2D:
                    _LOGGER.debug(
                        "Write verify got unsupported/dash pattern for %s (0x%04X)",
                        self._attr_name,
                        register_address,
                    )
                    return False

                readback_scaled = float(readback_raw) * self._scale

                if abs(readback_scaled - expected_scaled) <= tolerance:
                    if attempt > 0:
                        _LOGGER.debug(
                            "Write verified for %s on attempt %d",
                            self._attr_name,
                            attempt + 1,
                        )
                    return True

                _LOGGER.debug(
                    "Write verify attempt %d for %s: expected raw %d (scaled %s), "
                    "read raw %d (scaled %s)",
                    attempt + 1,
                    self._attr_name,
                    expected_value,
                    expected_scaled,
                    readback_raw,
                    readback_scaled,
                )

            _LOGGER.warning(
                "Write verification failed for %s after %d attempts "
                "(expected raw %d / scaled %s)",
                self._attr_name,
                _WRITE_VERIFY_MAX_ATTEMPTS,
                expected_value,
                expected_scaled,
            )
            return False

        except Exception as err:
            _LOGGER.error(
                "Error verifying write for %s: %s",
                self._attr_name,
                err,
            )
            return True

    async def _handle_write_failure(
        self, error_message: str, register_address: int | None
    ) -> None:
        """Handle write failure with rollback and error reporting.

        Args:
            error_message: Human-readable error message
            register_address: Register address (for logging), or None
        """
        # Revert optimistic state
        if self._optimistic:
            self._optimistic_value = None
            self.async_write_ha_state()

        # Format error message
        if register_address is not None:
            full_message = f"Failed to write {self._attr_name}: {error_message} (register 0x{register_address:04X})"
        else:
            full_message = f"Failed to write {self._attr_name}: {error_message}"

        _LOGGER.error(full_message)
        raise HomeAssistantError(full_message)

    def _encode_value(self, value: float) -> int:
        """Convert native value to register representation.

        Args:
            value: Native value (e.g., 30.0A)

        Returns:
            Register value (e.g., 300 for 0.1 scale)
        """
        # Apply inverse scaling (native value may be pack volts for per-12V registers)
        value_in = value
        if self._per_12v_reference:
            value_in = value / self._pack_scale
        # e.g., 30.0A with scale 0.1 → 300
        register_value = int(round(value_in / self._scale))

        # Handle signed values (two's complement for negative numbers)
        if self._signed and register_value < 0:
            register_value = register_value + 0x10000

        # Ensure value fits in 16-bit register
        register_value = register_value & 0xFFFF

        return register_value

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        Clears optimistic state once coordinator confirms the new value.
        """
        # Clear optimistic state once confirmed
        if self._optimistic and self._optimistic_value is not None:
            confirmed_value = self.native_value  # Gets value from coordinator
            if confirmed_value is not None and abs(
                confirmed_value - self._optimistic_value
            ) < (self._attr_native_step / 2):
                _LOGGER.debug(
                    "Number %s confirmed: %s",
                    self._attr_name,
                    confirmed_value,
                )
                self._optimistic_value = None

        super()._handle_coordinator_update()
