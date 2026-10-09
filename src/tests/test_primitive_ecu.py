"""Primitive pipeline: priority, traction, activation, signs and motor limits."""
import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/_runtime'))
from lupa.luajit21 import LuaRuntime
NAMES=('FL','FR','RL','RR')

class PrimitiveECUTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.fn=self.lua.execute((ROOT/'custom_motor_control.lua').read_text())
        # Static allocation checks describe an already established allowance.
        # Dynamic plant tests start with empty memory and exercise the launch.
        self.memory=self.lua.table_from({'trc':{n:dict(peak=.1,gain=1) for n in NAMES}},recursive=True)

    def state(self,gas=.5,brake=0,radius=None,yaw=1):
        speed=30/3.6
        s=dict(dt=.01,throttle=gas,brake=brake,gear=1,forwardSpeed=speed,travelSpeed=speed,
            bodySpeed=speed,steering=-.5,wantedRotationSpeed=30,
            wheelSpeed={n:speed for n in NAMES},wheelGroundSpeed={n:speed for n in NAMES},
            wheelRPM={n:speed/.313*30/math.pi for n in NAMES},motorTorque={n:500 for n in NAMES},
            motorLimits={n:dict(drive=1000,regen=800,radius=.313,inertia=.611) for n in NAMES},
            geometry=dict(mass=715,wheelbase=2.6,trackFront=1.6,trackRear=1.6))
        if radius is not None:
            s['wantedRC']=dict(x=0,y=10,z=0,distance=10)
            s['estimatedRC']=dict(x=0,y=radius,z=0,distance=abs(radius),yawRad=yaw,
                rotationSpeed=30,forwardSpeed=speed,lateralSpeed=0,center=dict(x=0,y=0,z=0),
                forward=dict(x=1,y=0,z=0),left=dict(x=0,y=1,z=0))
        return self.lua.table_from(s,recursive=True)

    def test_brake_overrides_and_zero_coasts(self):
        out=self.fn(self.state(gas=1,brake=.25),self.memory)
        self.assertEqual(out.trc.request,-.25)
        for n in NAMES:
            self.assertEqual(out[n],0);self.assertAlmostEqual(out.regen[n],.25)
        out=self.fn(self.state(gas=0),self.memory)
        for n in NAMES:self.assertEqual(out[n],0);self.assertEqual(out.regen[n],0)

    def test_trc_has_no_steering_dependency_and_reports_overshoot(self):
        s=self.state();s.wheelSpeed.FL*=1.2
        a=self.fn(s,self.lua.table());s.steering=1
        b=self.fn(s,self.lua.table())
        self.assertGreater(a.trc.slip.FL.usage,1)
        self.assertAlmostEqual(a.trc.slip.FL.usage,2)
        for n in NAMES:self.assertEqual(a.trc.torques[n],b.trc.torques[n])
        for _ in range(30):a=self.fn(s,self.memory)
        self.assertLess(a.trc.torques.FL,a.trc.torques.FR)

    def test_gate_15m_and_at_target_no_correction(self):
        for r in (15,20):
            out=self.fn(self.state(radius=r),self.lua.table())
            self.assertFalse(out.vectoring.active)
            for n in NAMES:self.assertEqual(out.mitvsDelta[n],0)
        out=self.fn(self.state(radius=10,yaw=(30/3.6)/10),self.lua.table())
        self.assertTrue(out.vectoring.active)
        for n in NAMES:self.assertAlmostEqual(out.mitvsDelta[n],0,places=8)

    def test_correction_only_telemetry_and_capacity_redistribution(self):
        out=self.fn(self.state(gas=1,radius=5,yaw=1.6),self.memory)
        self.assertLess(out.vectoring.allocatedYawMoment,0)
        self.assertLess(out.mitvsDelta.FR,0)
        self.assertLess(out.mitvsDelta.RR,0)
        self.assertAlmostEqual(sum(out.vectoring.wheelCorrection[n].share for n in NAMES),1)
        for n in NAMES:
            row=out.vectoring.wheelCorrection[n]
            self.assertEqual(row.commandedTorqueNm,out.mitvsDelta[n])
            self.assertAlmostEqual(row.motorUse*row.motorLimitNm,row.deltaTorqueNm)
            self.assertGreaterEqual(out[n],-1);self.assertLessEqual(out[n],1)

    def test_peak_search_climbs_then_reverses_on_falling_force(self):
        s=self.state(gas=1)
        def cycle(low_force,high_force):
            for i in range(60):
                high=i>=30
                s.motorTorque.FL=high_force if high else low_force
                s.wheelSpeed.FL=s.wheelGroundSpeed.FL*(1+(.11 if high else .08))
                out=self.fn(s,self.memory)
            return out.trc.slip.FL.peak
        rising=cycle(500,650)
        self.assertGreater(rising,.1)
        falling=cycle(650,500)
        self.assertLess(falling,rising)

    def test_mild_peak_overshoot_does_not_dump_power(self):
        s=self.state(gas=1)
        for n in NAMES:s.motorTorque[n]=1000
        s.wheelSpeed.FL*=1.11
        first=self.fn(s,self.memory)
        self.assertGreater(first.trc.torques.FL,970)
        for _ in range(5):out=self.fn(s,self.memory)
        self.assertGreater(out.trc.torques.FL,950)

    def test_search_finds_three_different_tire_peaks_in_dynamic_plant(self):
        # Four equal tires, wheel inertia and vehicle acceleration. The force
        # curve rises then falls; the controller is not given its peak location.
        for actual_peak in (.06,.12,.18):
            with self.subTest(actual_peak=actual_peak):
                memory=self.lua.table();s=self.state(gas=1)
                speed=10.;omega=speed/.313;torque=0.;samples=[]
                peak_force=1.2*715*9.81/4
                for tick in range(1600):
                    s.travelSpeed=speed;s.forwardSpeed=speed;s.bodySpeed=speed
                    for n in NAMES:
                        s.wheelSpeed[n]=abs(omega*.313);s.wheelRPM[n]=omega*30/math.pi
                        s.wheelGroundSpeed[n]=speed;s.motorTorque[n]=torque
                    out=self.fn(s,memory);torque=out.FL*1000-out.regen.FL*800
                    forces=[]
                    for _ in range(10):
                        slip=(omega*.313-speed)/max(speed,2)
                        q=slip/actual_peak;force=peak_force*2*q/(1+q*q)
                        omega+=(torque-force*.313)/.611*.001
                        speed+=4*force/715*.001;forces.append(force)
                    if tick>1200:samples.append((sum(forces)/10/peak_force,out.trc.slip.FL.peak))
                self.assertGreater(sum(x[0] for x in samples)/len(samples),.95)
                self.assertAlmostEqual(sum(x[1] for x in samples)/len(samples),actual_peak,delta=.015)

    def test_slow_wheel_during_acceleration_is_not_treated_as_wheelspin(self):
        s=self.state(gas=1)
        s.wheelSpeed.FL*=.8
        out=self.fn(s,self.memory)
        self.assertLess(out.trc.slip.FL.controlSlip,0)
        self.assertEqual(out.trc.torques.FL,1000)

    def test_search_crosses_deep_valley_to_stronger_peak(self):
        self.memory=self.lua.table()
        s=self.state(gas=1);speed=10.;omega=speed/.313;torque=0.;samples=[]
        peak_force=1.2*715*9.81/4
        for tick in range(1600):
            s.travelSpeed=speed;s.forwardSpeed=speed;s.bodySpeed=speed
            for n in NAMES:
                s.wheelSpeed[n]=abs(omega*.313);s.wheelRPM[n]=omega*30/math.pi
                s.wheelGroundSpeed[n]=speed;s.motorTorque[n]=torque
            out=self.fn(s,self.memory);torque=out.FL*1000-out.regen.FL*800
            for _ in range(10):
                slip=(omega*.313-speed)/max(speed,2)
                k=abs(slip)
                curve=(.25+.40*math.exp(-((k-.06)/.025)**2)
                       +.75*math.exp(-((k-.20)/.055)**2))*(1-math.exp(-k/.015))
                force=math.copysign(peak_force*curve,slip)
                omega+=(torque-force*.313)/.611*.001
                speed+=4*force/715*.001
            if tick>1200:samples.append((force/peak_force,out.trc.slip.FL.peak))
        self.assertGreater(sum(x[0] for x in samples)/len(samples),.90)
        self.assertAlmostEqual(sum(x[1] for x in samples)/len(samples),.20,delta=.02)

    def test_launch_recovers_traction_at_1_10_30_and_100_kmh(self):
        accelerations=[]
        for kmh in (1,10,30,100):
            with self.subTest(kmh=kmh):
                memory=self.lua.table();s=self.state(gas=1)
                speed=kmh/3.6;omega=speed/.313;torque=0.;samples=[]
                for tick in range(100):
                    s.travelSpeed=speed;s.forwardSpeed=speed;s.bodySpeed=speed
                    for n in NAMES:
                        s.wheelSpeed[n]=abs(omega*.313);s.wheelRPM[n]=omega*30/math.pi
                        s.wheelGroundSpeed[n]=speed;s.motorTorque[n]=torque
                    out=self.fn(s,memory);torque=out.FL*1000-out.regen.FL*800
                    for _ in range(100):
                        slip=(omega*.313-speed)/max(speed,.05)
                        q=slip/.12;force=1.2*715*9.81/4*2*q/(1+q*q)
                        omega+=(torque-force*.313)/.611*.0001
                        speed+=4*force/715*.0001
                        if tick>=50:samples.append(4*force/715/9.81)
                acceleration=sum(samples)/len(samples)
                self.assertGreater(acceleration,.85)
                accelerations.append(acceleration)
        self.assertLess(max(accelerations)-min(accelerations),.05)

    def test_slip_is_same_ratio_at_low_and_high_speed(self):
        for kmh in (1,10,30,100):
            s=self.state(gas=1)
            for n in NAMES:
                s.wheelGroundSpeed[n]=kmh/3.6;s.wheelSpeed[n]=kmh/3.6*1.12
            out=self.fn(s,self.lua.table())
            self.assertAlmostEqual(out.trc.slip.FL.slip,.12)

    def test_front_overshoot_recruits_rear_and_delta_matches_final(self):
        s=self.state(gas=0,radius=5,yaw=1.6)
        s.wheelSpeed.FL*=1.3;s.wheelSpeed.FR*=1.3
        out=self.fn(s,self.memory)
        front=sum(abs(out.mitvsDelta[n]) for n in ('FL','FR'))
        rear=sum(abs(out.mitvsDelta[n]) for n in ('RL','RR'))
        self.assertGreater(rear,front)
        for n in NAMES:
            final=out[n]*1000-out.regen[n]*800
            self.assertAlmostEqual(final,out.trc.torques[n]+out.mitvsDelta[n])

    def test_mirrored_turns_mirror_allocations(self):
        left=self.state(gas=.5,radius=5,yaw=1.6)
        right=self.state(gas=.5,radius=-5,yaw=-1.6)
        right.wantedRC.y=-10;right.steering=.5
        a=self.fn(left,self.lua.table());b=self.fn(right,self.lua.table())
        for x,y in (('FL','FR'),('RL','RR')):
            self.assertAlmostEqual(a.mitvsDelta[x],b.mitvsDelta[y])
            self.assertAlmostEqual(a.mitvsDelta[y],b.mitvsDelta[x])

    def test_speed_error_and_reverse_signs(self):
        s=self.state(gas=0,radius=10,yaw=.833333333)
        s.estimatedRC.rotationSpeed=20
        out=self.fn(s,self.memory)
        self.assertGreater(sum(out.mitvsDelta[n] for n in NAMES),0)
        s.gear=-1;s.forwardSpeed=-s.forwardSpeed;s.travelSpeed=-s.travelSpeed
        s.estimatedRC.forwardSpeed=-s.estimatedRC.forwardSpeed;s.estimatedRC.yawRad=-.833333333
        out=self.fn(s,self.lua.table())
        self.assertLess(sum(out.mitvsDelta[n] for n in NAMES),0)

if __name__=='__main__':unittest.main()
