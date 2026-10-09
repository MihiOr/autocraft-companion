"""Stock performance tire tuning and four-motor control packaging."""
import json
import math
import re
from pathlib import Path

DEFAULT_TIRE_PROFILE = 'Scintilla Sport Plus'
LEGACY_TIRE_PROFILE = 'Legacy grip only'
TIRE_PROFILES = (DEFAULT_TIRE_PROFILE, 'Scintilla Race Slicks', LEGACY_TIRE_PROFILE)
PRESET_FILE = 'companion_tire_presets.jbeam'
PRESET_IDS = {'Scintilla Sport Plus':'sport_plus', 'Scintilla Race Slicks':'race_slicks',
              LEGACY_TIRE_PROFILE:'legacy'}
TIRE_PART_IDS = {DEFAULT_TIRE_PROFILE:'sport_plus', 'Scintilla Race Slicks':'race_slicks',
                 LEGACY_TIRE_PROFILE:'legacy', 'AutoCraft original':'autocraft'}


def stock_profiles():
    return json.loads(Path(__file__).with_name('performance_tires.json').read_text(encoding='utf-8'))['profiles']


def tire_params(profile, axle, grip, carcass, node_mass):
    from patcher import PatchError
    if profile == LEGACY_TIRE_PROFILE:
        return {'frictionCoef':grip, 'slidingFrictionCoef':grip*.9,
                'noLoadCoef':1.1, 'fullLoadCoef':.9, 'loadSensitivitySlope':.00015,
                'softnessCoef':.8, 'treadCoef':.1, 'stribeckExponent':1.75,
                'stribeckVelMult':1}, None
    donor = stock_profiles()[profile][axle]
    params = dict(donor['rubber'])
    for key in ('frictionCoef', 'slidingFrictionCoef'):
        params[key] *= grip
    scale = None
    if carcass:
        if node_mass is None or not math.isfinite(node_mass) or node_mass <= 0:
            raise PatchError('Stock tire carcass requires a positive numeric tire node mass.')
        scale = node_mass / donor['reference_node_mass']
        for key, value in donor['carcass'].items():
            # Match the donor's k/m and c/m instead of putting full-size stiffness
            # on extremely light nodes from the vehicle weight patch.
            if re.fullmatch(r'wheel\w*Beam(?:Spring|Damp)(?:Expansion)?', key):
                if isinstance(value, str):
                    if not value.startswith('$='):
                        raise PatchError('Unsupported stock tire spring expression.')
                    value = '$=(' + value[2:] + ')*' + format(scale, '.12g')
                else:
                    value *= scale
            params[key] = value
    return params, scale


def wheel_part(text, axle, title):
    """Copy one complete wheel part without rewriting comma-optional JBeam."""
    from patcher import JBeam, edits, PatchError
    doc=JBeam(text);part=doc.prop(0,'wheels_'+axle);props=dict(doc.props(part));changes=[]
    if 'slotType' in props:
        if json.loads(doc.tokens[props['slotType']].value)!='wheels_'+axle:
            raise PatchError('Unexpected wheel slot type for axle '+axle)
    else:
        start=doc.tokens[part].end
        changes.append((start,start,'"slotType":'+json.dumps('wheels_'+axle)+','))
    if 'information' in props:
        info=props['information'];name=dict(doc.props(info)).get('name')
        if name is not None:changes.append((*doc.span(name),json.dumps(title)))
        else:
            start=doc.tokens[info].end
            changes.append((start,start,'"name":'+json.dumps(title)+','))
    else:
        start=doc.tokens[part].end
        changes.append((start,start,'"information":'+json.dumps({'authors':'MiNini / BeamNG tire tuning','name':title})+','))
    start,end=doc.span(part)
    # Keep edits in part-local coordinates, including comments and expressions.
    return edits(text[start:end],[(a-start,b-start,value) for a,b,value in changes])


