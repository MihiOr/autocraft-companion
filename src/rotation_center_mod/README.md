# Minini Rotation Center

Install MininiRotationCenter.zip in the BeamNG mods folder and reload Lua (Ctrl+L).
The active player's car gets a green sphere labelled RC at its horizontal instantaneous rotation center. This is the center of its current turning motion, not the center of gravity or suspension roll center. It uses consecutive position and heading measurements, including reverse and sideways travel; it does not use MiTVS or assumed car axes.

The marker hides below 0.5 degrees/s yaw or beyond 200 m. Straight travel has its rotation center at infinity. Resets, teleports, vehicle switches and map transitions discard the previous measurement. The last marker remains visible when paused. Very fast changes describe the average center over one rendered simulation step.

Optional GE console commands: `extensions.mininiRotationCenter.toggle()` or `extensions.mininiRotationCenter.setEnabled(false)`.

A yellow sphere labelled ERC shows the four-IMU estimate on supported Minini vehicles. Its radius is 0.275 m, 10% larger than the green sphere's 0.25 m. The estimator averages all four accelerometers and gyros in a common world frame, removes gravity, and integrates acceleration. Existing corner velocity measurements initialize velocity and correct inertial drift with a 0.5 s time constant. It computes the horizontal center from estimated velocity and yaw rate, independently of the green marker's pose differences. This is sensor fusion with velocity aiding, not an accelerometer-only absolute-speed estimate. Invalid IMUs, near-zero yaw, resets and centers beyond 200 m hide ERC. It does not change motor commands or Civetta vehicle files.

Run `python capture_erc.py --seconds 120` from Companion's source folder to record diagnostic JSONL into `diagnostics/`. The mod sends each estimator sample over localhost UDP port 28610. Records include the four raw accelerometers/gyros/velocities, their mounting frames, world-space gyro contributions, averaged acceleration and yaw, velocity integration, radius, pedals, simulation timing, and the currently displayed RC/ERC markers. Candidate radius jumps are flagged; this is a diagnostic trigger, not proof of a faulty sensor. Recording does not control the vehicle or filter its readings.

With the primitive ECU, ERC fusion lives inside the vehicle controller and the yellow marker consumes its published estimate. The recorder also includes TRC state and MiTVS-added torques. Older vehicles retain the display extension's fallback estimator. The blue WRC marker consumes the ECU's wanted center.
