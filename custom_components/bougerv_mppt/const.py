"""Constants for the BougeRV MPPT integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "bougerv_mppt"
MANUFACTURER = "BougeRV"

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"

# The vendor app polls about every 5 s; 10 s is gentler on the BLE link.
UPDATE_INTERVAL = timedelta(seconds=10)
CONNECT_TIMEOUT = 20.0
