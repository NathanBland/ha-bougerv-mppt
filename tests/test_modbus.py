from __future__ import annotations

import pytest

from custom_components.bougerv_mppt.core.modbus import (
    ModbusError,
    ModbusExceptionResponse,
    ResponseAssembler,
    append_crc,
    build_read,
    crc_ok,
    parse_read_response,
    u32,
)

# Hard-coded frames from com.ruijing.mppt.util.Command (ChargePro 3.0.0).
APP_FRAMES = {
    "HOME_DATA_OLD": "01 03 01 01 00 16 94 38",
    "HOME_DATA": "01 03 01 00 00 17 04 38",
    "BULETOOTH": "01 03 00 0A 00 10 64 04",
    "TODAY_DATA": "01 03 04 00 00 05 84 F9",
    "SETTING": "01 03 02 00 00 18 44 78",
    "Forced_Load_Short": "01 03 01 21 00 01 D5 FC",
    "MODE_SIZE": "01 03 00 0B 00 01 F5 C8",
    "Forced_CHECK1_OPEN": "01 06 01 20 00 01 48 3C",
    "Restore_Factory_Setting": "01 78 FF FF FF FF A0 54",
    "Clear_historical_data": "01 79 FF FF FF FF 9D 94",
}


@pytest.mark.parametrize("name", APP_FRAMES)
def test_crc_matches_app_frames(name: str) -> None:
    frame = bytes.fromhex(APP_FRAMES[name])
    assert append_crc(frame[:-2]) == frame
    assert crc_ok(frame)


@pytest.mark.parametrize(
    ("address", "count", "name"),
    [
        (0x0101, 22, "HOME_DATA_OLD"),
        (0x000A, 16, "BULETOOTH"),
        (0x0400, 5, "TODAY_DATA"),
        (0x0121, 1, "Forced_Load_Short"),
    ],
)
def test_build_read_matches_app(address: int, count: int, name: str) -> None:
    assert build_read(address, count) == bytes.fromhex(APP_FRAMES[name])


def test_build_read_rejects_bad_count() -> None:
    with pytest.raises(ValueError):
        build_read(0x0101, 0)
    with pytest.raises(ValueError):
        build_read(0x0101, 126)


def _response(regs: list[int]) -> bytes:
    data = b"".join(r.to_bytes(2, "big") for r in regs)
    return append_crc(bytes((0x01, 0x03, len(data))) + data)


def test_parse_read_response_roundtrip() -> None:
    regs = [0, 1, 0xFFFF, 0x1234]
    assert parse_read_response(_response(regs), 4) == regs


def test_parse_read_response_rejects_wrong_count() -> None:
    with pytest.raises(ModbusError):
        parse_read_response(_response([1, 2]), 3)


def test_parse_read_response_rejects_bad_crc() -> None:
    frame = bytearray(_response([1, 2]))
    frame[-1] ^= 0xFF
    with pytest.raises(ModbusError, match="CRC"):
        parse_read_response(bytes(frame), 2)


def test_parse_exception_response() -> None:
    frame = append_crc(bytes((0x01, 0x83, 0x02)))
    with pytest.raises(ModbusExceptionResponse) as info:
        parse_read_response(frame, 1)
    assert info.value.code == 2


def test_assembler_joins_chunks() -> None:
    frame = _response(list(range(22)))  # 49 bytes, longer than a default 20-byte ATT payload
    assembler = ResponseAssembler()
    chunks = [frame[i : i + 20] for i in range(0, len(frame), 20)]
    results = [assembler.feed(chunk) for chunk in chunks]
    assert results[:-1] == [None] * (len(chunks) - 1)
    assert results[-1] == frame


def test_assembler_returns_exception_frame() -> None:
    frame = append_crc(bytes((0x01, 0x83, 0x02)))
    assert ResponseAssembler().feed(frame) == frame


def test_assembler_overflow_raises_and_resets() -> None:
    assembler = ResponseAssembler()
    with pytest.raises(ModbusError):
        assembler.feed(bytes([0x01, 0x03, 0xFF]) + bytes(300))
    assert assembler.feed(_response([7])) == _response([7])


def test_u32_high_word_first() -> None:
    assert u32(0x0001, 0x0002) == 0x00010002
