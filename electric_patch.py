"""Four direct-drive motors for the known AutoCraft double-wishbone export."""
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def read_curve(path, mode='Wheel output (direct drive)'):
    from patcher import PatchError
    points = []
    try:
        with Path(path).open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                wheel, motor, torque, power = [float(row[k]) for k in
                    ('wheel_rpm', 'motor_rpm', 'wheel_torque_nm', 'wheel_power_kw')]
                if not all(math.isfinite(x) and x >= 0 for x in (wheel, motor, torque, power)):
                    raise ValueError('Values must be finite and nonnegative.')
                if abs(wheel * torque * math.pi / 30000 - power) > max(.02, power * .01):
                    raise ValueError('Power does not match wheel RPM and torque.')
                if mode == 'Motor shaft (no reduction)':
                    if wheel > 0 and motor <= 0:
                        raise ValueError('Motor RPM must be positive when the wheel rotates.')
                    points.append([motor, torque * wheel / motor if motor else None])
                else:
                    points.append([wheel, torque])
        if len(points) < 3 or points[0][0] != 0 or any(b[0] <= a[0] for a, b in zip(points, points[1:])):
            raise ValueError('RPM must start at zero and strictly increase.')
        if points[0][1] is None:
            points[0][1] = points[1][1]
    except (OSError, ValueError, KeyError) as exc:
        raise PatchError('Electric dyno CSV: ' + str(exc)) from exc
    return points


def ratio_settings(settings):
    from patcher import number
    enabled = bool(settings.get('ev_ratio_enabled', False))
    if not enabled:
        return {'enabled': False, 'torque_scale': 1.0, 'rpm_scale': 1.0}
    defaults = dict(ev_original_ratio='5.4', ev_ratio='4.3', ev_reference_speed='130')
    defaults.update(settings)
    original = number(defaults, 'ev_original_ratio', .1, 30)
    ratio = number(defaults, 'ev_ratio', .1, 30)
    speed = number(defaults, 'ev_reference_speed', 1, 1000)
    return dict(enabled=True, original_ratio=original, ratio=ratio,
                torque_scale=ratio/original, rpm_scale=original/ratio,
                reference_speed_kmh=speed, estimated_speed_kmh=speed*original/ratio)


def scale_curve(curve, ratio):
    return [[rpm*ratio['rpm_scale'], torque*ratio['torque_scale']] for rpm,torque in curve]


def electric_settings(settings):
    from patcher import number, PatchError
    from tire_ecu_patch import validate
    validate(settings)
    if settings.get('ev_weight_enabled'):
        base = number(settings, 'ev_base_mass', 1, 10000)
        motors = 4 * number(settings, 'ev_motor_mass', 5, 300)
        number(settings, 'ev_passenger_left', 0, 500)
        number(settings, 'ev_passenger_right', 0, 500)
        if base <= motors:
            raise PatchError('Base vehicle mass must exceed the total motor mass (four motors).')
    ratio = ratio_settings(settings)
    curve = read_curve(settings.get('ev_csv', ''), settings.get('ev_curve_mode', 'Wheel output (direct drive)'))
    return {
        'capacity': number(settings, 'ev_capacity', 1, 1000),
        'battery_mass': number(settings, 'ev_battery_mass', 1, 5000),
        'motor_mass': number(settings, 'ev_motor_mass', 5, 300),
        'inertia': number(settings, 'ev_inertia', .001, 10),
        'regen': number(settings, 'ev_regen', 0, 100),
        'curve': scale_curve(curve, ratio),
        'ratio_override': ratio,
    }


def rows(doc, array):
    i = array + 1
    while i < doc.ends[array]:
        if doc.tokens[i].value == '[':
            yield i
        i = doc.ends.get(i, i) + 1


def values(doc, row):
    result = []
    i = row + 1
    while i < doc.ends[row]:
        t = doc.tokens[i].value
        if t != ',':
            if t in ('{', '['):
                break
            try:
                result.append(json.loads(t))
            except ValueError:
                result.append(t)
        i += 1
    return result


def node_positions(text):
    from patcher import JBeam, PatchError
    d = JBeam(text)
    result = {}
    for _, part in d.props(0):
        for key, v in d.props(part):
            if key == 'nodes':
                for row in rows(d, v):
                    vals = values(d, row)
                    if len(vals) >= 4 and vals[0] != 'id':
                        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vals[1:4]):
                            raise PatchError('Electric conversion requires numeric exported node coordinates.')
                        result[vals[0]] = vals[1:4]
    return result


