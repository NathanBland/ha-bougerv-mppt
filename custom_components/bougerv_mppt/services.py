"""``bougerv_mppt.read_registers``: read any holding registers, for protocol checks.

Read-only: only Modbus function 0x03 is sent. Use it from Developer tools → Actions with
"Return response" to look at registers the integration doesn't decode yet.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, SERVICE_READ_REGISTERS

ATTR_CONFIG_ENTRY = "config_entry_id"
ATTR_ADDRESS = "address"
ATTR_COUNT = "count"

SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): cv.string,
        vol.Required(ATTR_ADDRESS): vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFF)),
        vol.Optional(ATTR_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=64)),
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    async def _read_registers(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY])
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError("Not a BougeRV MPPT config entry")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("The config entry is not loaded")
        start = call.data[ATTR_ADDRESS]
        count = call.data[ATTR_COUNT]
        try:
            regs = await entry.runtime_data.coordinator.async_read_registers(start, count)
        except Exception as err:
            raise HomeAssistantError(f"Read failed: {type(err).__name__}: {err}") from err
        return {
            "start": f"0x{start:04X}",
            "registers": {
                f"0x{start + i:04X}": {"hex": f"{reg:04X}", "value": reg}
                for i, reg in enumerate(regs)
            },
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REGISTERS,
        _read_registers,
        schema=SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
