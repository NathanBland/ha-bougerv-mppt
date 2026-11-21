"""Diagnostics download: everything needed to check the protocol on real hardware.

Includes the advertisement as Home Assistant sees it, the device-info block, the last
~15 minutes of raw polls, and a fresh read of every documented read-only block.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import DIAGNOSTIC_BLOCKS
from .coordinator import BougeRVConfigEntry

_LOGGER = logging.getLogger(__name__)


def _advertisement(hass: HomeAssistant, address: str) -> dict[str, Any] | None:
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    if info is None:
        info = bluetooth.async_last_service_info(hass, address, connectable=False)
    if info is None:
        return None
    return {
        "name": info.name,
        "rssi": info.rssi,
        "source": info.source,
        "connectable": info.connectable,
        "service_uuids": list(info.service_uuids),
        "service_data": {k: v.hex() for k, v in info.service_data.items()},
        "manufacturer_data": {str(k): v.hex() for k, v in info.manufacturer_data.items()},
        "tx_power": info.tx_power,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BougeRVConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    info = coordinator.device_info

    blocks: dict[str, Any] = {}
    for name, address, count in DIAGNOSTIC_BLOCKS:
        try:
            regs = await coordinator.async_read_registers(address, count)
        except Exception as err:  # record and keep going
            blocks[name] = {"error": f"{type(err).__name__}: {err}"}
        else:
            blocks[name] = [f"{reg:04X}" for reg in regs]

    return {
        "address": coordinator.address,
        "force_single_layout": coordinator.force_single_layout,
        "advertisement": _advertisement(hass, coordinator.address),
        "device_info": asdict(info) if info else None,
        "profile": coordinator.profile_key,
        "connects": coordinator.connects,
        "last_error": coordinator.last_error,
        "last_update_success": coordinator.last_update_success,
        "data": asdict(coordinator.data) if coordinator.data else None,
        "raw_registers": {
            key: [f"{reg:04X}" for reg in regs] for key, regs in coordinator.raw_registers.items()
        },
        "fresh_reads": blocks,
        "poll_history": list(coordinator.history),
    }
