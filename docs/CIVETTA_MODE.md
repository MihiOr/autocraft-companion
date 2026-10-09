# Civetta mode

Use the **Minini Mode / Civetta Mode** button at the top right of Companion. Each mode has its own export workflow, Lua policy and version counter. Switching modes keeps Minini settings and installed vehicles.

The source is the installed **Civetta Scintilla GTx (DCT)** configuration (`gtx.pc`). Companion saves an unchanged local copy at `civetta/source/Scintilla_GTx.zip` and builds a separate vehicle. It never edits the original game ZIP.

## Conversion

- Four independent electric motors, each connected to its wheel through a 1:1 shaft.
- No combustion engine, DCT, differential or transfer-case powertrain devices.
- Existing chassis, body, suspension, wheel and tire settings retained. Engine/transmission mounting nodes and differential reaction supports remain passive structure so wheel attachments remain valid; their structural mass remains.
- Virtual battery, initially 100 kWh, with **0 kg** added mass. Fuel storage is removed.
- Regenerative service braking and the existing physical rear parking brake.
- Four chassis IMUs, each providing three accelerometer and three gyroscope axes. Existing wheel/motor/chassis telemetry uses the same custom-Lua contract as Minini.
- Existing debug, test-bench, rotation-center and dashboard interfaces. No traction, launch, stability, torque vectoring, suspension overrides or spawn-heading correction.

`civetta/custom_motor_control.lua` is separate from Minini's Lua. The initial policy passes pedal commands directly to all four motors. Reverse retains Minini's pedal convention. **Edit custom Lua** opens it; **Check Lua code** checks the same function contract used in the car. Re-export to package edits.

The motor CSV contains wheel RPM and wheel torque for one motor. **Peak torque per motor (Nm)** defaults to 1500. Civetta scales the torque curve vertically to that peak for each motor, preserving its shape and RPM points. Drive and regenerative envelopes use the same scale. It does not inherit Minini's grip, mass, gearbox-ratio or torque multipliers.

## Cache and versions

`civetta/cache/Scintilla_GTx_EV.zip` contains the physical conversion. Source ZIP, motor CSV, peak torque, capacity or converter/sensor changes invalidate its manifest. Lua edits reuse this cache and package the latest Lua adapter and policy.

With version label `v00`, **Convert & install** creates `Civetta_v00_01.zip`, then `_02`, `_03`, and so on, above the existing numbers in the selected mods folder. Each copy has its own model/asset namespace. Compiled source mesh caches (`.cdae`) are excluded so BeamNG compiles the renamed DAE meshes for that copy. The version label must be `v` followed by digits.

Restart Companion after updating its Python files. Reload BeamNG Lua with Ctrl+L after updating helper mods and select the new **Civetta Scintilla EV** vehicle. Offline checks validate ZIP contents, attachments, motor wiring and Lua syntax; driving behavior still needs an in-game check.