def strip_rows(text, removed, slots=False):
    from patcher import JBeam, edits
    d = JBeam(text)
    replacements = []
    for _, part in d.props(0):
        for key, v in d.props(part):
            if d.tokens[v].value != '[':
                continue
            for row in rows(d, v):
                vals = values(d, row)
                if any(isinstance(x, str) and x in removed for x in vals) or (
                    slots and key == 'slots' and vals and vals[0] in ('drivetrain', 'radiator', 'fueltank')):
                    start, end = d.span(row)
                    if d.tokens[d.ends[row] + 1].value == ',':
                        end = d.tokens[d.ends[row] + 1].end
                    replacements.append((start, end, ''))
    return edits(text, replacements)


def mesh_dae(meshes):
    """Simple replacement housings and shafts, sized in metres at node endpoints."""
    root = ET.Element('COLLADA', xmlns='http://www.collada.org/2005/11/COLLADASchema', version='1.4.1')
    asset = ET.SubElement(root, 'asset')
    ET.SubElement(asset, 'unit', name='meter', meter='1')
    ET.SubElement(asset, 'up_axis').text = 'Z_UP'
    effects = ET.SubElement(root, 'library_effects')
    effect = ET.SubElement(effects, 'effect', id='ev_metal_fx')
    profile = ET.SubElement(effect, 'profile_COMMON')
    technique = ET.SubElement(profile, 'technique', sid='common')
    phong = ET.SubElement(technique, 'phong')
    ET.SubElement(ET.SubElement(phong, 'diffuse'), 'color').text = '0.25 0.28 0.32 1'
    mats = ET.SubElement(root, 'library_materials')
    ET.SubElement(ET.SubElement(mats, 'material', id='ev_metal', name='ev_metal'), 'instance_effect', url='#ev_metal_fx')
    geoms = ET.SubElement(root, 'library_geometries')
    scene = ET.SubElement(ET.SubElement(root, 'library_visual_scenes'), 'visual_scene', id='Scene')
    for name, verts, tris in meshes:
        geom = ET.SubElement(geoms, 'geometry', id=name, name=name)
        mesh = ET.SubElement(geom, 'mesh')
        src = ET.SubElement(mesh, 'source', id=name + '_pos')
        ET.SubElement(src, 'float_array', id=name + '_array', count=str(len(verts)*3)).text = ' '.join(f'{x:.9g}' for v in verts for x in v)
        accessor = ET.SubElement(ET.SubElement(src, 'technique_common'), 'accessor', source='#'+name+'_array', count=str(len(verts)), stride='3')
        for axis in 'XYZ': ET.SubElement(accessor, 'param', name=axis, type='float')
        vertices = ET.SubElement(mesh, 'vertices', id=name + '_verts')
        ET.SubElement(vertices, 'input', semantic='POSITION', source='#'+name+'_pos')
        triangles = ET.SubElement(mesh, 'triangles', count=str(len(tris)), material='ev_metal')
        ET.SubElement(triangles, 'input', semantic='VERTEX', source='#'+name+'_verts', offset='0')
        ET.SubElement(triangles, 'p').text = ' '.join(str(i) for tri in tris for i in tri)
        instance = ET.SubElement(ET.SubElement(scene, 'node', id=name, name=name), 'instance_geometry', url='#'+name)
        ET.SubElement(ET.SubElement(ET.SubElement(instance, 'bind_material'), 'technique_common'), 'instance_material', symbol='ev_metal', target='#ev_metal')
    ET.SubElement(ET.SubElement(root, 'scene'), 'instance_visual_scene', url='#Scene')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def cylinder(a, b, radius):
    axis = [b[i]-a[i] for i in range(3)]
    length = math.sqrt(sum(x*x for x in axis))
    axis = [x/length for x in axis]
    u = [axis[1], -axis[0], 0]
    norm = math.sqrt(sum(x*x for x in u))
    u = [x/norm for x in u]
    v = [axis[1]*u[2]-axis[2]*u[1], axis[2]*u[0]-axis[0]*u[2], axis[0]*u[1]-axis[1]*u[0]]
    verts = [[p[k]+radius*(u[k]*math.cos(i*math.pi/8)+v[k]*math.sin(i*math.pi/8)) for k in range(3)] for p in (a,b) for i in range(16)]
    tris = []
    for i in range(16):
        j=(i+1)%16
        tris.extend([(i,j,16+j),(i,16+j,16+i)])
    for i in range(1,15): tris.extend([(0,i+1,i),(16,16+i,16+i+1)])
    return verts,tris


