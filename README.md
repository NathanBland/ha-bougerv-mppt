# BougeRV MPPT (ChargePro) for Home Assistant

Read-only Home Assistant integration for BougeRV MPPT solar charge controllers that use
the **ChargePro+ 2.0** app (built for the BougeRV 40A MPPT). It talks to the controller
directly over Bluetooth LE, through a local adapter or an ESPHome Bluetooth proxy. No
cloud, no account.

> **Status: v0.1.0b2 (beta), untested on hardware.** The protocol was worked out by
> statically analysing ChargePro+ 2.0 version 3.0.0. See
> [docs/protocol-chargepro-3.0.0.md](docs/protocol-chargepro-3.0.0.md) for the protocol
> and the open questions that still need a real controller to answer, and
> [docs/HARDWARE_TEST.md](docs/HARDWARE_TEST.md) for how to capture the data that answers
> them.

## What you get

| Group | Entities |
|---|---|
| Battery | state of charge, voltage, charge current, charge power, battery temperature |
| Solar | solar (PV) voltage, charge stage (not charging / starting / MPPT / equalize / boost / float / current limiting) |
| Load | load voltage, current, power, load output on/off, load mode (diagnostic) |
| Controller | controller temperature, faults (text, with `fault_code` and `faults` attributes), fault (problem binary sensor), running days (diagnostic) |
| Today | energy charged, energy discharged, peak charge power, highest and lowest battery voltage |
| Lifetime | total energy charged, total energy discharged |
| Diagnostics | raw registers 0x010A–0x010C (disabled by default; the app never shows them, likely PV current/power) |

The device page shows the model and firmware read from the controller.

Nothing is written to the controller. The app's write commands (load on/off, settings,
factory reset) are documented but not implemented.

## Install

### HACS (custom repository)

1. HACS → ⋮ → *Custom repositories* → add this repository's URL, category *Integration*.
2. Install **BougeRV MPPT (ChargePro)** and restart Home Assistant.

### Manual

Copy `custom_components/bougerv_mppt` into `<config>/custom_components/` and restart.

## Set up

Close the ChargePro app first: the controller accepts only one Bluetooth connection, and
Home Assistant keeps its connection open while it polls (every 10 s).

- **Discovery:** controllers advertise the name `ChargePro`, and Home Assistant offers
  those, plus devices that advertise the `FFE0` service. That's a
  generic BLE serial service also used by other gadgets, so setup connects and reads the
  controller's device info before adding it. Devices that don't answer like a ChargePro
  controller are dropped.
- **Manual:** *Settings → Devices & services → Add integration → BougeRV MPPT* lists every
  connectable Bluetooth device nearby (likely controllers marked ★ and listed first), or lets you type an address.

Dual-battery ChargePro controllers use a different register layout and are rejected with
"unsupported model" for now (see [Adding models](#adding-models)). For testing, the manual
address step has a **Force single-battery layout** option that reads them with the
single-battery layout anyway.

### Troubleshooting tools

- **Diagnostics** (device page → ⋮ → Download diagnostics): the advertisement, device info,
  a fresh read of every documented read-only register block, and the last ~15 minutes of
  raw polls.
- **`bougerv_mppt.read_registers` action** (Developer tools → Actions, tick *Return
  response*): reads any holding registers with Modbus function 0x03. Nothing is ever
  written to the controller.
- **Debug logging** shows every frame sent and received:

  ```yaml
  logger:
    logs:
      custom_components.bougerv_mppt: debug
  ```

## Energy dashboard

The energy sensors use `device_class: energy` and `state_class: total_increasing` in Wh
(displayed in kWh), as the
[Energy dashboard](https://www.home-assistant.io/docs/energy/) requires. Power sensors use
`state_class: measurement`, and state of charge is a `battery` sensor.

A suggested mapping for an off-grid 12 V system:

| Energy dashboard | Sensor |
|---|---|
| Solar production | **Total energy charged** (energy the controller put into the battery from solar) |
| Individual device | **Total energy discharged** (energy delivered to the controller's DC load output) |

Notes:

- Use the **lifetime** totals in the dashboard, not the "today" counters. Both work as
  `total_increasing` (a reset to 0 at midnight is fine), but adding both double-counts.
- Charged energy is measured at the battery side, so it is slightly lower than the panel's
  raw output.
- Discharged energy covers only the controller's own load terminals. Loads wired straight
  to the battery (an inverter, for example) aren't included.
- Which lifetime register is "charged" and which is "discharged" was inferred from the app
  and still needs confirming on hardware. If the numbers look swapped, please open an
  issue.

## Command-line tool

The Python package includes a read-only CLI for checking a controller from a laptop:

```bash
uv venv && uv pip install -e '.[test]'
.venv/bin/bougerv-mppt scan                         # FFE0 marks likely controllers
.venv/bin/bougerv-mppt read AA:BB:CC:DD:EE:FF --raw  # all values + raw registers
.venv/bin/bougerv-mppt regs AA:BB:CC:DD:EE:FF 0x0101 22
```

Disable the Home Assistant config entry while you use it, or the two will fight over the
single connection. On macOS, use the CoreBluetooth UUID that `scan` prints instead of a MAC
address.

## How it works

Modbus-RTU over BLE: requests go to characteristic `FFE1` on service `FFE0` (slave
`0x01`, function `0x03`, CRC-16/MODBUS), and replies come back as notifications on the
same characteristic. Each poll reads three blocks: real-time `0x0101` × 22, today
`0x0400` × 5, load `0x0121` × 1. Full details, with app class/method references, are in
[docs/protocol-chargepro-3.0.0.md](docs/protocol-chargepro-3.0.0.md).

## Adding models

`custom_components/bougerv_mppt/core/` has no Home Assistant dependency.

- `core/models.py` holds a `Profile` per register layout: the blocks to read and a parser.
  `select_profile()` picks one from the device-info block, using the same rule as the
  app.
- To add the ChargePro dual-battery layout (`0x0100` × 23), write its parser, add a
  profile, and return it from `select_profile()` instead of raising `UnsupportedDevice`.
  New `ControllerData` fields then need entity descriptions in `sensor.py`.

## Development

```bash
uv venv && uv pip install -e '.[test]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                    # protocol, client and static scaffold tests
```

Tests that run inside a real Home Assistant core (config flow, setup, entity states):

```bash
uv venv --python 3.13 .venv-ha
uv pip install --python .venv-ha/bin/python pytest-homeassistant-custom-component -e .
.venv-ha/bin/pytest tests_ha
```

## Disclaimer

Not affiliated with BougeRV or the ChargePro app's developers. Protocol details come from
interoperability analysis of the publicly distributed Android app.

## License

MIT
