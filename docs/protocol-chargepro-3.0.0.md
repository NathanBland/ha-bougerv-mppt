# ChargePro+ 2.0 3.0.0 — BLE protocol (BougeRV 40A MPPT)

Static analysis of the vendor Android app. Nothing here has been checked against
real hardware yet; see [Open questions](#open-questions).

## Source

| | |
|---|---|
| Package | ChargePro+ 2.0 3.0.0 (APKPure XAPK), package `com.paoding.heli_solar_app`, versionCode 300 |
| Analysed APK | base `com.paoding.heli_solar_app.apk`, SHA-256 `093429187cc3135578cf667d6ffdcf292ec44bd5831f7a21b6316f648e3f6a3d` |
| Tooling | REA with JADX (jadx-headless-mcp 0.7.1). The app is native Java (single `classes.dex`, no Flutter/`libapp.so`). |
| Vendor code | `com.ruijing.mppt.*`; BLE through the inuker BluetoothKit library (`com.inuker.bluetooth.library`) |

Evidence tags: **[J]** decompiled Java (class/method named), **[V]** verified here by
computation (e.g. CRC against app constants). Confidence: **Confirmed** (byte-exact or
directly visible in code), **Inferred** (reasoned from usage), **Unknown**.

Decompiled code and APK strings were treated as untrusted data.

## 1. Transport

| Item | Value | Evidence |
|---|---|---|
| GATT service | `0000ffe0-0000-1000-8000-00805f9b34fb` | [J] `com.ruijing.mppt.view.RightLayout` connect/notify setup, `BluCommt` constants — Confirmed |
| Write + notify characteristic | `0000ffe1-0000-1000-8000-00805f9b34fb` (app also probes `ffe2`) | [J] `BluCommt.send` → `ClientManager.write(mac, service, ffe1, bytes)`; `BluCommt` notify registration — Confirmed |
| Write type | BluetoothKit `write` (write **with** response) | [J] `BluCommt.send` — Confirmed |
| MTU | app requests 90 | [J] connect path in `RightLayout` — Confirmed |
| Connect | 5000 ms timeout, 1 retry, no bonding / PIN / auth handshake | [J] `BleConnectOptions` in `RightLayout` — Confirmed |
| Scan filter | none: every device with a name other than `"NULL"` is listed | [J] `RightLayout$3.onDeviceFounded` — Confirmed |

The device name the controller advertises and whether it puts FFE0 in its advertisement
are not known from the app. FFE0/FFE1 is the common "HM-10 style" UART service, so any
discovery match must be confirmed by reading the device-info block (§5).

## 2. Framing: Modbus-RTU over BLE

| Item | Value | Evidence |
|---|---|---|
| Slave address | `0x01` | [J] every constant in `com.ruijing.mppt.util.Command` — Confirmed |
| Function codes | `0x03` read holding, `0x06` write single, `0x10` write multiple, `0x78` factory reset, `0x79` clear history | [J] `Command` — Confirmed |
| CRC | CRC-16/MODBUS (poly 0xA001 reflected, init 0xFFFF), appended **low byte first** | [V] recomputed for 7 `Command` frames, all match — Confirmed |
| Register byte order | big-endian 16-bit words | [J] `Utils.getTen` on 4-hex-char slices — Confirmed |
| 32-bit values | two registers, high word first (hex strings concatenated) | [J] `MainActivity.Response` → `HistoryFragment.setDays(…, r[17]+r[18], r[15]+r[16])` — Confirmed |

CRC check vectors from `Command` ([V]):

```
01 03 01 01 00 16 | 94 38   HOME_DATA_OLD (single battery)
01 03 01 00 00 17 | 04 38   HOME_DATA (dual battery)
01 03 00 0A 00 10 | 64 04   BULETOOTH (device info)
01 03 04 00 00 05 | 84 F9   TODAY_DATA / CHART_TODAY
01 03 02 00 00 18 | 44 78   SETTING
01 03 01 21 00 01 | D5 FC   Forced_Load_Short
01 78 FF FF FF FF | A0 54   Restore_Factory_Setting
```

### Response handling

[J] `BluCommt$2.onNotify`: notification chunks are appended to a buffer until the last two
bytes equal the CRC of everything before them; then the frame is accepted. Data words are
taken from byte 3 for `byte_count` bytes and split into 4-hex-char strings. — Confirmed

[J] `BluCommt` keeps a queue and sends one command at a time, with a timeout timer before
the next. The response is dispatched by the *request* string, not by anything in the reply
(`MainActivity.Response(cmd, raw, regs)`). — Confirmed

The app does not handle Modbus exception replies (`fc | 0x80`) explicitly. This
integration treats them as errors. — Inferred

## 3. Session and polling

[J] `MainActivity.canMsg`, the handler in `MainActivity$1`, `MainActivity.canSendMsg`, and
`com.ruijing.mppt.util.BleTimer` (1 s tick; counters `seconds_three = 3`,
`seconds_five = 5`, `seconds_set = 300`):

| When | Request | Purpose |
|---|---|---|
| on connect | `0x03` @ `0x000A` × 16 | device info; decides single/dual layout |
| ~every 5 s (handler msg 0) | `0x03` @ `0x0101` × 22 (single) or `0x0100` × 23 (dual) | real-time data |
| same tick | `0x03` @ `0x0400` × 5 | today's statistics |
| same tick, until loaded | `0x03` @ `0x0200` × 24 | settings |
| same tick, if password enabled | `0x03` @ `0x0310` × 8 | password |
| every 3 s (msg 1) | `0x03` @ `0x0121` × 1 | load state / mode |
| ~every 300 s (msg 2) | `0x03` @ `0x000A` × 16 | device info refresh |

Which timer counter maps to which message is Inferred from the counter names; the request
set itself is Confirmed.

## 4. Layout selection

[J] `MainActivity.Response` for the device-info reply:

- `isDouble = r[14]`; `isDoubleBattary = (r[14] == 1)`.
- If the model string contains `100F` or `80F`, `isDoubleBattary` is forced false.
- `isDoubleBattary` false → single-battery requests (`HOME_DATA_OLD`, 0x0101 × 22).
  This includes `isDouble == 3` (DC-DC charger), which uses the single layout plus
  registers 19–20.

The integration implements the single-battery layout only. Dual-battery devices are
recognised and rejected with a clear error, so they can be added later.

## 5. Device info — `0x000A` × 16

[J] `MainActivity.Response`, `LeftLayout.setBlueCode`, `SettingFragment.setMaxCurrent`/`setMaxV`:

| Index | Register | Meaning | Confidence |
|---|---|---|---|
| 0 | 0x000A | high byte: rated/max current (A) | Inferred (used for dual-battery limits) |
| 2–9 | 0x000C–0x0013 | model name, ASCII, double spaces removed | Confirmed |
| 10 | 0x0014 | firmware / version ÷ 100 (shown in side drawer) | Confirmed |
| 14 | 0x0018 | layout: 1 = dual battery, 3 = DC-DC, otherwise single | Confirmed |
| 15 | 0x0019 | 1 = settings password enabled | Confirmed |

Debug sample in `MainActivity.Response` (only 15 words):
`1EFF 180C 2020 4443 2D44 432D 3330 2020 2020 2000 0064 0064 0000 0000 0001`
→ model `DC-DC-30`, version 1.00, `r[14] = 1`.

## 6. Real-time data — `0x0101` × 22 (single battery)

[J] `HomeFragment.setData` (single-battery branches), `HomeFragment.initList` (labels),
`MainActivity.Response` → `HistoryFragment.setDays`. Index *i* is register `0x0101 + i`.

| i | Reg | Value | Scale / unit | Confidence |
|---|---|---|---|---|
| 0 | 0x0101 | battery state of charge (`mWaveView.setWaterLevelRatio`) | % | Confirmed |
| 1 | 0x0102 | battery voltage | ×0.1 V | Confirmed |
| 2 | 0x0103 | charging current | ×0.01 A | Confirmed |
| 3 | 0x0104 | charging power | W | Confirmed |
| 4 | 0x0105 | high byte: controller temperature; low byte: battery temperature | °C (app parses unsigned) | Confirmed (signedness Unknown) |
| 5 | 0x0106 | load voltage | ×0.1 V | Confirmed |
| 6 | 0x0107 | load current | ×0.01 A | Confirmed |
| 7 | 0x0108 | load power | W | Confirmed |
| 8 | 0x0109 | PV (solar) voltage | ×0.1 V | Confirmed |
| 9–11 | 0x010A–0x010C | not used by the app | — | Unknown (PV current/power likely) |
| 12 | 0x010D | high byte: DC load on (≠ 0); low byte: charge stage | enum below | Confirmed |
| 13 | 0x010E | fault bit field | bits below | Confirmed |
| 14 | 0x010F | total running days | d | Confirmed |
| 15–16 | 0x0110–0x0111 | lifetime energy, u32 | Wh | Confirmed value; Inferred = **charge** |
| 17–18 | 0x0112–0x0113 | lifetime energy, u32 | Wh | Confirmed value; Inferred = **discharge** |
| 19 | 0x0114 | DC-DC direction (layout 3 only) | — | Inferred |
| 20 | 0x0115 | external voltage (layout 3 only): (v − 32768) ÷ 10 | V | Inferred |
| 21 | 0x0116 | used in dual-battery layout only | — | Inferred |

Charge stage (low byte of r[12]), string resources in `HomeFragment.setData`:

| Value | Resource | Meaning |
|---|---|---|
| 0 | `no_work` | not charging |
| 1 | `start_charge` | starting |
| 2 | `MPPT` | MPPT (bulk) |
| 3 | `EQUALIZE` | equalize |
| 4 | `BOOST` | boost / absorption |
| 5 | `FLOAT` | float |
| 6 | `Curren` | current limiting |

Fault bits (r[13], bit 0 = LSB), from the bit-string loop in `HomeFragment.setData` and the
fault labels; 0 shows "System Normal":

| Bit | Fault |
|---|---|
| 0 | battery over-discharge |
| 1 | battery over-voltage |
| 2 | battery under-voltage warning |
| 3 | DC load short circuit |
| 4 | DC load overload |
| 5 | controller over-temperature |
| 6 | ambient over-temperature |
| 7 | PV overload |
| 8 | PV short circuit |
| 9 | PV over-voltage |
| 12 | PV reverse polarity |
| 13 | battery reverse polarity |

The two lifetime totals: `setDays(days, r[17]+r[18], r[15]+r[16])`; the third argument
feeds the "total charge" text view and the second "total discharge". The labels were
followed through `HistoryFragment.setDays` view IDs only, hence Inferred.

## 7. Today — `0x0400` × 5

[J] `HomeFragment.setTodayData`, labels from `initList`:

| i | Reg | Value | Scale |
|---|---|---|---|
| 0 | 0x0400 | energy charged today | Wh |
| 1 | 0x0401 | energy discharged today | Wh |
| 2 | 0x0402 | peak charging power today | W |
| 3 | 0x0403 | highest battery voltage today | ×0.1 V |
| 4 | 0x0404 | lowest battery voltage today | ×0.1 V |

## 8. Load state — `0x0121` × 1

[J] `MainActivity.Response` → `HomeFragment.setShort`: high byte `1` = load output on;
low byte `0` = manual ("switch") load mode, otherwise a timed/light-controlled mode.
— Confirmed (meaning of non-zero low-byte values Unknown)

## 9. Settings — `0x0200` × 24 (read only, documented for later)

[J] `SettingFragment.setData`, `Utils.getBatteryMode`. In single mode the app drops the
first word before parsing (`regs[1:]`); indices below are after that drop.

| i | Meaning |
|---|---|
| 1 | system voltage (12/24/36/48; 255 = auto). Voltage ratio = V ÷ 12 |
| 2 | battery type: 0 user, 1 flooded, 2 sealed (AGM), 3 gel, 4 lithium |
| 3–7, 9 | charge/discharge voltage thresholds, ×0.1 V × ratio |
| 8 | alarm voltage |
| 10–11 | durations (min) |
| 12 | duration (s) |
| 13 | voltage × ratio |
| 14 | load mode (85 → app also reads `0x0300` × 12; 255 special) |
| 15 | temperature compensation, mV/2V/°C (0 = off) |
| 16 | integer setting |
| 17 | PV type 0–6 (presets) |
| 18–22 | voltages ×0.1 V |

## 10. Writes seen (not implemented)

From `Command` ([J], CRCs [V]):

| Frame | Purpose |
|---|---|
| `01 06 01 20 00 01 48 3C` / `01 06 01 20 00 00 89 FC` | DC load on / off |
| `01 06 01 21 FF 01 …` / `01 06 01 21 FF 00 …` | load mode |
| `01 06 02 10 …` | charging on/off (`HOME_CHONGDIAN_SET`) |
| `01 10 02 00 00 10 20 …`, `01 10 02 01 00 17 2E …` | bulk settings write |
| `01 10 03 00 00 0C …` | load timer settings |
| `01 78 FF FF FF FF A0 54` | restore factory settings |
| `01 79 FF FF FF FF 9D 94` | clear history |

## 11. What the integration reads

Per poll (default every 10 s; the app uses ~5 s): `0x0101` × 22, `0x0400` × 5, `0x0121` × 1.
Device info `0x000A` × 16 is read on each new connection.

## Open questions

To settle on hardware:

1. What registers 0x010A–0x010C hold (exposed as disabled diagnostic raw sensors).
2. Whether temperatures are signed below 0 °C.
3. Which lifetime total is charge and which is discharge.
4. The advertised name, and whether FFE0 is in the advertisement.
5. Whether the 40A reports `r[14]` ≠ 1 (single layout), as the app logic expects.
