# Minini live debugger

`MininiDebug.zip` is a separate BeamNG mod. Companion does not need to stay open.
Enable it, press **Ctrl+L** to reload game Lua, then load a Companion EV.
It publishes 20 Hz telemetry to localhost UDP **28581** and accepts commands on **28580**.
Other vehicles report `unsupported`; their controls and physics are untouched.

From this folder, read pedals, gear, speed, four motors, ECU errors and four chassis IMUs:

```powershell
python src/minini_debug.py watch --seconds 30 --log debug-session.jsonl
```

Apply 20% throttle in drive for three seconds and record the result:

```powershell
python src/minini_debug.py drive --seconds 3 --throttle 0.2 --log debug-drive.jsonl
```

Commands also accept `--brake`, `--parkingbrake` (0..1) and `--steering` (-1..1).
Replace the active car with an installed Companion ZIP, or reload the game Lua VM
(the same operation as Ctrl+L):

```powershell
python src/minini_debug.py replace --zip "C:\path\to\mods\Test_v22_33.zip"
python src/minini_debug.py reload
```

Replacement checks the installed model's four Companion motor channels. Other car
models and filesystem paths cannot be used as replacement targets. It replaces the
active vehicle; it does not overwrite or delete any ZIPs in your mods folder.
The normal custom Lua ECU still decides wheel torque; this does not bypass traction,
launch or vectoring. It is intended to reveal where requested torque gets lost.
Debug pedal/steering input expires after 0.5 seconds without a heartbeat, releases on
vehicle switch, and releases on client exit. Watch mode never writes controls.
Direction normally follows the custom ECU. Optional `--gear -1/0/1` requests the stock selector for scripts that use it; automatic direction control can override that request. Only one client can own the telemetry port.

Full records include ECU inputs/outputs, motor torque/commands/regen/RPM/energy status,
wheel speed/RPM, and each IMU's forward/left/up specific force (m/s²) and gyro (rad/s).
The independent IMU sampler can also diagnose the previous export with a failed ECU.
It uses this car's existing chassis nodes and adds no physical mass.

The bridge has only `snapshot`, `control`, `release`, `replace` and `reload` commands, JSON validation,
active vehicle ID matching, and loopback-only sockets. It has no arbitrary Lua execution API.

Wheel diagnostics also include steering and camber angles relative to four chassis reference nodes, plus contact slip speeds. These angles are for testing only and are not supplied to the custom motor-control function.
