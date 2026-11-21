"""Constants for the BougeRV MPPT integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "bougerv_mppt"
MANUFACTURER = "BougeRV"

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"

# The vendor app polls about every 5 s; 10 s is gentler on the BLE link.
UPDATE_INTERVAL = timedelta(seconds=10)
CONNECT_TIMEOUT = 20.0

CONF_FORCE_SINGLE_LAYOUT = "force_single_layout"

# Raw polls kept in memory for the diagnostics download (10 s x 90 = 15 min).
POLL_HISTORY = 90

SERVICE_READ_REGISTERS = "read_registers"

# Extra read-only blocks fetched when diagnostics are downloaded (doc §4-§9). The
# password block 0x0310 is deliberately not read.
DIAGNOSTIC_BLOCKS: tuple[tuple[str, int, int], ...] = (
    ("device_info_0x000A", 0x000A, 16),
    ("dual_layout_0x0100", 0x0100, 23),
    ("live_0x0101", 0x0101, 22),
    ("settings_0x0200", 0x0200, 24),
    ("charging_switch_0x0210", 0x0210, 1),
    ("load_timers_0x0300", 0x0300, 12),
    ("today_0x0400", 0x0400, 5),
    ("load_0x0121", 0x0121, 1),
)
