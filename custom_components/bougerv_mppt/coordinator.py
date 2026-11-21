"""Polling coordinator: keeps one BLE connection open and reads the controller."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from bleak import BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_FORCE_SINGLE_LAYOUT, CONNECT_TIMEOUT, POLL_HISTORY, UPDATE_INTERVAL
from .core.client import ChargeProClient
from .core.modbus import ModbusError
from .core.models import ControllerData, DeviceInfo, UnsupportedDevice

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BougeRVRuntimeData:
    coordinator: BougeRVCoordinator


BougeRVConfigEntry = ConfigEntry[BougeRVRuntimeData]


async def async_open_client(
    hass: HomeAssistant,
    ble_device: BLEDevice,
    address: str,
    *,
    force_single_layout: bool = False,
) -> tuple[BleakClientWithServiceCache, ChargeProClient]:
    """Connect, subscribe and read device info. Used by the coordinator and config flow."""
    bleak_client = await establish_connection(
        BleakClientWithServiceCache,
        ble_device,
        address,
        use_services_cache=True,
        ble_device_callback=lambda: (
            bluetooth.async_ble_device_from_address(hass, address, True) or ble_device
        ),
        timeout=CONNECT_TIMEOUT,
    )
    client = ChargeProClient(bleak_client)
    try:
        await client.start(force_single_layout=force_single_layout)
    except BaseException:
        await bleak_client.disconnect()
        raise
    return bleak_client, client


class BougeRVCoordinator(DataUpdateCoordinator[ControllerData]):
    """Poll a ChargePro controller over a persistent BLE connection."""

    config_entry: BougeRVConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BougeRVConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=UPDATE_INTERVAL,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self.force_single_layout: bool = entry.data.get(CONF_FORCE_SINGLE_LAYOUT, False)
        self.device_info: DeviceInfo | None = None
        self.raw_registers: dict[str, list[int]] = {}
        # Recent raw polls, kept for diagnostics so register behaviour over time is visible.
        self.history: deque[dict[str, Any]] = deque(maxlen=POLL_HISTORY)
        self.last_error: str | None = None
        self.connects = 0
        self._bleak_client: BleakClientWithServiceCache | None = None
        self._client: ChargeProClient | None = None
        self._lock = asyncio.Lock()

    @property
    def profile_key(self) -> str | None:
        return self._client.profile.key if self._client and self._client.profile else None

    async def _ensure_connected(self) -> ChargeProClient:
        if self._client is not None and self._bleak_client and self._bleak_client.is_connected:
            return self._client
        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, True)
        if ble_device is None:
            raise UpdateFailed(f"{self.address} is not in range of any Bluetooth adapter")
        self._bleak_client, self._client = await async_open_client(
            self.hass, ble_device, self.address, force_single_layout=self.force_single_layout
        )
        self.connects += 1
        self.device_info = self._client.device_info
        return self._client

    async def _async_update_data(self) -> ControllerData:
        async with self._lock:
            try:
                client = await self._ensure_connected()
                data, self.raw_registers = await client.poll()
            except UnsupportedDevice as err:
                await self._disconnect()
                raise ConfigEntryError(
                    f"{err}. Re-add the device with 'Force single-battery layout' to test anyway."
                ) from err
            except (BleakError, TimeoutError, ModbusError) as err:
                self.last_error = f"{type(err).__name__}: {err}"
                await self._disconnect()
                raise UpdateFailed(self.last_error) from err
        self.history.append(
            {
                "time": round(time.time(), 1),
                **{key: [f"{reg:04X}" for reg in regs] for key, regs in self.raw_registers.items()},
            }
        )
        return data

    async def async_read_registers(self, address: int, count: int) -> list[int]:
        """Read arbitrary holding registers (function 0x03 only) on the shared connection."""
        async with self._lock:
            try:
                client = await self._ensure_connected()
                return await client.read_registers(address, count)
            except (BleakError, TimeoutError, ModbusError):
                await self._disconnect()
                raise

    async def _disconnect(self) -> None:
        bleak_client, self._bleak_client, self._client = self._bleak_client, None, None
        if bleak_client is not None:
            try:
                await bleak_client.disconnect()
            except BleakError:
                _LOGGER.debug("Disconnect failed", exc_info=True)

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        async with self._lock:
            await self._disconnect()
