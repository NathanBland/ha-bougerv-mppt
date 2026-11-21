"""Sensor entities.

Energy counters use device_class ENERGY + state_class TOTAL_INCREASING so they can be
added to the Energy dashboard. Today's counters reset at midnight, which
TOTAL_INCREASING handles. See README "Energy dashboard".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BougeRVConfigEntry, BougeRVCoordinator
from .core.models import CHARGE_STAGE_OPTIONS, ControllerData
from .entity import BougeRVEntity


@dataclass(frozen=True, kw_only=True)
class BougeRVSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ControllerData], Any]
    attrs_fn: Callable[[ControllerData], dict[str, Any]] | None = None


def _voltage(key: str, attr: str, **kw: Any) -> BougeRVSensorDescription:
    return BougeRVSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        value_fn=lambda d: getattr(d, attr),
        **kw,
    )


def _current(key: str, attr: str) -> BougeRVSensorDescription:
    return BougeRVSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        value_fn=lambda d: getattr(d, attr),
    )


def _power(key: str, attr: str, **kw: Any) -> BougeRVSensorDescription:
    return BougeRVSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: getattr(d, attr),
        **kw,
    )


def _energy(key: str, attr: str) -> BougeRVSensorDescription:
    return BougeRVSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: getattr(d, attr),
    )


def _temperature(key: str, attr: str) -> BougeRVSensorDescription:
    return BougeRVSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: getattr(d, attr),
    )


def _raw(index: int) -> BougeRVSensorDescription:
    register = 0x010A + index
    return BougeRVSensorDescription(
        key=f"raw_{register:04x}",
        translation_key="raw_register",
        translation_placeholders={"register": f"0x{register:04X}"},
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.raw_unknown[index] if len(d.raw_unknown) > index else None,
    )


SENSORS: tuple[BougeRVSensorDescription, ...] = (
    # Battery
    BougeRVSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.battery_soc,
    ),
    _voltage("battery_voltage", "battery_voltage"),
    _current("charge_current", "charge_current"),
    _power("charge_power", "charge_power"),
    _temperature("battery_temperature", "battery_temperature"),
    # Solar
    _voltage("pv_voltage", "pv_voltage"),
    BougeRVSensorDescription(
        key="charge_stage",
        translation_key="charge_stage",
        device_class=SensorDeviceClass.ENUM,
        options=CHARGE_STAGE_OPTIONS,
        value_fn=lambda d: d.charge_stage,
    ),
    # Load
    _voltage("load_voltage", "load_voltage"),
    _current("load_current", "load_current"),
    _power("load_power", "load_power"),
    BougeRVSensorDescription(
        key="load_mode",
        translation_key="load_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["manual", "automatic"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            None if d.load_manual_mode is None else "manual" if d.load_manual_mode else "automatic"
        ),
    ),
    # Controller
    _temperature("controller_temperature", "controller_temperature"),
    BougeRVSensorDescription(
        key="faults",
        translation_key="faults",
        value_fn=lambda d: None if d.fault_code is None else ", ".join(d.faults) or "none",
        attrs_fn=lambda d: {"fault_code": d.fault_code, "faults": list(d.faults)},
    ),
    BougeRVSensorDescription(
        key="running_days",
        translation_key="running_days",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.running_days,
    ),
    # Today
    _energy("today_charge_energy", "today_charge_energy"),
    _energy("today_discharge_energy", "today_discharge_energy"),
    _power("today_max_charge_power", "today_max_charge_power"),
    _voltage("today_max_battery_voltage", "today_max_battery_voltage"),
    _voltage("today_min_battery_voltage", "today_min_battery_voltage"),
    # Lifetime
    _energy("total_charge_energy", "total_charge_energy"),
    _energy("total_discharge_energy", "total_discharge_energy"),
    # Registers the app never displays (likely PV current/power); for hardware checks.
    _raw(0),
    _raw(1),
    _raw(2),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BougeRVConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(BougeRVSensor(coordinator, description) for description in SENSORS)


class BougeRVSensor(BougeRVEntity, SensorEntity):
    entity_description: BougeRVSensorDescription

    def __init__(
        self, coordinator: BougeRVCoordinator, description: BougeRVSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