def in_game_presets(original, patched, prefix, settings, selected):
    from patcher import JBeam
    baseline=dict(original)
    old_presets=baseline.get(prefix+PRESET_FILE)
    if old_presets is not None:
        # Direct reapply also needs the unmodified AutoCraft tire baseline.
        doc=JBeam(old_presets.decode('utf-8-sig'))
        for axle in ('F','R'):
            part=doc.prop(0,'companion_tires_'+axle+'_autocraft')
            baseline[prefix+'wheels_'+axle+'.jbeam']=('{"wheels_'+axle+'":'+
                doc.text[slice(*doc.span(part))]+'}').encode()
    parts=[]
    for profile in (None,*TIRE_PROFILES):
        source=baseline
        if profile is not None:
            source=apply(baseline,prefix,dict(settings,ev_tire_profile=profile,
                         ev_tire_ingame=False,ev_ecu_mode='Off'))
        for axle,side in (('F','front'),('R','rear')):
            name=prefix+'wheels_'+axle+'.jbeam'
            tag=PRESET_IDS[profile] if profile is not None else 'autocraft'
            title=(profile if profile is not None else 'AutoCraft original')+' tires ('+side+')'
            body=wheel_part(source[name].decode('utf-8-sig'),axle,title)
            parts.append(json.dumps('companion_tires_'+axle+'_'+tag)+':'+body)
    result=dict(patched)
    result[prefix+PRESET_FILE]=('{\n'+',\n'.join(parts)+'\n}\n').encode()
    for axle,side in (('F','front'),('R','rear')):
        name=prefix+'wheels_'+axle+'.jbeam'
        title='Companion default: '+selected+' ('+side+')'
        result[name]=('{"wheels_'+axle+'":'+wheel_part(result[name].decode('utf-8-sig'),axle,title)+'}\n').encode()
    return result


def validate(settings):
    from patcher import number, PatchError
    result = {}
    if settings.get('ev_tire_enabled'):
        result['grip'] = number(settings, 'ev_tire_grip', 0.2, 3)
        result['profile'] = settings.get('ev_tire_profile', LEGACY_TIRE_PROFILE)
        if result['profile'] not in TIRE_PROFILES:
            raise PatchError('Choose a supported tire preset.')
        result['carcass'] = bool(settings.get('ev_tire_carcass', True)) and result['profile'] != LEGACY_TIRE_PROFILE
        result['ingame'] = bool(settings.get('ev_tire_ingame', False))
    mode = settings.get('ev_ecu_mode', 'Off')
    if mode not in ('Off', 'Traction control', 'Launch + traction control', 'Custom Lua'):
        raise PatchError('Unknown electric ECU mode.')
    result['mode'] = mode
    if mode not in ('Off', 'Custom Lua'):
        result['slip'] = number(settings, 'ev_tc_slip', 1, 30) / 100
        result['launch_slip'] = number(settings, 'ev_launch_slip', 1, 30) / 100
        result['ramp'] = number(settings, 'ev_launch_ramp', 0, 3)
    return result


def disable_friction_brakes(entries, prefix):
    """Disable service friction brakes while preserving physical parking brakes."""
    from patcher import JBeam, edits
    result=dict(entries)
    for name,raw in entries.items():
        if not name.startswith(prefix) or not name.endswith('.jbeam'):
            continue
        doc=JBeam(raw.decode('utf-8-sig'));changes=[]
        for _,part in doc.props(0):
            if doc.tokens[part].value!='{':continue
            tables=dict(doc.props(part))
            for key in ('pressureWheels','wheels','rotators'):
                table=tables.get(key)
                if table is None or doc.tokens[table].value!='[':continue
                for i in range(table+1,doc.ends[table]-1):
                    token=doc.tokens[i].value
                    prop=json.loads(token) if token.startswith('"') else token
                    if prop in ('brakeTorque','enableBrakeThermals') and doc.tokens[i+1].value==':':
                        changes.append((*doc.span(i+2),'false' if prop=='enableBrakeThermals' else '0'))
                header=next((i for i in range(table+1,doc.ends[table]) if doc.tokens[i].value=='['),None)
                if header is not None:
                    end=doc.tokens[doc.ends[header]].end
                    following=doc.ends[header]+1
                    while following<doc.ends[table] and doc.tokens[following].value==',':following+=1
                    from wheel_attachment_patch import properties
                    defaults=properties(doc,following) if doc.tokens[following].value=='{' else {}
                    if not {'brakeTorque','enableBrakeThermals'} <= defaults.keys():
                        changes.append((end,end,', {"brakeTorque":0,"enableBrakeThermals":false}'))
        if changes:result[name]=edits(doc.text,changes).encode()
    return result


