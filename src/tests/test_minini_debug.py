import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/_runtime'))
from lupa.luajit21 import LuaRuntime
from custom_control import build_controller, verify_motor_wiring
from debug_mod import build
from minini_debug import DebugClient


class DebugModTests(unittest.TestCase):
    def vehicle(self, supported=True):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          FILTER_DIRECT=0
          calls={};published={};motors={};wheels={wheels={}}
          v={data={controller={{fileName='companion_custom_ecu'}},nodes={}}}
          electrics={values={gearIndex=1,gear='D'}}
          input={state={},throttle=.2,brake=0,steering=0}
          for _,n in ipairs({'throttle','brake','steering','parkingbrake'}) do input.state[n]={} end
          input.event=function(n,val,filter,a,b,c,source)
            calls[#calls+1]={name=n,value=val}
            input.state[n]={val=val,source=source}
          end
          for _,n in ipairs({'FL','FR','RL','RR'}) do
            motors['evMotor'..n]={electricsThrottleName='companionCustom'..n,outputTorque1=100}
            wheels.wheels[n]={name=n,wheelSpeed=2}
          end
          powertrain={getDevice=function(n) return motors[n] end}
          ecu={getDebugState=function() return {failed=false,version=2} end}
          controller={getController=function() return ecu end,
            mainController={shiftToGearIndex=function(g) electrics.values.gearIndex=g==2 and 1 or g end}}
          enablePhysicsStepHook=function() physicsHookEnabled=true end
          obj={getID=function() return 7 end,
            getVelocity=function() return {length=function() return 2 end} end,
            queueGameEngineLua=function(_,text) published[#published+1]=text end}
          jsonReadFile=function() return nil end
          jsonEncode=function(data) lastPacket=data;return '{}' end
        ''')
        lua.globals().jsonDecode=lambda raw: lua.table_from(json.loads(raw), recursive=True)
        if not supported:
            lua.execute('motors={};v.data.controller={}')
        text=(ROOT/'debug_mod/lua/vehicle/extensions/mininiDebugVehicle.lua').read_text()
        text=text.replace('-- __IMU__',(ROOT/'companion_imu.lua').read_text())
        module=lua.execute(text)
        module.onExtensionLoaded()
        return lua,module

    def command(self,module,**kwargs):
        module.request(json.dumps(dict(schema=1,vehicleID=7,op='control',throttle=.2,
            brake=0,steering=.3,parkingbrake=0,gear=1,**kwargs)))

    def test_other_cars_are_read_only_without_errors(self):
        lua,m=self.vehicle(False)
        self.command(m)
        for _ in range(100):
            m.onPhysicsStep(.01);m.updateGFX(.01)
        self.assertEqual(len(lua.globals().calls),0)
        self.assertEqual(lua.globals().lastPacket.status,'unsupported')
        self.assertIsNone(lua.globals().physicsHookEnabled)

    def test_control_timeout_releases_and_human_input_is_preserved(self):
        lua,m=self.vehicle()
        self.command(m);m.updateGFX(.01)
        self.assertTrue(lua.globals().physicsHookEnabled)
        self.assertEqual(lua.globals().electrics['values'].gearIndex,1)
        self.assertEqual(lua.globals().input.state.throttle.val,.2)
        lua.execute("input.state.steering={val=-.8,source='local'}")
        m.updateGFX(.51)
        self.assertEqual(lua.globals().input.state.throttle.val,0)
        self.assertEqual(lua.globals().input.state.steering.val,-.8)
        self.assertFalse(lua.globals().lastPacket.remoteActive)

    def test_invalid_and_wrong_vehicle_packets_never_control(self):
        lua,m=self.vehicle()
        for raw in ('not json',json.dumps(dict(schema=1,vehicleID=99,op='control')),
                    json.dumps(dict(schema=1,vehicleID=7,op='control',throttle=2,
                                    brake=0,steering=0,parkingbrake=0))):
            m.request(raw)
        m.updateGFX(.1)
        self.assertEqual(len(lua.globals().calls),0)

    def test_missing_ecu_and_failed_sensor_are_reported(self):
        lua,m=self.vehicle()
        lua.execute('ecu=nil')
        m.updateGFX(.1)
        self.assertTrue(lua.globals().lastPacket.ecu.failed)
        self.assertIn('did not initialize',lua.globals().lastPacket.ecu.error)
        lua.execute("v.data.controller[1].imu={mounts={FL={nodes={'a','b','c'}}}}")
        # Missing nodes are handled as an unavailable sampler, not a vehicle error.
        m.onReset();m.onPhysicsStep(.01);m.updateGFX(.1)

    def test_package_contains_sampler_and_fallback_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            path=build(Path(temp)/'debug.zip',dict(mounts={}))
            with ZipFile(path) as z:
                text=z.read('lua/vehicle/extensions/mininiDebugVehicle.lua').decode()
                self.assertIn('local function createIMUSampler',text)
                self.assertNotIn('-- __IMU__',text)
                self.assertIsNone(z.testzip())
                lua=LuaRuntime()
                compiler=lua.eval('function(s) return loadstring(s) end')
                for name in z.namelist():
                    if name.endswith('.lua'):
                        result=compiler(z.read(name).decode())
                        self.assertFalse(isinstance(result,tuple),name)

    def test_checker_rejects_previous_missing_imu_export(self):
        prefix='vehicles/test/'
        engine={'controller':[['type'],['companion_custom_ecu']]}
        for n in ('FL','FR','RL','RR'):
            engine['evMotor'+n]=dict(electricsThrottleName='companionCustom'+n,
                electricsThrottleFactorName='companionCustomFactor',
                electricsRegenThrottleName='companionCustomRegen'+n)
        entries={prefix+'engine.jbeam':json.dumps(dict(engine=engine)).encode(),
            prefix+'custom_motor_control.lua':b'return function() end',
            prefix+'lua/controller/companion_custom_ecu.lua':b'-- __IMU__\ncreateIMUSampler()'}
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            verify_motor_wiring(entries)
        entries[prefix+'lua/controller/companion_custom_ecu.lua']=build_controller(
            'return function() return {FL=0,FR=0,RL=0,RR=0} end').encode()
        verify_motor_wiring(entries)

    def test_watch_client_does_not_write_and_drive_sends_release(self):
        with patch('minini_debug.socket.socket') as factory:
            client=DebugClient();client.vehicle_id=7;client.close()
            factory.return_value.sendto.assert_not_called()
            client=DebugClient();client.vehicle_id=7
            client.send('control',throttle=.2);client.close()
            sent=json.loads(factory.return_value.sendto.call_args.args[0])
            self.assertEqual(sent['op'],'release')

    def test_client_locks_initial_vehicle_id(self):
        with patch('minini_debug.socket.socket') as factory:
            factory.return_value.recvfrom.side_effect=[
                (b'{"schema":1,"status":"ready","vehicleID":7}',('127.0.0.1',28580)),
                (b'{"schema":1,"status":"ready","vehicleID":8}',('127.0.0.1',28580))]
            client=DebugClient();client.receive();client.receive()
            self.assertEqual(client.vehicle_id,7)
            client.close()

    def test_game_bridge_routes_only_matching_ids_and_expires_in_real_time(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          sent={};queued={};inbox={};bindAddress=nil
          udp={settimeout=function() end,
            setsockname=function(_,address,port) bindAddress=address;return 1 end,
            sendto=function(_,raw,ip,port) sent[#sent+1]={raw=raw,ip=ip,port=port} end,
            receivefrom=function()
              if #inbox==0 then return nil end
              local row=table.remove(inbox,1);return row.raw,row.ip
            end,close=function() end}
          socket={udp=function() return udp end}
          vehicle={getID=function() return 7 end,
            queueLuaCommand=function(_,code) queued[#queued+1]=code end}
          be={getObjectByID=function(_,id) if id==7 then return vehicle end end}
          getPlayerVehicle=function() return vehicle end
          jsonEncode=function() return 'encoded' end
          log=function() end
        ''')
        lua.globals().jsonDecode=lambda raw: lua.table_from(json.loads(raw),recursive=True)
        ge=lua.execute((ROOT/'debug_mod/lua/ge/extensions/mininiDebug.lua').read_text())
        ge.onExtensionLoaded();ge.onUpdate(.01)
        self.assertEqual(lua.globals().bindAddress,'127.0.0.1')
        def packet(vehicle_id, ip='127.0.0.1'):
            row=dict(raw=json.dumps(dict(schema=1,vehicleID=vehicle_id,op='control')),
                     ip=ip)
            inbox=lua.globals().inbox
            inbox[len(inbox)+1]=lua.table_from(row)
        packet(99);packet(7,'192.168.1.2');ge.onUpdate(.01)
        commands=lambda: [v for v in lua.globals().queued.values() if '.request(' in v]
        self.assertEqual(len(commands()),0)
        packet(7);ge.onUpdate(.01)
        self.assertEqual(len(commands()),1)
        ge.onUpdate(.51)
        self.assertTrue(any('.release()' in v for v in lua.globals().queued.values()))
        ge.ingest(99,'{}')
        self.assertEqual(len(lua.globals().sent),0)
        ge.ingest(7,'{}')
        self.assertEqual(lua.globals().sent[1].ip,'127.0.0.1')
        lua.execute('''
          replacement=nil;reloaded=false
          engine={}
          for _,n in ipairs({'FL','FR','RL','RR'}) do
            engine['evMotor'..n]={electricsThrottleName='companionCustom'..n}
          end
          jsonReadFile=function(path)
            if path=='/vehicles/MininiNew/engine.jbeam' then return {engine=engine} end
          end
          core_vehicles={replaceVehicle=function(model) replacement=model end}
          Lua={requestReload=function() reloaded=true end}
        ''')
        def operation(op, model=None):
            data=dict(schema=1,vehicleID=7,op=op)
            if model is not None: data['model']=model
            inbox=lua.globals().inbox
            inbox[len(inbox)+1]=lua.table_from(dict(raw=json.dumps(data),ip='127.0.0.1'))
            ge.onUpdate(.01)
        operation('reload')
        self.assertFalse(lua.globals().reloaded)  # no recognized Companion snapshot yet
        ge.ingest(7,'{"status":"ready"}')
        operation('replace','../not_a_car')
        operation('replace','OtherCar')
        self.assertIsNone(lua.globals().replacement)
        operation('replace','MininiNew')
        self.assertEqual(lua.globals().replacement,'MininiNew')
        operation('reload')
        self.assertTrue(lua.globals().reloaded)
        ge.onExtensionUnloaded()

    def test_partial_ecu_initialization_remains_failed_after_reset(self):
        lua,m=self.vehicle()
        lua.execute('sensors={};input.parkingbrake=0')
        lua.execute("motors.evMotorFL=nil")
        lua.globals().log=lambda *args: None
        ecu=lua.execute(build_controller('return function() return {FL=1,FR=1,RL=1,RR=1} end'))
        ecu.init();ecu.reset();ecu.updateFixedStep(.01)
        self.assertTrue(ecu.getDebugState().failed)
        self.assertIn('missing motor channel',ecu.getDebugState().error)


if __name__=='__main__':
    unittest.main()
