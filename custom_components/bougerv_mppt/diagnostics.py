"""Diagnostics: device info plus the raw registers from the last poll."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import BougeRVConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BougeRVConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    info = coordinator.device_info
    return {
        "device_info": asdict(info) if info else None,
        "raw_registers": {
            key: [f"{reg:04X}" for reg in regs] for key, regs in coordinator.raw_registers.items()
        },
        "data": asdict(coordinator.data) if coordinator.data else None,
    }
