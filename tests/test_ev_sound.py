import json
from pathlib import Path
import sys
import unittest

from ev_sound_patch import apply


class SoundTests(unittest.TestCase):
    def test_sound_config_preserves_ecu_and_supports_silent_mode(self):
        prefix = 'vehicles/Car/'
        part = {'evMotor'+w: {} for w in ('FL', 'FR', 'RL', 'RR')}
        part['controller'] = [['fileName'], ['companion_ev_ecu', {}]]
        entries = {prefix+'engine.jbeam': json.dumps({'engine': part}).encode(),
                   prefix+'companion_ev_report.json': b'{}'}
        for enabled in (True, False):
            result = apply(entries, prefix, {'ev_sound_enabled': enabled})
            engine = json.loads(result[prefix+'engine.jbeam'])['engine']
            self.assertEqual(engine['controller'][1][0], 'companion_ev_ecu')
            self.assertEqual(engine['controller'][2][0], 'companion_ev_sound')
            for wheel in ('FL', 'FR', 'RL', 'RR'):
                self.assertEqual('soundConfig' in engine['evMotor'+wheel], enabled)
                if enabled:
                    self.assertEqual(engine[engine['evMotor'+wheel]['soundConfig']]['sampleName'], 'ElectricMotor_02')
            self.assertIn(prefix+'lua/controller/companion_ev_sound.lua', result)

    def test_audio_scaling_and_legacy_silencing_do_not_change_motor_speed(self):
        from lupa import LuaRuntime
        lua = LuaRuntime()
        lua.execute('''
            disabled=0
            sounds={disableOldEngineSounds=function() disabled=disabled+1 end,
                    hzToFMODHz=function(hz) return hz end}
            obj={setEngineSound=function(self,id,rpm,load,freq,volume) lastRPM=rpm end}
            motor={outputAV1=10, instantEngineLoad=1, soundMinLoadMix=0,
                   soundMaxLoadMix=1, engineSoundID=0, engineVolumeCoef=1,
                   fundamentalFrequencyRPMCoef=0.05,
                   soundRPMSmoother={get=function(self,v,dt) return v end},
                   soundLoadSmoother={get=function(self,v,dt) return v end}}
            powertrain={getDevice=function(name) return motor end}
        ''')
        controller = lua.execute((Path(__file__).parents[1]/'companion_ev_sound.lua').read_text())
        controller.init(lua.table_from({'pitchScale': 6.7}))
        controller.initSounds()
        controller.resetSounds()
        controller.updateGFX()
        lua.execute('motor:updateSounds(0.01)')
        self.assertEqual(lua.globals().disabled, 2)
        self.assertEqual(lua.globals().motor.outputAV1, 10)
        self.assertAlmostEqual(lua.globals().lastRPM, 10*9.5492965855*6.7)
