"""bleak transport for ChargePro controllers: one request in flight at a time."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .modbus import ModbusError, ResponseAssembler, build_read, parse_read_response
from .models import (
    DEVICE_INFO_BLOCK,
    SINGLE_BATTERY,
    Block,
    ControllerData,
    DeviceInfo,
    Profile,
    UnsupportedDevice,
    parse_device_info,
)
from .models import select_profile as _select_profile

_LOGGER = logging.getLogger(__name__)

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
REQUEST_TIMEOUT = 3.0
REQUEST_ATTEMPTS = 2


class ChargeProClient:
    """Speak Modbus over FFE1 on an already-connected :class:`BleakClient`.

    Connection management is left to the caller (Home Assistant uses
    bleak-retry-connector, the CLI uses a plain ``BleakClient``).
    """

    def __init__(
        self,
        client: BleakClient,
        *,
        timeout: float = REQUEST_TIMEOUT,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._sleep = sleep
        self._assembler = ResponseAssembler()
        self._lock = asyncio.Lock()
        self._pending: asyncio.Future[bytes] | None = None
        self._char: BleakGATTCharacteristic | None = None
        self.device_info: DeviceInfo | None = None
        self.profile: Profile | None = None

    async def start(self, *, force_single_layout: bool = False) -> DeviceInfo:
        """Subscribe to notifications, read device info, choose the profile.

        ``force_single_layout`` uses the single-battery layout even when the device
        reports the dual-battery layout (for testing on unconfirmed hardware).
        """
        char = self._client.services.get_characteristic(CHAR_UUID)
        if char is None:
            raise ModbusError("characteristic FFE1 not found")
        self._char = char
        await self._client.start_notify(char, self._on_notify)
        regs = await self.read_block(DEVICE_INFO_BLOCK)
        self.device_info = parse_device_info(regs)
        _LOGGER.debug("Device info %s", self.device_info)
        try:
            self.profile = _select_profile(self.device_info)
        except UnsupportedDevice:
            if not force_single_layout:
                raise
            _LOGGER.warning(
                "%s reports layout %s; forcing the single-battery layout as configured",
                self.device_info.model,
                self.device_info.layout,
            )
            self.profile = SINGLE_BATTERY
        return self.device_info

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        pending = self._pending
        _LOGGER.debug("RX %s", bytes(data).hex(" "))
        if pending is None or pending.done():
            _LOGGER.debug("Ignoring unsolicited notification")
            return
        try:
            frame = self._assembler.feed(bytes(data))
        except ModbusError as err:
            pending.set_exception(err)
            return
        if frame is not None:
            pending.set_result(frame)

    async def read_registers(self, address: int, count: int) -> list[int]:
        """Read holding registers, retrying once on timeout or a bad frame."""
        request = build_read(address, count)
        async with self._lock:
            last_error: Exception | None = None
            for attempt in range(REQUEST_ATTEMPTS):
                if attempt:
                    await self._sleep(0.2)
                loop = asyncio.get_running_loop()
                self._assembler.reset()
                self._pending = loop.create_future()
                try:
                    await self._write(request)
                    frame = await asyncio.wait_for(self._pending, self._timeout)
                    return parse_read_response(frame, count)
                except (TimeoutError, ModbusError) as err:
                    last_error = err
                    _LOGGER.debug("Read %#06x x%d failed: %r", address, count, err)
                finally:
                    self._pending = None
            assert last_error is not None
            raise last_error

    async def read_block(self, block: Block) -> list[int]:
        return await self.read_registers(block.address, block.count)

    async def poll(self) -> tuple[ControllerData, dict[str, list[int]]]:
        """Read every block of the selected profile. Returns parsed data and raw registers."""
        if self.profile is None:
            raise RuntimeError("call start() first")
        raw = {block.key: await self.read_block(block) for block in self.profile.blocks}
        return self.profile.build(raw), raw

    async def _write(self, data: bytes) -> None:
        assert self._char is not None
        # The app writes with response (BluetoothKit ``write``); fall back if unsupported.
        response = "write" in self._char.properties
        _LOGGER.debug("TX %s", data.hex(" "))
        await self._client.write_gatt_char(self._char, data, response=response)

    async def stop(self) -> None:
        if self._char is not None and self._client.is_connected:
            try:
                await self._client.stop_notify(self._char)
            except Exception:  # noqa: BLE001 - best effort during teardown
                _LOGGER.debug("stop_notify failed", exc_info=True)
