"""Command-line tool for checking a controller without Home Assistant.

    bougerv-mppt scan
    bougerv-mppt read AA:BB:CC:DD:EE:FF [--watch 10] [--raw]
    bougerv-mppt regs AA:BB:CC:DD:EE:FF 0x0101 22

Read-only: only Modbus function 0x03 is ever sent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from bleak import BleakClient, BleakScanner

from custom_components.bougerv_mppt.core.client import SERVICE_UUID, ChargeProClient


async def _scan(scan_seconds: float) -> int:
    found = await BleakScanner.discover(timeout=scan_seconds, return_adv=True)
    for device, adv in sorted(found.values(), key=lambda item: -item[1].rssi):
        has_ffe0 = SERVICE_UUID in [u.lower() for u in adv.service_uuids]
        marker = "FFE0" if has_ffe0 else "    "
        name = adv.local_name or device.name or ""
        print(f"{marker}  {device.address}  {adv.rssi:4d} dBm  {name}")
    return 0


async def _with_client(
    address: str, connect_seconds: float, action, *, require_info: bool = True
) -> int:
    try:
        async with BleakClient(address, timeout=connect_seconds) as bleak_client:
            client = ChargeProClient(bleak_client)
            try:
                info = await client.start()
                summary = f"# {info.model} firmware {info.firmware} layout {info.layout}"
                print(summary, file=sys.stderr)
            except Exception as err:  # noqa: BLE001 - report and continue for raw reads
                print(f"# device info failed: {type(err).__name__}: {err}", file=sys.stderr)
                if require_info:
                    return 1
            return await action(client)
    except Exception as err:  # noqa: BLE001
        # bleak timeouts often have empty messages; print the type.
        print(f"error: {type(err).__name__}: {err}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bougerv-mppt", description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=20.0, help="connect/scan timeout (s)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="list nearby BLE devices; FFE0 marks likely controllers")
    read = sub.add_parser("read", help="read and print all values")
    read.add_argument("address")
    read.add_argument("--watch", type=float, metavar="SECONDS", help="repeat every N seconds")
    read.add_argument("--raw", action="store_true", help="also print raw registers")
    regs = sub.add_parser("regs", help="read arbitrary holding registers (function 0x03)")
    regs.add_argument("address")
    regs.add_argument("start", type=lambda v: int(v, 0))
    regs.add_argument("count", type=int)
    args = parser.parse_args(argv)

    if args.command == "scan":
        return asyncio.run(_scan(args.timeout))

    if args.command == "read":

        async def _read_action(client: ChargeProClient) -> int:
            while True:
                data, raw = await client.poll()
                out = {"data": asdict(data)}
                if args.raw:
                    out["raw"] = {k: [f"{r:04X}" for r in v] for k, v in raw.items()}
                print(json.dumps(out, indent=2), flush=True)
                if not args.watch:
                    return 0
                await asyncio.sleep(args.watch)

        return asyncio.run(_with_client(args.address, args.timeout, _read_action))

    async def _regs_action(client: ChargeProClient) -> int:
        values = await client.read_registers(args.start, args.count)
        for offset, value in enumerate(values):
            print(f"0x{args.start + offset:04X}  {value:04X}  {value:6d}")
        return 0

    return asyncio.run(_with_client(args.address, args.timeout, _regs_action, require_info=False))


if __name__ == "__main__":
    raise SystemExit(main())
