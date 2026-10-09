# BeamNG dashboard serial bridge

Installed mod: `CompanionDashboard.zip`. It is independent of vehicle ZIPs.

1. Restart Companion and BeamNG after the initial installation.
2. In Companion's **Dashboard** tab, choose a COM port and baud rate, then **Connect**.
3. Keep Companion open and drive the active player vehicle.
4. For a hardware-free check, choose **Dummy receiver (no hardware)** instead. The tab shows decoded speed, G forces, sequence and packet count.

**BeamNG connection status** is always visible above the tabs and repeated in Dashboard. Green **Connected** means a valid vehicle telemetry packet arrived within the last second. **Not connected** means no fresh telemetry or the receiver is stopped; opening a COM port alone does not mean the game is connected. Click Connect to start listening, then load/drive a vehicle with the telemetry mod enabled.

Port and baud selections are saved. Connecting is manual. Default baud is **921600**, 8 data bits, no parity, 1 stop bit, no RTS/CTS or XON/XOFF; application receipts provide flow control. The supplied protocol does not specify a COM port, so the initial selection is the dummy receiver. Disconnect before changing port or baud. **Install/update telemetry mod** installs into the mods folder selected in Settings.

## Data path and STM32 input

The game sends JSON only over localhost UDP port **28574**. Companion converts it to the supplied Android binary format and writes raw binary bytes to the selected serial port. STM32 receives **binary, not JSON**.

Each serial snapshot is **91 bytes**, **36 cells** (sequence + all 35 telemetry fields), sampled at **24 Hz** while vehicle data is fresh. On a physical COM port, two snapshots are grouped into **182 bytes** and written as **64 + 64 + 54 byte** transfers, waiting for an ECU receipt after each chunk (about 12 batches/s). Even sizes avoid the observed odd-length receive fault; ECU receipts prevent back-to-back USB OUT writes from overrunning the board’s receive handling. An OS write/flush alone is not proof of ECU reception. The binary format is unchanged; the first snapshot in each pair waits approximately 42 ms. The dummy receiver retains individual 24 Hz writes. An unmatched snapshot is discarded on Disconnect or stale game data; no partial frame is deliberately sent. Wire traffic is 2184 bytes/second, approximately 21840 bit/second with 8N1. The COM sender uses wall-clock time, independently of rendering FPS. If the game stops providing data for one second, transmission waits for fresh data. It does not send fake zero snapshots when no vehicle exists.

Format: `COUNT[8] | (ID[6] | RAW[field width]) × COUNT | zero padding`. MSB-first; signed values use two's complement. There is no ASCII, newline, header, CRC or MFI envelope. IDs, widths, scaling and bounds are exactly those in `ANDROID_BINARY_PROTOCOL.md`. Music commands and bridge status packets are not generated.

Full 24 Hz snapshots replace the document's change-only sending policy. Sequence starts at 1 on Connect, advances after both snapshots receive ECU receipts, and wraps from 4294967295 to 0. ECU accepts these raw Android-format input packets and forwards changed values using the existing MFI protocol.

### ECU feedback

After processing each USB chunk, ECU replies with ASCII `ECU RX <bytes> MFI <count>\r\n`, for example `ECU RX 64 MFI 12\r\n`. `<bytes>` must match the outstanding chunk length. `<count>` is the cumulative number of completed exchanges acknowledged by BRIDGE since ECU reset, including music commands. It does not increase for unchanged telemetry. Receipts are emitted only in working mode, after any MFI request/response finishes; there are no prints inside MFI communication.

Companion waits at most 2.5 seconds for each receipt (MFI itself times out at 2 seconds). Missing, malformed or wrong-length receipts and `ECU TERMINAL ERROR: ...` stop transmission with an error. It never retries a possibly applied packet. Disconnect and reset ECU before reconnecting after a partial stream/error. Normal Disconnect finishes an already-started pair; stop can take up to approximately 2.5 seconds if feedback is missing.

The Dashboard reports `ECU received` and `MFI ACKs N`. These counters confirm the ECU receipt and the relay acknowledgment; they do not confirm that Android rendered the data.

For the STM32 parser, buffer partial reads and accept multiple packets in a read. Parse count, then ID and its documented width; apply only a complete validated packet. Do not use USB read boundaries as packet boundaries. Start the STM32 parser before clicking Connect, which starts a new packet-aligned stream. `dashboard_dummy.py` is a working incremental receiver reference for the telemetry subset.

## Signal mapping

| Dashboard value | Source |
|---|---|
| Speed | Magnitude of vehicle world velocity, converted to km/h |
| Longitudinal / lateral G | Stock G-meter signals: `sensors.gy2 / -gravity`, `sensors.gx2 / -gravity`, including its gravity clamp |
| Gear | `electrics.values.gearIndex`: negative=R, zero=N, positive=D; park is represented separately |
| Parking, throttle, brake, steering | Parking-brake state and normalized driver input |
| Launch | Custom ECU `companionLaunchState`: 0 off, 1 armed, 2 active |
| Turn signals | Steady enabled states `signal_left_input`, `signal_right_input`; Android performs blinking |
| Headlights | `lowbeam`, `highbeam` |
| FL/FR/RL/RR battery | Combined electric-battery state of charge; all four show the same shared pack percentage |
| Power | Battery energy change divided by simulation time; positive=draw, negative=charging |
| Remaining energy | Sum of electric-battery stored joules / 3600000 |
| Trip distance | Integrated body speed |
| Trip energy | Gross positive battery energy draw |
| Recovered energy | Integrated negative battery energy change |
| Average consumption | Net trip energy (draw minus recovered), kWh/100 km; calculated after 10 m |
| Remaining/recovered range | Remaining/recovered energy divided by average net consumption; zero when consumption is not positive |
| Outside temperature | Environment Kelvin minus 273.15 |
| Clock | PC local minutes since midnight |

Trip counters reset on vehicle reset/reload and only accumulate while that vehicle is selected. G signs/axes intentionally match the working BeamNG G-meter, without applying another orientation patch.

Unknown values use the **literal protocol minimum**. This includes mode=COMFORT, speed limit=1 km/h (display only; it does not limit the car), door states=closed, and unavailable corner temperatures=**-3276.8°C**. An absent battery means SOC/energy=0 and unavailable power=-3276.8 kW. Missing signed G or steering inputs also use their documented negative minimum. These are placeholders, not simulated measurements. No motor temperature model is invented.

## Verification

Run from the Companion folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_dashboard.py -v
```

Tests cover the exact documented golden packet, full snapshots, every possible byte split, combined packets, signed values, bounds, sequence wrap, vehicle activation/switching/reset, battery calculations, and the complete Lua -> localhost UDP -> real Python serial bridge -> pySerial loopback -> incremental dummy receiver path. Lua uses simulated BeamNG APIs in these automated tests. No physical COM device is opened by the tests.

Implementation: `dashboard_mod/` (game extensions), `dashboard_bridge.py` (transport), `dashboard_protocol.py` (binary encoder), `dashboard_dummy.py` (reference receiver). pySerial and Lupa are installed through `requirements.txt`.

## Device selection

The port list shows available serial devices. If you want to restrict it to one ECU, set `AUTOCRAFT_ECU_USB_SERIAL` in your local environment before starting Companion. It must match that board's USB serial number. No board identifier is included in this repository.

The physical receiver must implement the `ECU RX <bytes> MFI <count>` receipts described above. The dummy mode uses serial loopback and does not need this firmware. Start the downstream relay, reset the ECU, then Connect. Reset the ECU after an interrupted binary stream before reconnecting.
