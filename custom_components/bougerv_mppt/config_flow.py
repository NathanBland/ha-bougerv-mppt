"""Config flow: Bluetooth discovery plus manual pick, confirmed by reading device info.

FFE0 is a generic BLE-UART service, so a discovery match is only accepted after the
device answers the ChargePro device-info read. Controllers advertise the local name
"ChargePro". The manual step lists every connectable device, likely controllers first.
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

from .const import CONF_FORCE_SINGLE_LAYOUT, DOMAIN, SERVICE_UUID
from .coordinator import async_open_client
from .core.modbus import ModbusError
from .core.models import DeviceInfo, UnsupportedDevice

_LOGGER = logging.getLogger(__name__)

_MANUAL = "manual"
_MAX_LISTED = 40


def _looks_like_chargepro(info: BluetoothServiceInfoBleak) -> bool:
    return SERVICE_UUID in info.service_uuids or (info.name or "").startswith("ChargePro")


def _bluetooth_status(hass) -> dict[str, str]:
    """What Home Assistant hears right now, shown on the manual form to explain errors."""
    try:
        return {
            "connectable_scanners": str(bluetooth.async_scanner_count(hass, connectable=True)),
            "all_scanners": str(bluetooth.async_scanner_count(hass, connectable=False)),
            "connectable_devices": str(len(bluetooth.async_discovered_service_info(hass, True))),
            "all_devices": str(len(bluetooth.async_discovered_service_info(hass, False))),
        }
    except Exception:  # never let the status line break the form
        _LOGGER.debug("Could not read Bluetooth status", exc_info=True)
        return dict.fromkeys(
            ("connectable_scanners", "all_scanners", "connectable_devices", "all_devices"), "?"
        )


class BougeRVConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None

    async def _probe(
        self, address: str, force_single_layout: bool = False
    ) -> tuple[DeviceInfo | None, str | None]:
        """Connect and read device info. Returns (info, error_key)."""
        ble_device = bluetooth.async_ble_device_from_address(self.hass, address, True)
        if ble_device is None:
            if bluetooth.async_ble_device_from_address(self.hass, address, False) is not None:
                # Heard only by a passive scanner (e.g. a proxy without active: true).
                return None, "not_connectable"
            return None, "device_not_found"
        try:
            bleak_client, client = await async_open_client(
                self.hass, ble_device, address, force_single_layout=force_single_layout
            )
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

    def _create(self, info: DeviceInfo, address: str, force: bool) -> ConfigFlowResult:
        data: dict[str, Any] = {CONF_ADDRESS: address}
        if force:
            data[CONF_FORCE_SINGLE_LAYOUT] = True
        title = f"{info.model or 'ChargePro MPPT'} ({address[-5:]})"
        return self.async_create_entry(title=title, data=data)

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
                return self._create(info, address, False)
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
        if user_input is not None:
            if user_input[CONF_ADDRESS] == _MANUAL:
                return await self.async_step_manual()
            return await self.async_step_manual(
                {CONF_ADDRESS: user_input[CONF_ADDRESS], CONF_FORCE_SINGLE_LAYOUT: False}
            )

        configured = self._async_current_ids(include_ignore=False)
        found = [
            info
            for info in bluetooth.async_discovered_service_info(self.hass, True)
            if info.address not in configured
        ]
        found.sort(key=lambda i: (not _looks_like_chargepro(i), -(i.rssi or -127)))
        options: dict[str, str] = {}
        for info in found[:_MAX_LISTED]:
            tag = "★ " if _looks_like_chargepro(info) else ""
            name = info.name or "Unnamed"
            options[info.address] = f"{tag}{name} ({info.address}, {info.rssi} dBm)"
        if not options:
            return await self.async_step_manual()
        options[_MANUAL] = "Enter an address manually…"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            force = bool(user_input.get(CONF_FORCE_SINGLE_LAYOUT, False))
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            info, error = await self._probe(address, force)
            if info is not None:
                return self._create(info, address, force)
            errors["base"] = error or "unknown"
        defaults = user_input or {}
        return self.async_show_form(
            step_id="manual",
            description_placeholders=_bluetooth_status(self.hass),
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS, default=defaults.get(CONF_ADDRESS, "")): str,
                    vol.Optional(
                        CONF_FORCE_SINGLE_LAYOUT,
                        default=defaults.get(CONF_FORCE_SINGLE_LAYOUT, False),
                    ): bool,
                }
            ),
            errors=errors,
        )
