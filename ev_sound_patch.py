"""Built-in EV sound, without the legacy combustion fallback."""
import json
from pathlib import Path


def apply(entries, prefix, settings):
    from patcher import number
    enabled = settings.get('ev_sound_enabled', True)
    gain = number({'gain':settings.get('ev_sound_gain', -9)}, 'gain', -60, 6)
    pitch = number({'pitch':settings.get('ev_sound_pitch', 6.7)}, 'pitch', .5, 15)
    result = dict(entries)
    name = prefix+'engine.jbeam'
    data = json.loads(result[name]);part = data['engine']
    for wheel in ('FL','FR','RL','RR'):
        motor = part['evMotor'+wheel]
        motor.pop('soundConfigExhaust', None)
        if enabled:
            config = 'companionEVSound'+wheel
            motor['soundConfig'] = config
            part[config] = {'sampleName':'ElectricMotor_02', 'mainGain':gain,
                'onLoadGain':1, 'offLoadGain':.45, 'lowCutFreq':180,
                'eqLowFreq':350, 'eqLowGain':-5, 'eqHighFreq':2400, 'eqHighGain':2,
                'rpmSmootherInRate':25, 'rpmSmootherOutRate':30}
    part.setdefault('controller', [['fileName']]).append(['companion_ev_sound', {'pitchScale':pitch}])
    result[name]=(json.dumps(data,indent=2)+'\n').encode()
    result[prefix+'lua/controller/companion_ev_sound.lua']=Path(__file__).with_name('companion_ev_sound.lua').read_bytes()
    report_name=prefix+'companion_ev_report.json'
    report=json.loads(result[report_name]);report['sound']={'enabled':enabled,'sample':'ElectricMotor_02',
        'gain_db_per_motor':gain,'audio_rpm_scale':pitch,'legacy_engine_sound':False}
    result[report_name]=(json.dumps(report,indent=2)+'\n').encode()
    return result