def apply(entries, prefix, settings):
    from patcher import JBeam, edits, PatchError
    from electric_patch import values
    options = validate(settings)
    result = dict(entries)
    if 'grip' in options:
        grip = options['grip']
        options['wheels'] = {}
        for axle in ('F','R'):
            name = prefix+'wheels_'+axle+'.jbeam'
            d = JBeam(result[name].decode());part = d.prop(0,'wheels_'+axle)
            table = d.prop(part,'pressureWheels');reps=[];count=0
            state={}; row=table+1
            while row<d.ends[table]:
                if d.tokens[row].value=='{':
                    state.update(dict(d.props(row)))
                if d.tokens[row].value!='[':
                    row=d.ends.get(row,row)+1
                    continue
                val=values(d,row)
                if not val or val[0]=='name':
                    row=d.ends[row]+1
                    continue
                if val[0] not in (axle+'L',axle+'R'):
                    raise PatchError('Unexpected pressure wheel on axle '+axle)
                # Add options to each wheel row, overriding inherited defaults.
                inline=next((i for i in range(row+1,d.ends[row]) if d.tokens[i].value=='{'),None)
                props=dict(d.props(inline)) if inline is not None else {}
                local=dict(state);local.update(props)
                mass=None
                if 'nodeWeight' in local:
                    try:mass=float(d.tokens[local['nodeWeight']].value)
                    except ValueError:pass
                params,scale=tire_params(options['profile'],axle,grip,options['carcass'],mass)
                options['wheels'][val[0]]={'carcass_mass_scale':scale,'tire_node_mass_kg':mass}
                if inline is not None:
                    missing={}
                    for key,value in params.items():
                        if key in props:reps.append((*d.span(props[key]),json.dumps(value)))
                        else:missing[key]=value
                    if missing:
                        start=d.tokens[inline].end
                        reps.append((start,start,json.dumps(missing)[1:-1]+(',' if props else '')))
                else:
                    end=d.tokens[d.ends[row]].start
                    comma='' if d.tokens[d.ends[row]-1].value==',' else ','
                    reps.append((end,end,comma+json.dumps(params)))
                count+=1
                row=d.ends[row]+1
            if count!=2:raise PatchError('Expected two pressure wheels for axle '+axle)
            result[name]=edits(d.text,reps).encode()
    if options['mode']=='Custom Lua':
        from custom_control import source_for_export, check_code, build_controller
        source = source_for_export()
        check_code(source)
        name=prefix+'engine.jbeam';engine=json.loads(result[name]);part=engine['engine']
        part['controller']=[['fileName'],['companion_custom_ecu',{}]]
        from imu_patch import mounts
        imu=mounts(result,prefix)
        if imu:
            vehicle_report=json.loads(result[prefix+'companion_ev_report.json'])
            patched_mass=vehicle_report.get('weight',{}).get('total_kg')
            if patched_mass is not None:
                imu['mass']=float(patched_mass)
            part['controller'][1][1]['imu']=imu
            options['imu']=imu
        # Keep the stock selector/dashboard, but disable its automatic stopping/regen helpers.
        part.setdefault('vehicleController', {}).update(arcadeAutoBrakeAmount=0,
            onePedalRegenCoef=0, onePedalFrictionBrakeCoef=0, defaultRegenStrength=0)
        for wheel in ('FL','FR','RL','RR'):
            motor=part['evMotor'+wheel]
            # Match the drive torque/power envelope. The stock 1000 RPM regen
            # fade is inappropriate for a low-RPM direct-drive motor.
            motor.pop('regenTorqueCurve',None)
            motor.pop('maxRegenTorque',None)
            motor.pop('maxRegenPower',None)
            motor.update(electricsThrottleName='companionCustom'+wheel,
                electricsThrottleFactorName='companionCustomFactor',
                electricsRegenThrottleName='companionCustomRegen'+wheel, regenFadeRPM=30,
                minimumWantedRegenTorque=0,
                isAffectedByIgnition=False)
            multiplier=float(str(settings.get('ev_torque_multiplier',1)).replace(',','.'))
            if multiplier!=1:
                # Vertical scaling changes propulsion only; preserve the prior
                # regenerative envelope and its existing 30 RPM fade.
                motor['regenTorqueCurve']=[['rpm','torque']]+[
                    [rpm,torque/multiplier*min(1,rpm/30)] for rpm,torque in motor['torque'][1:]]
        options['friction_brakes']='disabled; hardware retained'
        options['regeneration']='per-wheel custom Lua; full motor envelope'
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
    if options.get('ingame'):
        result=in_game_presets(entries,result,prefix,settings,options['profile'])
    if options['mode']=='Custom Lua':
        result=disable_friction_brakes(result,prefix)
    return result