def convert(entries, root, settings):
    from patcher import PatchError, JBeam, edits
    options = electric_settings(settings)
    prefix = f'vehicles/{root}/'
    old = {}
    for file in ('engine', 'drivetrain', 'radiator', 'fueltank'):
        path = prefix + file + '.jbeam'
        if path not in entries: raise PatchError('Electric conversion missing ' + path)
        old.update(node_positions(entries[path].decode('utf-8-sig')))
    positions = {}
    for file in ('main', 'suspension_F', 'suspension_R'):
        positions.update(node_positions(entries[prefix+file+'.jbeam'].decode('utf-8-sig')))
    result = dict(entries)
    for file in ('drivetrain', 'radiator', 'fueltank'):
        result.pop(prefix+file+'.jbeam')
    for name, raw in list(result.items()):
        if name.startswith(prefix) and name.endswith('.jbeam') and name != prefix+'engine.jbeam':
            text = strip_rows(raw.decode('utf-8-sig'), set(old)-set(positions), slots=True)
            # Remove combustion/fire payload from chassis nodes, preserving their structure.
            import re
            text = re.sub(r'"(?:engineGroup|chemEnergy|burnRate|smokePoint|flashPoint)"\s*:\s*(?:\[[^\]]*\]|"[^"]*"|[-+0-9.eE]+)\s*,?', '', text)
            result[name] = text.encode()
    part = {'information': {'authors':'AutoCraft Companion', 'name':'Four direct-drive electric motors'},
            'slotType':'engine', 'slots':[['type','default','description']],
            'powertrain':[['type','name','inputName','inputIndex']],
            'vehicleController':{'shiftLogicName':'electricMotor', 'motorNames':[], 'defaultAutomaticMode':'N',
                                 'topSpeedLimitReverse':15, 'defaultRegenStrength':0, 'onePedalRegenCoef':0},
            'energyStorage':[['type','name'],['electricBattery','mainBattery']],
            'mainBattery':{'energyType':'electricEnergy','batteryCapacity':options['capacity'],'startingCapacity':options['capacity']},
            'nodes':[['id','posX','posY','posZ']], 'beams':[['id1:','id2:']],
            'flexbodies':[['mesh','[group]:','nonFlexMaterials']]}
    report = {'mode':settings.get('ev_curve_mode'), 'csv_sha256':hashlib.sha256(Path(settings['ev_csv']).read_bytes()).hexdigest(),
              'battery_kwh':options['capacity'], 'battery_mass_kg':options['battery_mass'], 'shafts':{},
              'ratio_override':options['ratio_override']}
    meshes=[]
    for wheel in ('FL','FR','RL','RR'):
        axle, side = wheel[0].lower(), wheel[1].lower()
        hub1,hub2 = axle+'w1'+side, axle+'w2'+side
        anchors = [axle+'x'+str(i)+side for i in (1,2,3,4)]
        if any(n not in positions for n in [hub1,hub2]+anchors):
            raise PatchError('Electric geometry requires AutoCraft double-wishbone nodes for '+wheel)
        sign = 1 if side=='l' else -1
        hub = [(a+b)/2 for a,b in zip(positions[hub1],positions[hub2])]
        out = [hub[0],positions[anchors[2]][1],hub[2]]
        if sign*(hub[1]-out[1]) < .25: raise PatchError('Not enough room for an inboard motor at '+wheel)
        center=[out[0],out[1]-.10*sign,out[2]]
        motor='evMotor'+wheel; group='ev_'+wheel
        coords=[out,[center[0]-.10,center[1]-.08*sign,center[2]-.08],
                [center[0]+.10,center[1]-.08*sign,center[2]-.08],
                [center[0],center[1]-.08*sign,center[2]+.10]]
        ids=[group+str(i) for i in range(4)]
        for node,pos in zip(ids,coords):
            part['nodes'].append([node,*pos,{'nodeWeight':options['motor_mass']/4,'collision':False,'selfCollision':False,'group':[group]}])
        for a,b in list(itertools.combinations(ids,2))+[(n,a) for n in ids for a in anchors]:
            part['beams'].append([a,b,{'beamSpring':1500000,'beamDamp':100,'beamDeform':150000,'beamStrength':'FLT_MAX'}])
        # Shaft torque is transmitted by the 1:1 powertrain device. Its CV ends
        # must not add a rigid distance constraint across moving suspension.
        shaft_group='ev_shaft_'+wheel
        tip=shaft_group+'_tip'
        part['nodes'].append([tip,*hub,{'nodeWeight':.3,'collision':False,'selfCollision':False,'group':[shaft_group]}])
        for a in (hub1,hub2,axle+'na'+side,axle+'h1'+side):
            if a not in positions: raise PatchError('Missing wheel upright node '+a)
            part['beams'].append([tip,a,{'beamSpring':200000,'beamDamp':30,'beamDeform':100000,'beamStrength':'FLT_MAX'}])
        curve=options['curve']
        part['powertrain'].extend([['electricMotor',motor,'dummy',0],['shaft','evHalfshaft'+wheel,motor,1]])
        part['vehicleController']['motorNames'].append(motor)
        part[motor]={'uiName':wheel+' motor', 'torque':[['rpm','torque']]+curve,
                     'energyStorage':'mainBattery', 'inertia':options['inertia'], 'friction':0,'dynamicFriction':0,
                     'electricalEfficiency':.95,'torqueReactionNodes:':[ids[1],ids[2],ids[3]],
                     'maxRegenTorque':max(t for _,t in curve)*options['regen']/100,
                     'regenFadeRPM':min(200,curve[-1][0]/4)}
        part['evHalfshaft'+wheel]={'connectedWheel':wheel,'gearRatio':1,'friction':0,'dynamicFriction':0}
        back=[out[0],out[1]-.20*sign,out[2]]
        meshes.append(('ev_housing_'+wheel,*cylinder(back,out,.12)))
        meshes.append(('ev_shaft_'+wheel,*cylinder(out,hub,.018)))
        part['flexbodies'].extend([['ev_housing_'+wheel,[group],[]],['ev_shaft_'+wheel,[group,shaft_group],[]]])
        report['shafts'][wheel]={'motor_output_m':out,'wheel_center_m':hub,'length_m':math.dist(out,hub),'ratio':1}
    chassis=[(n,p) for n,p in positions.items() if n.startswith('cc')]
    if len(chassis)<4: raise PatchError('Not enough chassis nodes to mount battery.')
    # Eight battery mass nodes below the cabin, bounded by the axle centers.
    front=report['shafts']['FL']['wheel_center_m'][0]; rear=report['shafts']['RL']['wheel_center_m'][0]
    midpoint=(front+rear)/2; half=min(abs(front-rear)*.30,1.0)
    corners=list(itertools.product((midpoint-half,midpoint+half),(-.45,.45),(.20,.34)))
    battery_ids=['ev_battery_'+str(i) for i in range(8)]
    for node,pos in zip(battery_ids,corners):
        part['nodes'].append([node,*pos,{'nodeWeight':options['battery_mass']/8,'collision':False,'selfCollision':False,'group':['ev_battery']}])
        for anchor,_ in sorted(chassis,key=lambda pair:math.dist(pair[1],pos))[:4]:
            part['beams'].append([node,anchor,{'beamSpring':2000000,'beamDamp':200,'beamDeform':200000,'beamStrength':'FLT_MAX'}])
    for a,b in itertools.combinations(battery_ids,2):
        part['beams'].append([a,b,{'beamSpring':2000000,'beamDamp':200,'beamDeform':200000,'beamStrength':'FLT_MAX'}])
    faces=[(0,1,3),(0,3,2),(4,6,7),(4,7,5),(0,4,5),(0,5,1),(2,3,7),(2,7,6),(0,2,6),(0,6,4),(1,5,7),(1,7,3)]
    meshes.append(('ev_battery',corners,faces));part['flexbodies'].append(['ev_battery',['ev_battery'],[]])
    result[prefix+'engine.jbeam']=(json.dumps({'engine':part},indent=2)+'\n').encode()
    result[prefix+'companion_ev.dae']=mesh_dae(meshes)
    result[prefix+'companion_ev_report.json']=(json.dumps(report,indent=2)+'\n').encode()
    for name,raw in list(result.items()):
        if name.startswith(prefix) and Path(name).name.startswith('info') and name.endswith('.json'):
            data=json.loads(raw.decode('utf-8-sig'))
            data.update({'Propulsion':'Electric','Fuel Type':'Battery','Drivetrain':'AWD'})
            data.pop('Induction Type',None)
            # Exported combustion-car mass and peak-RPM labels are no longer valid.
            for stale in ('Weight', 'TorquePeakRPM', 'PowerPeakRPM'):
                data.pop(stale,None)
            data['Torque']=round(4*max(t for _,t in options['curve']))
            data['Power']=round(4*max(r*t*math.pi/30000 for r,t in options['curve'])*1.341022)
            if 'Name' in data: data['Name']+=' Electric'
            if 'Configuration' in data: data['Configuration']='Four motors · direct drive'
            result[name]=(json.dumps(data,indent=2)+'\n').encode()
        elif name.startswith(prefix) and name.endswith('.pc'):
            data=json.loads(raw.decode('utf-8-sig')) if raw.strip() else {'format':2,'parts':{'main':'main'}}
            for key in ('radiator','fueltank','drivetrain','diff_F','diff_R'):
                data.get('parts',{}).pop(key,None)
            data.get('parts',{})['engine']='engine'
            result[name]=(json.dumps(data,indent=2)+'\n').encode()
    text=result[prefix+'main.jbeam'].decode();d=JBeam(text)
    value=d.prop(d.prop(d.prop(0,'main'),'information'),'name')
    result[prefix+'main.jbeam']=edits(text,[(*d.span(value),json.dumps(json.loads(d.tokens[value].value)+' Electric'))]).encode()
    return result
