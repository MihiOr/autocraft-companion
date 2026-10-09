"""Opt-in tire friction settings and four-motor slip control."""
import json
from pathlib import Path


def validate(settings):
    from patcher import number, PatchError
    result = {}
    if settings.get('ev_tire_enabled'):
        result['grip'] = number(settings, 'ev_tire_grip', 0.2, 3)
    mode = settings.get('ev_ecu_mode', 'Off')
    if mode not in ('Off', 'Traction control', 'Launch + traction control', 'Custom Lua'):
        raise PatchError('Unknown electric ECU mode.')
    result['mode'] = mode
    if mode not in ('Off', 'Custom Lua'):
        result['slip'] = number(settings, 'ev_tc_slip', 1, 30) / 100
        result['launch_slip'] = number(settings, 'ev_launch_slip', 1, 30) / 100
        result['ramp'] = number(settings, 'ev_launch_ramp', 0, 3)
    return result


def apply(entries, prefix, settings):
    from patcher import JBeam, edits, PatchError
    from electric_patch import rows, values
    options = validate(settings)
    result = dict(entries)
    if 'grip' in options:
        grip = options['grip']
        params = {'frictionCoef':grip, 'slidingFrictionCoef':grip*.9,
                  'noLoadCoef':1.1, 'fullLoadCoef':.9, 'loadSensitivitySlope':.00015,
                  'softnessCoef':.8, 'treadCoef':.1, 'stribeckExponent':1.75}
        for axle in ('F','R'):
            name = prefix+'wheels_'+axle+'.jbeam'
            d = JBeam(result[name].decode());part = d.prop(0,'wheels_'+axle)
            table = d.prop(part,'pressureWheels');reps=[];count=0
            for row in rows(d,table):
                val=values(d,row)
                if not val or val[0]=='name':continue
                # Add options to each wheel row, overriding inherited defaults.
                inline=next((i for i in range(row+1,d.ends[row]) if d.tokens[i].value=='{'),None)
                if inline is not None:
                    props=dict(d.props(inline))
                    missing={}
                    for key,value in params.items():
                        if key in props:reps.append((*d.span(props[key]),json.dumps(value)))
                        else:missing[key]=value
                    if missing:
                        start=d.tokens[inline].end
                        reps.append((start,start,json.dumps(missing)[1:-1]+','))
                else:
                    end=d.tokens[d.ends[row]].start
                    reps.append((end,end,','+json.dumps(params)))
                count+=1
            if count!=2:raise PatchError('Expected two pressure wheels for axle '+axle)
            result[name]=edits(d.text,reps).encode()
    if options['mode']=='Custom Lua':
        from custom_control import USER_FILE, check_code, build_controller
        source = USER_FILE.read_text(encoding='utf-8-sig')
        check_code(source)
        name=prefix+'engine.jbeam';engine=json.loads(result[name]);part=engine['engine']
        part['controller']=[['fileName'],['companion_custom_ecu',{}]]
        # Keep the stock selector/dashboard, but disable its automatic stopping/regen helpers.
        part.setdefault('vehicleController', {}).update(arcadeAutoBrakeAmount=0,
            onePedalRegenCoef=0, onePedalFrictionBrakeCoef=0, defaultRegenStrength=0)
        for wheel in ('FL','FR','RL','RR'):
            part['evMotor'+wheel].update(electricsThrottleName='companionCustom'+wheel,
                electricsThrottleFactorName='companionCustomFactor',
                electricsRegenThrottleName='companionCustomRegen', maxRegenTorque=0,
                isAffectedByIgnition=False)
        result[name]=(json.dumps(engine,indent=2)+'\n').encode()
        result[prefix+'lua/controller/companion_custom_ecu.lua']=build_controller(source).encode('utf-8')
        result[prefix+'custom_motor_control.lua']=source.encode('utf-8')
    elif options['mode']!='Off':
        name=prefix+'engine.jbeam';engine=json.loads(result[name]);part=engine['engine']
        part['controller']=[['fileName'],['companion_ev_ecu',{
            'targetSlip':options['slip'],'launchSlip':options['launch_slip'],
            'launchRamp':options['ramp'],'launchEnabled':options['mode']=='Launch + traction control'}]]
        for wheel in ('FL','FR','RL','RR'):
            part['evMotor'+wheel]['electricsThrottleFactorName']='companionTorque'+wheel
        result[name]=(json.dumps(engine,indent=2)+'\n').encode()
        result[prefix+'lua/controller/companion_ev_ecu.lua']=Path(__file__).with_name('companion_ev_ecu.lua').read_bytes()
    report_path=prefix+'companion_ev_report.json'
    report=json.loads(result[report_path]);report['tire_ecu']=options
    result[report_path]=(json.dumps(report,indent=2)+'\n').encode()
    return result
