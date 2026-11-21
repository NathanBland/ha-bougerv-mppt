"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BougeRVCoordinator


class BougeRVEntity(CoordinatorEntity[BougeRVCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BougeRVCoordinator, key: str) -> None:
        super().__init__(coordinator)
        address = coordinator.address
        info = coordinator.device_info
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            model=info.model if info and info.model else "ChargePro MPPT",
            sw_version=info.firmware if info else None,
            name=coordinator.config_entry.title,
        )
