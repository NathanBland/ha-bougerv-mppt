"""Register maps and parsers for ChargePro-family controllers.

Each supported layout is a :class:`Profile` in :data:`PROFILES`. New controller models are
added by writing a profile (blocks to read plus a parser) and teaching
:func:`select_profile` to pick it. See docs/protocol-chargepro-3.0.0.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum

from .modbus import u32


@dataclass(frozen=True, slots=True)
class Block:
    """A contiguous register range read with function 0x03."""

    key: str
    address: int
    count: int


DEVICE_INFO_BLOCK = Block("device_info", 0x000A, 16)


class ChargeStage(IntEnum):
    """Low byte of real-time register 12 (``HomeFragment.setData``)."""

    OFF = 0
    STARTING = 1
    MPPT = 2
    EQUALIZE = 3
    BOOST = 4
    FLOAT = 5
    CURRENT_LIMITING = 6


CHARGE_STAGE_OPTIONS = [stage.name.lower() for stage in ChargeStage]

FAULT_BITS: dict[int, str] = {
    0: "battery_over_discharge",
    1: "battery_over_voltage",
    2: "battery_under_voltage_warning",
    3: "load_short_circuit",
    4: "load_overload",
    5: "controller_over_temperature",
    6: "ambient_over_temperature",
    7: "pv_overload",
    8: "pv_short_circuit",
    9: "pv_over_voltage",
    12: "pv_reverse_polarity",
    13: "battery_reverse_polarity",
}


def decode_faults(value: int) -> list[str]:
    """Return fault names for set bits; unknown bits become ``bit_<n>``."""
    return [FAULT_BITS.get(bit, f"bit_{bit}") for bit in range(16) if value >> bit & 1]


def _ascii(registers: list[int]) -> str:
    raw = b"".join(reg.to_bytes(2, "big") for reg in registers)
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Parsed device-info block (0x000A x 16)."""

    model: str
    firmware: str
    layout: int
    password_enabled: bool
    rated_current: int
    raw: tuple[int, ...] = field(repr=False)

    @property
    def dual_battery(self) -> bool:
        """Same rule as ``MainActivity.Response``."""
        if self.layout != 1:
            return False
        return "100F" not in self.model and "80F" not in self.model


def parse_device_info(regs: list[int]) -> DeviceInfo:
    if len(regs) < 15:
        raise ValueError(f"device info needs at least 15 registers, got {len(regs)}")
    return DeviceInfo(
        model=_ascii(regs[2:10]),
        firmware=f"{regs[10] / 100:.2f}",
        layout=regs[14],
        password_enabled=len(regs) > 15 and regs[15] == 1,
        rated_current=regs[0] >> 8,
        raw=tuple(regs),
    )


@dataclass(frozen=True, slots=True)
class ControllerData:
    """One poll's worth of normalized values. ``None`` means not available."""

    battery_soc: int | None = None
    battery_voltage: float | None = None
    charge_current: float | None = None
    charge_power: int | None = None
    controller_temperature: int | None = None
    battery_temperature: int | None = None
    load_voltage: float | None = None
    load_current: float | None = None
    load_power: int | None = None
    pv_voltage: float | None = None
    load_on: bool | None = None
    charge_stage: str | None = None
    fault_code: int | None = None
    faults: tuple[str, ...] = ()
    running_days: int | None = None
    total_charge_energy: int | None = None
    total_discharge_energy: int | None = None
    today_charge_energy: int | None = None
    today_discharge_energy: int | None = None
    today_max_charge_power: int | None = None
    today_max_battery_voltage: float | None = None
    today_min_battery_voltage: float | None = None
    load_manual_mode: bool | None = None
    raw_unknown: tuple[int, ...] = ()


def _stage_name(value: int) -> str | None:
    try:
        return ChargeStage(value).name.lower()
    except ValueError:
        return None


def parse_single_live(regs: list[int]) -> dict[str, object]:
    """Real-time block 0x0101 x 22, single-battery layout (doc §6)."""
    if len(regs) < 19:
        raise ValueError(f"real-time block needs 19+ registers, got {len(regs)}")
    return {
        "battery_soc": regs[0],
        "battery_voltage": round(regs[1] * 0.1, 1),
        "charge_current": round(regs[2] * 0.01, 2),
        "charge_power": regs[3],
        # App reads both bytes unsigned; signedness below 0 °C is unverified.
        "controller_temperature": regs[4] >> 8,
        "battery_temperature": regs[4] & 0xFF,
        "load_voltage": round(regs[5] * 0.1, 1),
        "load_current": round(regs[6] * 0.01, 2),
        "load_power": regs[7],
        "pv_voltage": round(regs[8] * 0.1, 1),
        "raw_unknown": tuple(regs[9:12]),
        "load_on": (regs[12] >> 8) != 0,
        "charge_stage": _stage_name(regs[12] & 0xFF),
        "fault_code": regs[13],
        "faults": tuple(decode_faults(regs[13])),
        "running_days": regs[14],
        "total_charge_energy": u32(regs[15], regs[16]),
        "total_discharge_energy": u32(regs[17], regs[18]),
    }


def parse_today(regs: list[int]) -> dict[str, object]:
    """Today block 0x0400 x 5 (doc §7)."""
    if len(regs) < 5:
        raise ValueError(f"today block needs 5 registers, got {len(regs)}")
    return {
        "today_charge_energy": regs[0],
        "today_discharge_energy": regs[1],
        "today_max_charge_power": regs[2],
        "today_max_battery_voltage": round(regs[3] * 0.1, 1),
        "today_min_battery_voltage": round(regs[4] * 0.1, 1),
    }


def parse_load_state(regs: list[int]) -> dict[str, object]:
    """Load register 0x0121 (doc §8). The high byte duplicates load_on."""
    return {"load_manual_mode": (regs[0] & 0xFF) == 0}


@dataclass(frozen=True, slots=True)
class Profile:
    """A register layout: which blocks to poll and how to parse each."""

    key: str
    description: str
    blocks: tuple[Block, ...]
    parsers: dict[str, Callable[[list[int]], dict[str, object]]]

    def build(self, block_regs: dict[str, list[int]]) -> ControllerData:
        """Merge parsed blocks into one :class:`ControllerData`. Missing blocks are skipped."""
        values: dict[str, object] = {}
        for block in self.blocks:
            regs = block_regs.get(block.key)
            if regs is not None:
                values.update(self.parsers[block.key](regs))
        return ControllerData(**values)  # type: ignore[arg-type]


SINGLE_BATTERY = Profile(
    key="single_battery",
    description="ChargePro single-battery MPPT (e.g. BougeRV 40A)",
    blocks=(
        Block("live", 0x0101, 22),
        Block("today", 0x0400, 5),
        Block("load", 0x0121, 1),
    ),
    parsers={"live": parse_single_live, "today": parse_today, "load": parse_load_state},
)

PROFILES: dict[str, Profile] = {SINGLE_BATTERY.key: SINGLE_BATTERY}


class UnsupportedDevice(Exception):
    """The controller uses a layout this integration does not implement yet."""


def select_profile(info: DeviceInfo) -> Profile:
    """Pick a profile the way the app does (``MainActivity.Response``)."""
    if info.dual_battery:
        raise UnsupportedDevice(f"{info.model or 'device'} uses the dual-battery layout")
    return SINGLE_BATTERY
