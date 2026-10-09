import json
import socket
import sys
import time
import unittest
from pathlib import Path
from dashboard_protocol import encode_cells, encode_snapshot, FIELDS
from dashboard_dummy import DummyReceiver
from dashboard_bridge import DashboardBridge, DUMMY

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/_runtime'))
from lupa.luajit21 import LuaRuntime


def vehicle_lua(send):
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().sendPacket=send
    lua.globals().jsonEncode=lambda t:json.dumps({'schema':t.schema,'source':t.source,'values':dict(t['values'].items())})
    lua.execute('''
      closed=false; energy=360000000; speed=20; gravity=-9.81
      socket={udp=function() return {
        settimeout=function() end, setpeername=function() end,
        send=function(self,packet) sendPacket(packet) end,
        close=function() closed=true end} end}
      obj={getVelocity=function() return {length=function() return speed end} end,
        getGravity=function() return gravity end, getID=function() return 42 end,
        getEnvTemperature=function() return 298.15 end}
      electrics={values={gearIndex=1,parkingbrake=0,companionLaunchState=2,
        signal_left_input=1,signal_right_input=0,lowbeam=true,highbeam=false}}
      input={throttle=0.75,brake=0.25,steering=-0.5}
      sensors={gx2=-4.905,gy2=9.81}
      energyStorage={getStorages=function() return {
        {type='electricBattery',energyCapacity=360000000,storedEnergy=energy}}
      end}
    ''')
    module=lua.execute((ROOT/'dashboard_mod/lua/vehicle/extensions/companionDashboardTelemetry.lua').read_text())
    return lua,module


