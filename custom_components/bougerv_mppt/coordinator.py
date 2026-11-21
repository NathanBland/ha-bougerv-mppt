"""Polling coordinator: keeps one BLE connection open and reads the controller."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONNECT_TIMEOUT, UPDATE_INTERVAL
from .core.client import ChargeProClient
from .core.modbus import ModbusError
from .core.models import ControllerData, DeviceInfo, UnsupportedDevice

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BougeRVRuntimeData:
    coordinator: BougeRVCoordinator


BougeRVConfigEntry = ConfigEntry[BougeRVRuntimeData]


async def async_open_client(
    hass: HomeAssistant, ble_device: BLEDevice, address: str
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
        await client.start()
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
        self.device_info: DeviceInfo | None = None
        self.raw_registers: dict[str, list[int]] = {}
        self._bleak_client: BleakClientWithServiceCache | None = None
        self._client: ChargeProClient | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> ChargeProClient:
        if self._client is not None and self._bleak_client and self._bleak_client.is_connected:
            return self._client
        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, True)
        if ble_device is None:
            raise UpdateFailed(f"{self.address} is not in range of any Bluetooth adapter")
        self._bleak_client, self._client = await async_open_client(
            self.hass, ble_device, self.address
        )
        self.device_info = self._client.device_info
        return self._client

    async def _async_update_data(self) -> ControllerData:
        async with self._lock:
            try:
                client = await self._ensure_connected()
                data, self.raw_registers = await client.poll()
            except UnsupportedDevice as err:
                await self._disconnect()
                raise ConfigEntryError(str(err)) from err
            except (BleakError, TimeoutError, ModbusError) as err:
                await self._disconnect()
                raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        return data

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
