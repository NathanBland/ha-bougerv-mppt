from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bougerv_mppt.core.client import CHAR_UUID, ChargeProClient
from custom_components.bougerv_mppt.core.modbus import ModbusError, append_crc
from custom_components.bougerv_mppt.core.models import UnsupportedDevice


def _response(regs: list[int]) -> bytes:
    data = b"".join(r.to_bytes(2, "big") for r in regs)
    return append_crc(bytes((0x01, 0x03, len(data))) + data)


def _info_regs(layout: int = 0) -> list[int]:
    model = b"MPPT-40A        "
    regs = [0x2800, 0] + [int.from_bytes(model[i : i + 2], "big") for i in range(0, 16, 2)]
    return regs + [105, 0, 0, 0, layout, 0]


class FakeBleakClient:
    """Answers reads from a register map, in 20-byte notification chunks."""

    def __init__(self, registers: dict[int, int], *, drop_first: int = 0) -> None:
        self.registers = registers
        self.writes: list[tuple[bytes, bool]] = []
        self.callback = None
        self.drop_first = drop_first
        self.is_connected = True
        self.char = SimpleNamespace(uuid=CHAR_UUID, properties=["read", "write", "notify"])
        self.services = SimpleNamespace(
            get_characteristic=lambda uuid: self.char if uuid == CHAR_UUID else None
        )

    async def start_notify(self, _char, callback) -> None:
        self.callback = callback

    async def stop_notify(self, _char) -> None:
        self.callback = None

    async def write_gatt_char(self, _char, data: bytes, response: bool) -> None:
        self.writes.append((bytes(data), response))
        if self.drop_first:
            self.drop_first -= 1
            return
        address = int.from_bytes(data[2:4], "big")
        count = int.from_bytes(data[4:6], "big")
        frame = _response([self.registers.get(address + i, 0) for i in range(count)])
        loop = asyncio.get_running_loop()
        for i in range(0, len(frame), 20):
            loop.call_soon(self.callback, self.char, bytearray(frame[i : i + 20]))


def _registers(layout: int = 0) -> dict[int, int]:
    regs = {0x000A + i: v for i, v in enumerate(_info_regs(layout))}
    live = [76, 128, 500, 64, (30 << 8) | 20, 127, 100, 12, 190, 0, 0, 0]
    live += [0x0105, 0, 3, 0, 900, 0, 400]
    regs.update({0x0101 + i: v for i, v in enumerate(live)})
    regs.update({0x0400 + i: v for i, v in enumerate([120, 40, 200, 143, 124])})
    regs[0x0121] = 0x0100
    return regs


async def _no_sleep(_s: float) -> None:
    return None


async def test_start_and_poll() -> None:
    fake = FakeBleakClient(_registers())
    client = ChargeProClient(fake, timeout=0.5, sleep=_no_sleep)  # type: ignore[arg-type]
    info = await client.start()
    assert info.model == "MPPT-40A"
    assert info.firmware == "1.05"
    data, raw = await client.poll()
    assert data.battery_soc == 76
    assert data.charge_stage == "float"
    assert data.load_on is True
    assert data.total_charge_energy == 900
    assert data.today_min_battery_voltage == 12.4
    assert set(raw) == {"live", "today", "load"}
    assert fake.writes[0] == (bytes.fromhex("0103000A00106404"), True)
    assert fake.writes[1][0] == bytes.fromhex("0103010100169438")


async def test_retry_after_timeout() -> None:
    fake = FakeBleakClient(_registers(), drop_first=1)
    client = ChargeProClient(fake, timeout=0.05, sleep=_no_sleep)  # type: ignore[arg-type]
    info = await client.start()
    assert info.model == "MPPT-40A"
    assert len(fake.writes) == 2


async def test_gives_up_after_attempts() -> None:
    fake = FakeBleakClient(_registers(), drop_first=5)
    client = ChargeProClient(fake, timeout=0.05, sleep=_no_sleep)  # type: ignore[arg-type]
    with pytest.raises(TimeoutError):
        await client.start()


async def test_dual_battery_rejected() -> None:
    fake = FakeBleakClient(_registers(layout=1))
    client = ChargeProClient(fake, timeout=0.5, sleep=_no_sleep)  # type: ignore[arg-type]
    with pytest.raises(UnsupportedDevice):
        await client.start()


async def test_missing_characteristic() -> None:
    fake = FakeBleakClient(_registers())
    fake.services = SimpleNamespace(get_characteristic=lambda _uuid: None)
    client = ChargeProClient(fake)  # type: ignore[arg-type]
    with pytest.raises(ModbusError):
        await client.start()