class DashboardTests(unittest.TestCase):
    def test_physical_batches_preserve_frames_and_complete_even_usb_writes(self):
        class Port:
            def __init__(self): self.chunks=[]; self.reply=b''
            def write(self,data):
                self.chunks.append(bytes(data)); self.reply=f'ECU RX {len(data)} MFI 3\r\n'.encode(); return len(data)
            def read(self,n): result=self.reply[:n];self.reply=self.reply[n:];return result
        bridge=DashboardBridge(); bridge.serial=Port()
        packets=[encode_snapshot({'clock':765},0xffffffff),encode_snapshot({'clock':765},0)]
        bridge._write_physical_batch(packets)
        self.assertEqual(list(map(len,bridge.serial.chunks)),[64,64,54])
        self.assertEqual(bridge.mfi_confirmed,3)
        receiver=DummyReceiver()
        for chunk in bridge.serial.chunks: receiver.feed(chunk)
        self.assertEqual(receiver.packets,2)
        self.assertEqual(receiver.latest['seq'],0)
        self.assertEqual(b''.join(bridge.serial.chunks),b''.join(packets))
        with self.assertRaises(ValueError): bridge._write_physical_batch(packets[:1])
        bridge.serial.write=lambda data:len(data)-1
        with self.assertRaises(IOError): bridge._write_physical_batch(packets)

    def test_physical_transport_pairs_and_commits_only_complete_batches(self):
        from unittest.mock import patch
        import dashboard_bridge as module
        class Port:
            def __init__(self): self.chunks=[]; self.closed=False; self.reply=b''
            def write(self,data): self.chunks.append(bytes(data)); self.reply=f'ECU RX {len(data)} MFI 3\r\n'.encode(); return len(data)
            def read(self,n): result=self.reply[:n];self.reply=self.reply[n:];return result
            def close(self): self.closed=True
        port=Port(); bridge=DashboardBridge()
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1',0)); udp_port=reservation.getsockname()[1]
        with patch.object(module.serial,'serial_for_url',return_value=port), patch.object(module,'validate_ecu_port'):
            bridge.start('COM5',baud=921600,udp_port=udp_port)
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sender:
                    sender.sendto(json.dumps({'schema':1,'source':'test','values':{'clock':765}}).encode(),('127.0.0.1',udp_port))
                end=time.monotonic()+.35
                while time.monotonic()<end: time.sleep(.005)
            finally: bridge.stop()
        self.assertTrue(port.closed)
        self.assertGreaterEqual(bridge.sent,2)
        self.assertEqual(bridge.sent%2,0)
        self.assertEqual(bridge.bytes_sent,bridge.sent*91)
        self.assertEqual(list(map(len,port.chunks)),[64,64,54]*(bridge.sent//2))
        receiver=DummyReceiver()
        receiver.feed(b''.join(port.chunks))
        self.assertEqual(receiver.packets,bridge.sent)
        self.assertEqual(receiver.latest['seq'],bridge.sent)

    def test_receipt_errors_stop_before_the_next_usb_chunk(self):
        from unittest.mock import patch
        class Port:
            def __init__(self, reply): self.reply=reply; self.writes=0
            def write(self, data): self.writes+=1; return len(data)
            def read(self, n): result=self.reply[:n];self.reply=self.reply[n:];return result
        packets=[encode_snapshot({'clock':765},1)]*2
        for reply in (b'ECU RX 54 MFI 0\n', b'ECU TERMINAL ERROR: MFI TIMEOUT\n', b'x'*161):
            bridge=DashboardBridge();bridge.serial=Port(reply)
            with self.assertRaises(IOError): bridge._write_physical_batch(packets)
            self.assertEqual(bridge.serial.writes,1)
            self.assertEqual(bridge.sent,0)
        bridge=DashboardBridge();bridge.serial=Port(b'')
        with patch('dashboard_bridge.time.monotonic',side_effect=[0,3]):
            with self.assertRaisesRegex(IOError,'timeout'):
                bridge._write_physical_batch(packets)
        self.assertEqual(bridge.serial.writes,1)

    def test_wrong_device_is_rejected_before_opening_port(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import dashboard_bridge as module
        devices=[SimpleNamespace(device='COM5',serial_number=module.ECU_USB_SERIAL),
                 SimpleNamespace(device='COM7',serial_number='147657561600')]
        with patch.object(module.list_ports,'comports',return_value=devices), patch.object(module.serial,'serial_for_url') as opener:
            self.assertEqual(module.ports(),[DUMMY,'COM5'])
            with self.assertRaisesRegex(ValueError,'not the ECU'):
                DashboardBridge().start('COM7')
            opener.assert_not_called()
            module.validate_ecu_port('COM5')

    def test_document_golden_packet(self):
        packet=encode_cells([(0x2b,1234),(0,734),(0x0b,412),(7,1560)])
        self.assertEqual(packet.hex(' ').upper(),'04 AC 00 00 13 48 02 DE 2C 06 70 76 18')
        out=DummyReceiver().feed(packet)[0]
        self.assertEqual(out['seq'],1234)
        self.assertEqual(out['powerKw'],41.2)

    def test_full_packet_fragmentation_coalescing_minima_and_wrap(self):
        packet=encode_snapshot({'clock':4095},0xffffffff)
        self.assertEqual(len(FIELDS),35)
        self.assertEqual(len(packet),91)
        self.assertEqual(packet[0],36)
        for split in range(1,len(packet)):
            receiver=DummyReceiver()
            self.assertEqual(receiver.feed(packet[:split]),[])
            self.assertEqual(receiver.packets,0)
            out=receiver.feed(packet[split:]+encode_snapshot({},0))[0]
            self.assertEqual(receiver.packets,2)
            self.assertEqual(out['seq'],0xffffffff)
            self.assertEqual(receiver.latest['seq'],0)
            self.assertEqual(out['clock'],4095)
            for field in FIELDS:
                if field[1]!='clock': self.assertEqual(out[field[1]],field[4]/field[6])

    def test_clamps_and_signed_values(self):
        out=DummyReceiver().feed(encode_snapshot(dict(speedKmh=999,longitudinalG=-0.7,lateralG=5,powerKw=-41.2,
            steering=-1,throttle=2,brake=-1,tripKm=1e9,flBattery=float('nan')),1))[0]
        self.assertEqual(out['speedKmh'],255)
        self.assertEqual(out['longitudinalG'],-.7)
        self.assertEqual(out['lateralG'],2.047)
        self.assertEqual(out['powerKw'],-41.2)
        self.assertEqual(out['steering'],-1)
        self.assertEqual(out['throttle'],1)
        self.assertEqual(out['brake'],0)
        self.assertEqual(out['tripKm'],4294967.295)
        self.assertEqual(out['flBattery'],0)

    def test_vehicle_signals_energy_reset_and_activation(self):
        messages=[]
        lua,module=vehicle_lua(lambda message:messages.append(json.loads(message)['values']))
        module.updateGFX(.05);self.assertEqual(messages,[])
        module.setActive(True);module.updateGFX(.05)
        lua.globals().energy-=5000;module.updateGFX(.05)
        values=messages[-1]
        self.assertEqual(values['powerKw'],100)
        self.assertEqual(values['longitudinalG'],1)
        self.assertEqual(values['lateralG'],-.5)
        self.assertEqual(values['lowBeam'],1)
        self.assertEqual(values['gear'],2)
        self.assertEqual(values['outsideC'],25)
        self.assertAlmostEqual(values['tripKwh'],5000/3600000)
        lua.globals().energy+=1000;module.updateGFX(.05)
        self.assertEqual(messages[-1]['powerKw'],-20)
        self.assertAlmostEqual(messages[-1]['recoveredKwh'],1000/3600000)
        module.onReset();module.updateGFX(.05)
        self.assertEqual(messages[-1]['powerKw'],0)
        self.assertEqual(messages[-1]['tripKwh'],0)
        module.setActive(False);count=len(messages);module.updateGFX(1)
        self.assertEqual(len(messages),count)
        module.onExtensionUnloaded();self.assertTrue(lua.globals().closed)

    def test_ge_player_switch_and_lua_reload(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          commands={}; player=1
          function vehicle(id) return {getID=function() return id end,
            queueLuaCommand=function(self,cmd) table.insert(commands,{id,cmd}) end} end
          be={getObjectByID=function(self,id) return vehicle(id) end}
          function getPlayerVehicle() return player and vehicle(player) end
        ''')
        ge=lua.execute((ROOT/'dashboard_mod/lua/ge/extensions/companionDashboard.lua').read_text())
        ge.onUpdate(.25)
        self.assertIn('setActive(true)',lua.globals().commands[1][2])
        lua.globals().player=2;ge.onUpdate(.25)
        self.assertEqual(lua.globals().commands[2][1],1)
        self.assertIn('setActive(false)',lua.globals().commands[2][2])
        self.assertEqual(lua.globals().commands[3][1],2)
        ge.onUpdate(.25);self.assertIn('extensions.load',lua.globals().commands[4][2])
        ge.onExtensionUnloaded();self.assertIn('setActive(false)',lua.globals().commands[5][2])

    def test_live_lua_udp_serial_dummy_24hz(self):
        bridge=DashboardBridge();sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            bridge.start(DUMMY,921600,udp_port=0)
            destination=bridge.udp.getsockname()
            lua,module=vehicle_lua(lambda message:sender.sendto(message.encode(),destination))
            module.setActive(True)
            start=time.monotonic();deadline=start
            while time.monotonic()-start<2.5:
                lua.globals().energy-=100000/60
                module.updateGFX(1/60)
                deadline+=1/60
                time.sleep(max(0,deadline-time.monotonic()))
            duration=time.monotonic()-start
            self.assertTrue(bridge.beamng_connected)
            self.assertIn('BeamNG: Connected', bridge.beamng_status)
            # Same freshness boundary as serial output, without extending the live test.
            from unittest.mock import patch
            with patch('dashboard_bridge.time.monotonic', return_value=bridge.last_telemetry_at + 1.01):
                self.assertFalse(bridge.beamng_connected)
                self.assertIn('Not connected', bridge.beamng_status)
            bridge.stop()
            self.assertFalse(bridge.beamng_connected)
            self.assertTrue(54<=bridge.sent<=64,(bridge.sent,duration,bridge.status))
            self.assertEqual(bridge.receiver.packets,bridge.sent)
            self.assertEqual(bridge.bytes_sent,bridge.sent*91)
            result=bridge.receiver.latest
            self.assertEqual(result['speedKmh'],72)
            self.assertEqual(result['longitudinalG'],1)
            self.assertEqual(result['lateralG'],-.5)
            self.assertEqual(result['launch'],2)
            self.assertEqual(result['powerKw'],100)
            self.assertEqual(result['flTemperature'],-3276.8)
            self.assertEqual(result['seq'],bridge.sent)
            print(f'\nDashboard integration: {bridge.sent} packets / {duration:.2f}s, {bridge.bytes_sent} bytes; Lua -> UDP -> serial loopback -> dummy decoded correctly.')
        finally:
            bridge.stop();sender.close()

    def test_no_send_without_fresh_data_and_port_validation(self):
        bridge=DashboardBridge()
        with self.assertRaises(ValueError): bridge.start('socket://example.org:1')
        with self.assertRaises(ValueError): bridge.start(DUMMY,9600)
        try:
            bridge.start(DUMMY,udp_port=0)
            time.sleep(.12)
            self.assertEqual(bridge.sent,0)
            self.assertFalse(bridge.beamng_connected)
            self.assertIn('waiting for vehicle telemetry',bridge.beamng_status)
        finally: bridge.stop()


if __name__=='__main__': unittest.main()
