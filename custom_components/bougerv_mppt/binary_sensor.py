"""Binary sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BougeRVConfigEntry, BougeRVCoordinator
from .core.models import ControllerData
from .entity import BougeRVEntity


@dataclass(frozen=True, kw_only=True)
class BougeRVBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[ControllerData], bool | None]


BINARY_SENSORS: tuple[BougeRVBinaryDescription, ...] = (
    BougeRVBinaryDescription(
        key="load_on",
        translation_key="load_on",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda d: d.load_on,
    ),
    BougeRVBinaryDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: None if d.fault_code is None else d.fault_code != 0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BougeRVConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(BougeRVBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class BougeRVBinarySensor(BougeRVEntity, BinarySensorEntity):
    entity_description: BougeRVBinaryDescription

    def __init__(
        self, coordinator: BougeRVCoordinator, description: BougeRVBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
