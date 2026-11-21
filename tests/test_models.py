from __future__ import annotations

import pytest

from custom_components.bougerv_mppt.core.models import (
    SINGLE_BATTERY,
    UnsupportedDevice,
    decode_faults,
    parse_device_info,
    parse_single_live,
    parse_today,
    select_profile,
)


def _words(hex_string: str) -> list[int]:
    return [int(hex_string[i : i + 4], 16) for i in range(0, len(hex_string), 4)]


# Debug sample from MainActivity.Response (15 words; the app pads nothing).
APP_DEVICE_INFO_SAMPLE = "1EFF180C202044432D44432D333020202020200000640064000000000001"
# Debug samples from MainActivity.Response for HOME_DATA and TODAY_DATA.
APP_HOME_SAMPLE = (
    "0C0C640001210122000100020086002100001CFF000000000000000000000000000000000000000000FF0001"
)
APP_TODAY_SAMPLE = "0000000000000000000000000000000000000000000000800081"

# Synthetic single-battery frame with realistic values for a 12 V system.
LIVE = [
    87,  # SOC %
    132,  # 13.2 V
    1250,  # 12.50 A
    165,  # 165 W
    (31 << 8) | 22,  # controller 31 °C, battery 22 °C
    131,  # load 13.1 V
    215,  # 2.15 A
    28,  # 28 W
    185,  # PV 18.5 V
    0x1111,
    0x2222,
    0x3333,
    (1 << 8) | 2,  # load on, MPPT
    0b0001_0000_0000_1001,  # over-discharge, load short, PV reverse
    412,  # days
    0x0001,
    0x86A0,  # 100000 Wh
    0x0000,
    0xC350,  # 50000 Wh
    0,
    0,
    0,
]


def test_device_info_from_app_sample() -> None:
    info = parse_device_info(_words(APP_DEVICE_INFO_SAMPLE))
    assert info.model == "DC-DC-30"
    assert info.firmware == "1.00"
    assert info.layout == 1
    assert info.rated_current == 0x1E
    assert info.password_enabled is False
    assert info.dual_battery is True


def test_100f_and_80f_models_are_never_dual() -> None:
    regs = _words(APP_DEVICE_INFO_SAMPLE) + [0]
    model = b"MPPT-100F       "
    regs[2:10] = [int.from_bytes(model[i : i + 2], "big") for i in range(0, 16, 2)]
    info = parse_device_info(regs)
    assert info.model == "MPPT-100F"
    assert info.dual_battery is False


def test_select_profile() -> None:
    single = parse_device_info([0] * 14 + [0, 0])
    assert select_profile(single) is SINGLE_BATTERY
    dcdc = parse_device_info([0] * 14 + [3, 0])
    assert select_profile(dcdc) is SINGLE_BATTERY
    with pytest.raises(UnsupportedDevice):
        select_profile(parse_device_info(_words(APP_DEVICE_INFO_SAMPLE)))


def test_parse_single_live() -> None:
    values = parse_single_live(LIVE)
    assert values["battery_soc"] == 87
    assert values["battery_voltage"] == 13.2
    assert values["charge_current"] == 12.5
    assert values["charge_power"] == 165
    assert values["controller_temperature"] == 31
    assert values["battery_temperature"] == 22
    assert values["load_voltage"] == 13.1
    assert values["load_current"] == 2.15
    assert values["load_power"] == 28
    assert values["pv_voltage"] == 18.5
    assert values["raw_unknown"] == (0x1111, 0x2222, 0x3333)
    assert values["load_on"] is True
    assert values["charge_stage"] == "mppt"
    assert values["fault_code"] == 0x1009
    assert values["faults"] == (
        "battery_over_discharge",
        "load_short_circuit",
        "pv_reverse_polarity",
    )
    assert values["running_days"] == 412
    assert values["total_charge_energy"] == 100000
    assert values["total_discharge_energy"] == 50000


def test_parse_app_home_sample_does_not_crash() -> None:
    values = parse_single_live(_words(APP_HOME_SAMPLE))
    assert values["battery_soc"] == 0x0C0C
    assert values["battery_voltage"] == 2560.0  # dual-layout sample, so values are nonsense
    assert values["charge_stage"] == "off"
    assert values["load_on"] is False


def test_unknown_stage_maps_to_none() -> None:
    live = list(LIVE)
    live[12] = 0x0009
    assert parse_single_live(live)["charge_stage"] is None


def test_parse_today_app_sample() -> None:
    values = parse_today(_words(APP_TODAY_SAMPLE)[:5])
    assert values == {
        "today_charge_energy": 0,
        "today_discharge_energy": 0,
        "today_max_charge_power": 0,
        "today_max_battery_voltage": 0.0,
        "today_min_battery_voltage": 0.0,
    }


def test_parse_today() -> None:
    assert parse_today([420, 180, 310, 144, 121]) == {
        "today_charge_energy": 420,
        "today_discharge_energy": 180,
        "today_max_charge_power": 310,
        "today_max_battery_voltage": 14.4,
        "today_min_battery_voltage": 12.1,
    }


def test_decode_faults_unknown_bit() -> None:
    assert decode_faults(0) == []
    assert decode_faults(1 << 10) == ["bit_10"]


def test_profile_build_merges_blocks() -> None:
    data = SINGLE_BATTERY.build({"live": LIVE, "today": [1, 2, 3, 144, 120], "load": [0x0100]})
    assert data.battery_soc == 87
    assert data.today_charge_energy == 1
    assert data.load_manual_mode is True
    assert data.faults == ("battery_over_discharge", "load_short_circuit", "pv_reverse_polarity")


def test_profile_build_tolerates_missing_block() -> None:
    data = SINGLE_BATTERY.build({"live": LIVE})
    assert data.today_charge_energy is None
