"""BougeRV / ChargePro MPPT solar charge controller over Bluetooth LE (read-only).

Home Assistant imports stay inside the functions so ``core`` (and the CLI) can be used
without Home Assistant installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import BougeRVConfigEntry

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: BougeRVConfigEntry) -> bool:
    from .coordinator import BougeRVCoordinator, BougeRVRuntimeData

    coordinator = BougeRVCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = BougeRVRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BougeRVConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.coordinator.async_shutdown()
    return unload_ok
