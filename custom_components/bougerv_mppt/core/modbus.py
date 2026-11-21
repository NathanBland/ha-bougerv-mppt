"""Modbus-RTU framing as used by ChargePro controllers over BLE.

See docs/protocol-chargepro-3.0.0.md §2. Pure Python, no Home Assistant or bleak imports.
"""

from __future__ import annotations

SLAVE_ID = 0x01
FC_READ_HOLDING = 0x03
_EXCEPTION_FLAG = 0x80


class ModbusError(Exception):
    """A response could not be used."""


class ModbusExceptionResponse(ModbusError):
    """The device answered with a Modbus exception code."""

    def __init__(self, function: int, code: int) -> None:
        super().__init__(f"Modbus exception {code:#04x} for function {function:#04x}")
        self.function = function
        self.code = code


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS (reflected poly 0xA001, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def append_crc(payload: bytes) -> bytes:
    """Return payload with its CRC appended, low byte first."""
    crc = crc16(payload)
    return payload + bytes((crc & 0xFF, crc >> 8))


def crc_ok(frame: bytes) -> bool:
    """True if the last two bytes are the CRC of the rest."""
    return len(frame) >= 4 and append_crc(frame[:-2])[-2:] == frame[-2:]


def build_read(address: int, count: int, slave: int = SLAVE_ID) -> bytes:
    """Build a function 0x03 (read holding registers) request."""
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"address out of range: {address}")
    if not 1 <= count <= 125:
        raise ValueError(f"count out of range: {count}")
    return append_crc(
        bytes((slave, FC_READ_HOLDING, address >> 8, address & 0xFF, count >> 8, count & 0xFF))
    )


class ResponseAssembler:
    """Collect BLE notification chunks until they form one CRC-valid frame.

    Mirrors the app (``BluCommt$2.onNotify``): append chunks until the buffer ends with
    the CRC of what precedes it. Also accepts a 5-byte exception frame.
    """

    MAX_LENGTH = 256

    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, chunk: bytes) -> bytes | None:
        """Add a chunk; return the complete frame once one is available."""
        self._buffer.extend(chunk)
        if len(self._buffer) > self.MAX_LENGTH:
            self._buffer.clear()
            raise ModbusError("response too long without a valid CRC")
        buf = bytes(self._buffer)
        if len(buf) >= 5 and buf[1] & _EXCEPTION_FLAG and crc_ok(buf[:5]):
            self._buffer.clear()
            return buf[:5]
        if len(buf) >= 5 and len(buf) >= 3 + buf[2] + 2 and crc_ok(buf[: 3 + buf[2] + 2]):
            frame = buf[: 3 + buf[2] + 2]
            self._buffer.clear()
            return frame
        return None


def parse_read_response(frame: bytes, count: int, slave: int = SLAVE_ID) -> list[int]:
    """Validate a 0x03 response frame and return its registers as unsigned ints."""
    if not crc_ok(frame):
        raise ModbusError("bad CRC")
    if frame[0] != slave:
        raise ModbusError(f"unexpected slave id {frame[0]:#04x}")
    if frame[1] == FC_READ_HOLDING | _EXCEPTION_FLAG:
        raise ModbusExceptionResponse(FC_READ_HOLDING, frame[2])
    if frame[1] != FC_READ_HOLDING:
        raise ModbusError(f"unexpected function {frame[1]:#04x}")
    byte_count = frame[2]
    if byte_count != count * 2 or len(frame) != 3 + byte_count + 2:
        raise ModbusError(f"expected {count} registers, got {byte_count} bytes")
    data = frame[3 : 3 + byte_count]
    return [int.from_bytes(data[i : i + 2], "big") for i in range(0, byte_count, 2)]


def u32(high: int, low: int) -> int:
    """Combine two registers, high word first."""
    return (high << 16) | low
