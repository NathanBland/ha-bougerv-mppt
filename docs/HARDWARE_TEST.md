# First hardware test (Home Assistant + ESP32 Bluetooth proxy)

This is the checklist for the first run of v0.1.0b3 against a real controller. The goal is
to confirm the protocol and capture the data that settles the
[open questions](protocol-chargepro-3.0.0.md#open-questions). Nothing here writes to
the controller: the integration only sends Modbus function 0x03 (read holding
registers), and it never reads the password block (0x0310).

## 1. ESP32 Bluetooth proxy

Flash an ESP32 with ESPHome. The integration needs an **active** (connectable) proxy:

```yaml
esp32:
  board: esp32dev
  framework:
    type: esp-idf

esp32_ble_tracker:
  scan_parameters:
    active: true

bluetooth_proxy:
  active: true
```

Add the ESPHome device to Home Assistant, and place it within a few metres of the
controller for the first test. One active proxy can hold about three connections at once,
and this integration keeps one open all the time.

## 2. Install the integration

1. HACS → ⋮ → *Custom repositories* → `https://github.com/NathanBland/ha-bougerv-mppt`,
   category *Integration*.
2. Open *BougeRV MPPT (ChargePro)* in HACS and download it. v0.1.0b3 is a pre-release, so
   if HACS doesn't offer it, use ⋮ → *Redownload* and pick `v0.1.0b3` (or turn on *Show
   beta versions*).
3. Add debug logging to `configuration.yaml`, then restart Home Assistant:

   ```yaml
   logger:
     default: warning
     logs:
       custom_components.bougerv_mppt: debug
   ```

### If Home Assistant says it can't see the controller

The controller **stops advertising while any phone is connected**, so first force-quit
the ChargePro app (or turn the phone's Bluetooth off). Don't pair the controller from the
phone's Bluetooth settings: the app never pairs, and system pairing fails with an
invalid-PIN error. Home Assistant doesn't pair either.

Then open *Settings → System → Bluetooth* (or the Bluetooth integration's *Advertisement
monitor*) and search for the address or `ChargePro`:

- **Not listed:** no adapter or proxy hears it. Move the ESP32 closer, check the ESPHome
  logs show it online, and check the phone has really let go.
- **Listed, but the source isn't connectable** (setup shows "heard only through a passive
  scanner"): the proxy needs `bluetooth_proxy: active: true`.
- **Listed and connectable:** retry setup. If it still fails, capture the debug log.

## 3. Before adding the device

- **Close the ChargePro app** on every phone (force-quit it). The controller accepts one
  Bluetooth connection, so the app blocks Home Assistant and vice versa.
- With the app open on the phone, take screenshots of the home screen (voltages, current,
  SOC, temperatures, stage) and the history/statistics screen (today and totals). They are
  the reference values for step 5. Note the time.
- Then close the app.

## 4. Add the device

Check, in this order:

1. **Discovery.** Does *Settings → Devices & services* show *Discovered: BougeRV MPPT*?
   - Yes: confirm it. (Controllers advertise the name `ChargePro`; the app shows the same.)
   - No: go to *Add integration → BougeRV MPPT*. The list shows every connectable device,
     likely controllers first, marked ★. Find the controller by name or by signal strength (move the
     proxy closer to tell). If it isn't listed, pick *Enter an address manually* and type
     the address from the ESPHome logs or *Settings → Bluetooth → Advertisement monitor*.
2. **Errors you might see:**

   | Error | Meaning | Next step |
   |---|---|---|
   | Device not found | No adapter or proxy can see that address right now | Check the proxy is online and close by |
   | Could not connect | Connection failed | Close the ChargePro app; retry |
   | Not a ChargePro controller (abort or error) | Connected, but no valid answer to the device-info read | Capture debug logs (step 6) |
   | Unsupported model | The controller reports the dual-battery layout | Add it manually with **Force single-battery layout** ticked, then compare values carefully |

## 5. Compare against the app

Open the device page. Compare each entity with the app screenshots:

| Entity | Check |
|---|---|
| Battery voltage, Charge current, Charge power, Solar voltage | Within a reading or two of the app |
| Battery state of charge | Same % as the app |
| Controller / Battery temperature | Same °C (note the ambient temperature too) |
| Charge stage | Same stage name as the app |
| Load voltage / current / power, Load output | Match the app's load screen |
| Energy charged/discharged today, Peak charge power, Highest/Lowest battery voltage today | Match the app's statistics screen |
| Total energy charged / Total energy discharged | Which one matches the app's lifetime *charged* total? (open question 3) |
| Running days | Matches the app |

Values arrive about 10 s apart. If a value is off by 10× or 100×, that's a scaling error;
note the entity and both values.

## 6. Capture data to send back

Collect all of these, even if everything looks right:

1. **Diagnostics:** device page → ⋮ → *Download diagnostics*. It contains:
   - `advertisement`: the name, service UUIDs and manufacturer data (open question 4).
   - `device_info`: model, firmware, layout register `r[14]` (open question 5).
   - `fresh_reads`: every documented read-only register block, read at download time.
   - `poll_history`: the last ~15 minutes of raw polls, for spotting which registers move.
   Download it twice, a few minutes apart, ideally once with the sun on the panels and once
   with a load switched on.
2. **Unknown registers 0x010A–0x010C** (open question 1). Either enable the three disabled
   *Register 0x010A/B/C* diagnostic sensors on the device page and watch them, or run this
   in *Developer tools → Actions* with *Return response* ticked:

   ```yaml
   action: bougerv_mppt.read_registers
   data:
     config_entry_id: <pick the controller>
     address: 266   # 0x010A
     count: 3
   ```

   Try it with the load on and off, and in sun and shade, and note what changed.
3. **Temperatures below 0 °C** (open question 2): only if it gets that cold. Record the
   raw `live_0x0101` register 5 (index 4) from `poll_history`, alongside the real
   temperature.
4. **Debug log:** *Settings → System → Logs → Download full log*, or copy the
   `custom_components.bougerv_mppt` lines. Each poll logs `TX` (request) and `RX`
   (notification) frames in hex. If setup failed, these lines are the most useful thing.

Diagnostics hold the Bluetooth address and the readings, nothing else. Review before
sharing.

## 7. What each result tells us

| Open question | Answered by |
|---|---|
| 1. Registers 0x010A–0x010C | `read_registers` results and `poll_history`, compared with what changed |
| 2. Signed temperatures | `live_0x0101` index 4 below 0 °C |
| 3. Charge vs discharge totals | App lifetime totals vs the two *Total energy* sensors |
| 4. Advertised name, FFE0 advertised | Diagnostics `advertisement`, and whether discovery fired |
| 5. Layout register on the 40A | Diagnostics `device_info.layout`, and whether *Unsupported model* appeared |

## 8. Energy dashboard (after the values check out)

*Settings → Dashboards → Energy*:

- *Solar panels → Add solar production*: **Total energy charged** (or whichever total
  matched the app's charged total in step 5).
- *Individual devices*: **Total energy discharged** for the load output.

Don't add the *today* sensors as well, or energy is counted twice.
