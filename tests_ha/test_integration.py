"""Config flow and entry setup inside a real Home Assistant core (BLE is faked)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bougerv_mppt.const import CONF_FORCE_SINGLE_LAYOUT, DOMAIN, SERVICE_UUID
from custom_components.bougerv_mppt.core.models import (
    SINGLE_BATTERY,
    UnsupportedDevice,
    parse_device_info,
)
from custom_components.bougerv_mppt.diagnostics import async_get_config_entry_diagnostics

ADDRESS = "AA:BB:CC:DD:EE:FF"
MODEL = b"MPPT-40A        "
INFO = parse_device_info(
    [0x2800, 0]
    + [int.from_bytes(MODEL[i : i + 2], "big") for i in range(0, 16, 2)]
    + [105, 0, 0, 0, 0, 0]
)
LIVE = [87, 132, 1250, 165, (31 << 8) | 22, 131, 215, 28, 185, 0, 0, 0]
LIVE += [0x0105, 0x0008, 412, 0x0001, 0x86A0, 0, 50000, 0, 0, 0]
DATA = SINGLE_BATTERY.build({"live": LIVE, "today": [420, 180, 310, 144, 121], "load": [0x0100]})

BLE_DEVICE = BLEDevice(ADDRESS, "BT-TH-1234", None)
SERVICE_INFO = BluetoothServiceInfoBleak(
    name="BT-TH-1234",
    address=ADDRESS,
    rssi=-60,
    manufacturer_data={},
    service_data={},
    service_uuids=[SERVICE_UUID],
    source="local",
    device=BLE_DEVICE,
    advertisement=AdvertisementData(
        local_name="BT-TH-1234",
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        tx_power=None,
        rssi=-60,
        platform_data=(),
    ),
    connectable=True,
    time=0,
    tx_power=None,
)


def _fake_open(error: Exception | None = None, calls: list | None = None):
    async def _open(_hass, _device, _address, *, force_single_layout=False):
        if calls is not None:
            calls.append(force_single_layout)
        if error is not None:
            raise error
        bleak_client = MagicMock(is_connected=True, disconnect=AsyncMock())
        client = SimpleNamespace(
            device_info=INFO,
            profile=SINGLE_BATTERY,
            poll=AsyncMock(return_value=(DATA, {"live": LIVE})),
            read_registers=AsyncMock(side_effect=lambda address, count: list(range(count))),
            stop=AsyncMock(),
        )
        return bleak_client, client

    return _open


@pytest.fixture
def ble_present():
    with (
        patch(
            "custom_components.bougerv_mppt.config_flow.bluetooth.async_ble_device_from_address",
            return_value=BLE_DEVICE,
        ),
        patch(
            "custom_components.bougerv_mppt.config_flow.bluetooth.async_discovered_service_info",
            return_value=[SERVICE_INFO],
        ),
        patch("custom_components.bougerv_mppt.async_setup_entry", return_value=True),
    ):
        yield


async def test_bluetooth_discovery_creates_entry(hass: HomeAssistant, ble_present) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=SERVICE_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    with patch("custom_components.bougerv_mppt.config_flow.async_open_client", _fake_open()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MPPT-40A (EE:FF)"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["result"].unique_id == ADDRESS


async def test_bluetooth_discovery_aborts_for_other_ffe0_devices(
    hass: HomeAssistant, ble_present
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=SERVICE_INFO
    )
    with patch(
        "custom_components.bougerv_mppt.config_flow.async_open_client",
        _fake_open(TimeoutError()),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_chargepro"


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (BleakError("boom"), "cannot_connect"),
        (UnsupportedDevice("dual"), "unsupported_model"),
    ],
)
async def test_user_flow_errors_then_success(
    hass: HomeAssistant, ble_present, error: Exception, key: str
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with patch("custom_components.bougerv_mppt.config_flow.async_open_client", _fake_open(error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": key}
    with patch("custom_components.bougerv_mppt.config_flow.async_open_client", _fake_open()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ADDRESS}


async def test_manual_address_with_forced_layout(hass: HomeAssistant, ble_present) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "manual"}
    )
    assert result["step_id"] == "manual"
    calls: list[bool] = []
    with patch(
        "custom_components.bougerv_mppt.config_flow.async_open_client", _fake_open(calls=calls)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_ADDRESS: " aa:bb:cc:dd:ee:ff ", CONF_FORCE_SINGLE_LAYOUT: True},
        )
    assert calls == [True]
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_FORCE_SINGLE_LAYOUT: True}


async def test_user_flow_lists_non_ffe0_devices(hass: HomeAssistant, ble_present) -> None:
    other = BluetoothServiceInfoBleak(
        name="Other",
        address="11:22:33:44:55:66",
        rssi=-40,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice("11:22:33:44:55:66", "Other", None),
        advertisement=SERVICE_INFO.advertisement,
        connectable=True,
        time=0,
        tx_power=None,
    )
    with patch(
        "custom_components.bougerv_mppt.config_flow.bluetooth.async_discovered_service_info",
        return_value=[other, SERVICE_INFO],
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    options = list(result["data_schema"].schema[CONF_ADDRESS].container)
    assert options == [ADDRESS, "11:22:33:44:55:66", "manual"]


async def test_setup_entry_creates_entities(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}, title="MPPT-40A (EE:FF)"
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.bougerv_mppt.coordinator.bluetooth.async_ble_device_from_address",
            return_value=BLE_DEVICE,
        ),
        patch("custom_components.bougerv_mppt.coordinator.async_open_client", _fake_open()),
        patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    prefix = "mppt_40a_ee_ff"

    def state(entity: str) -> str:
        found = hass.states.get(entity)
        assert found is not None, entity
        return found.state

    assert state(f"sensor.{prefix}_battery_state_of_charge") == "87"
    assert state(f"sensor.{prefix}_battery_voltage") == "13.2"
    assert state(f"sensor.{prefix}_charge_stage") == "float"
    assert state(f"sensor.{prefix}_faults") == "load_short_circuit"
    assert state(f"binary_sensor.{prefix}_fault") == "on"
    assert state(f"binary_sensor.{prefix}_load_output") == "on"
    total = hass.states.get(f"sensor.{prefix}_total_energy_charged")
    assert total.state == "100.0"
    assert total.attributes["unit_of_measurement"] == "kWh"
    assert total.attributes["state_class"] == "total_increasing"
    assert total.attributes["device_class"] == "energy"
    # Raw diagnostic registers are disabled by default.
    assert hass.states.get(f"sensor.{prefix}_register_0x010a") is None

    # read_registers action returns the registers from the shared connection.
    response = await hass.services.async_call(
        DOMAIN,
        "read_registers",
        {"config_entry_id": entry.entry_id, "address": 0x010A, "count": 3},
        blocking=True,
        return_response=True,
    )
    assert response == {
        "start": "0x010A",
        "registers": {
            "0x010A": {"hex": "0000", "value": 0},
            "0x010B": {"hex": "0001", "value": 1},
            "0x010C": {"hex": "0002", "value": 2},
        },
    }

    # Diagnostics include a fresh read of every documented block, never the password block.
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["profile"] == "single_battery"
    assert diag["device_info"]["model"] == "MPPT-40A"
    assert diag["fresh_reads"]["live_0x0101"][:2] == ["0000", "0001"]
    assert not any("0310" in name for name in diag["fresh_reads"])
    assert len(diag["poll_history"]) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_forced_layout_is_passed_to_client(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_FORCE_SINGLE_LAYOUT: True},
    )
    entry.add_to_hass(hass)
    calls: list[bool] = []
    with (
        patch(
            "custom_components.bougerv_mppt.coordinator.bluetooth.async_ble_device_from_address",
            return_value=BLE_DEVICE,
        ),
        patch(
            "custom_components.bougerv_mppt.coordinator.async_open_client",
            _fake_open(calls=calls),
        ),
        patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert calls == [True]


async def test_setup_retries_when_device_missing(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.bougerv_mppt.coordinator.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
        patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_dual_battery_is_a_setup_error(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.bougerv_mppt.coordinator.bluetooth.async_ble_device_from_address",
            return_value=BLE_DEVICE,
        ),
        patch(
            "custom_components.bougerv_mppt.coordinator.async_open_client",
            _fake_open(UnsupportedDevice("dual")),
        ),
        patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_manual_reports_passive_only_device(hass: HomeAssistant, ble_present) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "manual"}
    )
    with patch(
        "custom_components.bougerv_mppt.config_flow.bluetooth.async_ble_device_from_address",
        side_effect=lambda _hass, _addr, connectable: None if connectable else BLE_DEVICE,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["errors"] == {"base": "not_connectable"}
