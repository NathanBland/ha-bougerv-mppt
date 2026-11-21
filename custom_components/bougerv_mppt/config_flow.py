"""Config flow: Bluetooth discovery plus manual pick, confirmed by reading device info.

FFE0 is a generic BLE-UART service, so a discovery match is only accepted after the
device answers the ChargePro device-info read.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak import BleakError
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, SERVICE_UUID
from .coordinator import async_open_client
from .core.modbus import ModbusError
from .core.models import DeviceInfo, UnsupportedDevice

_LOGGER = logging.getLogger(__name__)


class BougeRVConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._candidates: dict[str, BluetoothServiceInfoBleak] = {}

    async def _probe(self, address: str) -> tuple[DeviceInfo | None, str | None]:
        """Connect and read device info. Returns (info, error_key)."""
        ble_device = bluetooth.async_ble_device_from_address(self.hass, address, True)
        if ble_device is None:
            return None, "device_not_found"
        try:
            bleak_client, client = await async_open_client(self.hass, ble_device, address)
        except UnsupportedDevice:
            return None, "unsupported_model"
        except (ModbusError, TimeoutError):
            return None, "not_chargepro"
        except BleakError:
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error probing %s", address)
            return None, "unknown"
        await client.stop()
        await bleak_client.disconnect()
        return client.device_info, None

    def _title(self, info: DeviceInfo, address: str) -> str:
        return f"{info.model or 'ChargePro MPPT'} ({address[-5:]})"

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or discovery_info.address}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        address = self._discovery.address
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await self._probe(address)
            if info is not None:
                return self.async_create_entry(
                    title=self._title(info, address), data={CONF_ADDRESS: address}
                )
            if error == "not_chargepro":
                return self.async_abort(reason="not_chargepro")
            errors["base"] = error or "unknown"
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery.name or address},
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            info, error = await self._probe(address)
            if info is not None:
                return self.async_create_entry(
                    title=self._title(info, address), data={CONF_ADDRESS: address}
                )
            errors["base"] = error or "unknown"

        configured = self._async_current_ids(include_ignore=False)
        for service_info in bluetooth.async_discovered_service_info(self.hass, True):
            if service_info.address in configured:
                continue
            if SERVICE_UUID in service_info.service_uuids:
                self._candidates[service_info.address] = service_info

        if self._candidates:
            options = {
                address: f"{info.name or 'Unnamed'} ({address})"
                for address, info in self._candidates.items()
            }
            schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)})
        else:
            schema = vol.Schema({vol.Required(CONF_ADDRESS): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
