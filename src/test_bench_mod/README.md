# Minini Test Bench

Reapply the updated Companion patch to the car. Install MininiTestBench.zip, press Ctrl+L, reload the car, and add Minini Test Bench through UI Apps.

Set signed Nm for FL/FR/RL/RR and steering-wheel angle in degrees (positive right). Start takes exclusive driving-input control; Stop releases it. Exact mode prescribes ideal net motor output Nm, bypassing the torque curves. Additional mode adds offsets to a frozen baseline: current shaft torques when starting immediately, or the last run-up torque when the initial-speed target is reached. Displayed Actual Nm confirms shaft commands. ±5000 Nm bounds prevent invalid configurations; damaged/unpowered motors produce zero.

Steering is applied first with a 0.3-second settling phase. With an initial-speed target, keep that steering while an equal-wheel torque speed regulator reaches the requested speed; activate wheel torque settings once within 1 km/h for 0.2 seconds. Speed is not held afterward. No traction/launch/yaw assistance is applied. Closing the widget, switching vehicle, resetting, changing map or losing the heartbeat stops the test. Stopping does not brake the vehicle.

The normal custom controller is now direct pedal control without MiTVS, launch or traction assistance. Old policy and adapter files are retained in Companion's backups folder. The test torque interface requires the updated car patch; unrelated cars are rejected without taking input control. Geometry, tires and physical brakes are retained.

All numeric controls use sliders and display their values. Initial speed ranges from 0 to 130 km/h in 1 km/h steps. Steering follows the active car's steering-wheel lock in 1 degree steps. Torque sliders cover -1500 to +1500 Nm in 1 Nm steps, with -10, -1, Zero, +1 and +10 buttons. Additional mode applies these offsets to the captured baseline; combined torque retains the existing actuator bounds. Torque mode uses buttons. Labels use ASCII characters.

Torque sliders, mode buttons and steering remain editable during the test. Updates do not restart run-up or recapture the baseline. Exact mode can switch to additional mode and back while preserving the torque that reached the target speed. Initial-speed settings are locked until Stop. Current shaft torque is displayed next to each wheel setting.
