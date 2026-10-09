import unittest
from custom_control import USER_FILE, ROOT
import sys
from lupa.luajit21 import LuaRuntime


class UserTractionTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        loader,self.evaluate=self.lua.execute((ROOT/'custom_control_contract.lua').read_text()+'\nreturn loadUser,evaluateUser')
        self.fn=loader(USER_FILE.read_text())
        self.memory=self.lua.table()
        self.s=self.lua.table_from(dict(dt=.01,time=0,gear=1,bodySpeed=0,throttle=1,brake=0,parkingBrake=0,steering=0,
            wheelSpeed={n:0 for n in ('FL','FR','RL','RR')}),recursive=True)

    def step(self,count=1):
        for _ in range(count): out=self.evaluate(self.fn,self.s,self.memory)
        return out

    def test_arm_release_cancel_no_rearm_and_no_ramp(self):
        self.s.brake=1
        self.assertTrue(self.step().launchArmed)
        self.assertEqual(self.step().FL,0)
        self.s.brake=0
        out=self.step()
        self.assertTrue(out.launchActive)
        self.assertEqual(out.FL,1)
        self.s.bodySpeed=30
        self.s.wheelSpeed=self.lua.table_from({n:30 for n in ('FL','FR','RL','RR')})
        self.assertTrue(self.step().launchActive)
        self.s.throttle=.49
        self.assertFalse(self.step().launchActive)
        self.s.throttle=1; self.s.bodySpeed=0; self.s.brake=1
        self.step(); self.s.brake=0; self.step()
        self.s.brake=1
        out=self.step()
        self.assertFalse(out.launchActive)
        self.assertFalse(out.launchArmed)
        self.assertEqual(out.FL,0)
        self.assertFalse(self.step(20).launchArmed)

    def test_independent_slip_recovery_all_wheel_spin_and_reverse(self):
        self.s.bodySpeed=10
        self.s.wheelSpeed=self.lua.table_from(dict(FL=20,FR=10,RL=10,RR=10))
        out=self.step(40)
        self.assertEqual(out.FL,0)
        self.assertEqual(out.FR,1)
        self.s.wheelSpeed.FL=10
        self.assertEqual(self.step(100).FL,1)
        self.s.wheelSpeed=self.lua.table_from({n:20 for n in ('FL','FR','RL','RR')})
        out=self.step(40)
        self.assertTrue(all(out[n]==0 for n in ('FL','FR','RL','RR')))
        self.s.gear=-1
        self.s.wheelSpeed=self.lua.table_from({n:-10 for n in ('FL','FR','RL','RR')})
        self.assertEqual(self.step(2).FL,-1)
        self.s.wheelSpeed.FL=-20
        self.assertEqual(self.step(40).FL,0)

    def test_launch_uses_separate_slip_target_and_blocks_neutral_park(self):
        self.s.brake=1; self.step(); self.s.brake=0; self.step()
        self.s.bodySpeed=10
        self.s.wheelSpeed=self.lua.table_from({n:11 for n in ('FL','FR','RL','RR')})
        self.assertEqual(self.step(30).FL,1)  # below launch's 12%, above TC's 8%
        self.s.throttle=.49
        self.assertLess(self.step(30).FL,.49)
        self.s.parkingBrake=1
        self.assertEqual(self.step().FL,0)
        self.s.parkingBrake=0; self.s.gear=0
        self.assertEqual(self.step().FL,0)
