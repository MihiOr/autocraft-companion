"""Independent Scintilla GTx EV conversion and cached, sequential exports."""
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import zipfile
from patcher import JBeam, edits
from electric_patch import read_curve
from storage import ROOT

BASE='civetta_ev_base'
SOURCE=ROOT/'civetta/source/Scintilla_GTx.zip'
CACHE=ROOT/'civetta/cache/Scintilla_GTx_EV.zip'
GAME=Path(r'E:\Games\Steam\steamapps\common\BeamNG.drive\content\vehicles\scintilla.zip')
TEXT={'.jbeam','.json','.pc','.dae','.html','.js','.css','.svg','.txt','.lua','.ini'}
VERSION=3

def compiled_mesh_cache(name):
    """Compiled meshes retain source names; only the renamed DAE is portable."""
    return str(name).lower().endswith(('.cdae', '.cached.dts'))


def data_value(doc,i):
    token=doc.tokens[i].value
    if token=='{':return {k:data_value(doc,v) for k,v in doc.props(i)}
    if token=='[':
        out=[];j=i+1
        while j<doc.ends[i]:
            if doc.tokens[j].value!=',':out.append(data_value(doc,j))
            j=doc.ends.get(j,j)+1
        return out
    try:return json.loads(token)
    except ValueError:return token

def source_zip(game=GAME):
    if SOURCE.exists():return SOURCE
    if not Path(game).is_file():raise ValueError('Cannot find the installed Scintilla ZIP: '+str(game))
    SOURCE.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(game,SOURCE)
    with zipfile.ZipFile(SOURCE) as z:
        if 'vehicles/scintilla/gtx.pc' not in z.namelist():raise ValueError('Scintilla GTx configuration missing')
    return SOURCE

def part(z,file,name):
    doc=JBeam(z.read('vehicles/scintilla/'+file).decode('utf-8-sig'))
    return data_value(doc,doc.prop(0,name))

def positions(part):
    return {r[0]:r[1:4] for r in part.get('nodes',[]) if isinstance(r,list) and len(r)>=4 and all(isinstance(x,(int,float)) for x in r[1:4])}

def imu_geometry(z):
    chassis=positions(part(z,'scintilla_chassis.jbeam','scintilla_chassis'))
    chassis.update(positions(part(z,'scintilla_subframe_R.jbeam','scintilla_subframe_R')))
    chassis={n:p for n,p in chassis.items() if not n.startswith(('arf','arr'))}
    hubs={}
    for axle in ('F','R'):
        nodes=positions(part(z,'scintilla_hub_'+axle+'.jbeam','scintilla_hub_'+axle+'_5'))
        for side in ('L','R'):
            a,b=nodes[axle.lower()+'w1'+side.lower()],nodes[axle.lower()+'w1'+side.lower()*2]
            hubs[axle+side]=[(x+y)/2 for x,y in zip(a,b)]
    def sub(a,b):return [x-y for x,y in zip(a,b)]
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    def unit(v):
        l=math.sqrt(dot(v,v));return [x/l for x in v]
    forward=[0,-1,0];left=[1,0,0];up=[0,0,1]
    picked={};used=set()
    for name,hub in hubs.items():
        node=min((n for n in chassis if n not in used),key=lambda n:math.dist(chassis[n],hub));picked[name]=node;used.add(node)
    center=[sum(chassis[n][i] for n in picked.values())/4 for i in range(3)]
    mounts={}
    for name,node in picked.items():
        pos=chassis[node];near=sorted((n for n in chassis if n!=node),key=lambda n:math.dist(chassis[n],pos))
        pair=next((a,b) for a in near for b in near if a!=b and math.sqrt(dot(cross(sub(chassis[a],pos),sub(chassis[b],pos)),cross(sub(chassis[a],pos),sub(chassis[b],pos))))>.025)
        edge=unit(sub(chassis[pair[0]],pos));normal=unit(cross(edge,sub(chassis[pair[1]],pos)));side=unit(cross(normal,edge))
        offset=sub(pos,center)
        mounts[name]={'nodes':[node,*pair],'forward':[dot(forward,e) for e in (edge,normal,side)],'left':[dot(left,e) for e in (edge,normal,side)],'up':[dot(up,e) for e in (edge,normal,side)],'offset':dict(forward=dot(offset,forward),left=dot(offset,left),up=dot(offset,up))}
    return {'mounts':mounts,'bodyCornerNodes':picked,'wheelbase':abs(hubs['FL'][1]-hubs['RL'][1]),'trackFront':abs(hubs['FL'][0]-hubs['FR'][0]),'trackRear':abs(hubs['RL'][0]-hubs['RR'][0]),'note':'Four virtual 6-axis chassis IMUs; no physical mass added.'}

def peak_torque(settings):
    value=float(str(settings.get('civetta_peak_torque',1500)).replace(',','.'))
    if not math.isfinite(value) or not 1<=value<=5000:raise ValueError('Peak motor torque must be 1-5000 Nm')
    return value


def signature(source,settings):
    capacity=float(str(settings.get('civetta_capacity',100)).replace(',','.'))
    if not math.isfinite(capacity) or not 1<=capacity<=1000:raise ValueError('Battery capacity must be 1-1000 kWh')
    with Path(source).open('rb') as stream:source_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'version':VERSION,'converter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_sha256':source_hash,'csv_sha256':hashlib.sha256(Path(settings['civetta_csv']).read_bytes()).hexdigest(),'capacity':capacity,'peak_torque_nm':peak_torque(settings),'inertia':.1}

def build_physical(settings):
    source=source_zip();key=signature(source,settings)
    manifest=CACHE.with_suffix('.json')
    if CACHE.exists() and manifest.exists() and json.loads(manifest.read_text())==key:return CACHE,True
    curve=read_curve(settings['civetta_csv'])
    peak=max(t for _,t in curve)
    if peak<=0:raise ValueError('Motor CSV must have a positive peak torque')
    scale=key['peak_torque_nm']/peak
    curve=[[rpm,torque*scale] for rpm,torque in curve]
    with zipfile.ZipFile(source) as z:
        imu=imu_geometry(z)
        engine=part(z,'scintilla_engine.jbeam','scintilla_engine_5.0_v10')
        # Preserve load-bearing nodes and mounts; remove combustion devices,
        # combustion meshes and engine-only children. Structural mass is retained.

        for field in ('mainEngine','flexbodies','props','soundConfig','soundConfigExhaust'):engine.pop(field,None)
        engine['slots2']=[['name','allowTypes','denyTypes','default','description'],['scintilla_enginemounts',['scintilla_enginemounts'],[],'scintilla_enginemounts','Motor support mounts'],['scintilla_transaxle',['scintilla_transaxle'],[],'scintilla_transaxle_7DCT','Rear structural support']]
        engine['information']={'authors':'MihiOr / BeamNG','name':'Four direct-drive electric motors'}
        engine['powertrain']=[['type','name','inputName','inputIndex']]
        engine['vehicleController']={'shiftLogicName':'electricMotor','motorNames':[],'defaultAutomaticMode':'D','arcadeAutoBrakeAmount':0,'onePedalRegenCoef':0,'onePedalFrictionBrakeCoef':0,'defaultRegenStrength':0}
        engine['energyStorage']=[['type','name'],['electricBattery','mainBattery']]
        engine['mainBattery']={'energyType':'electricEnergy','batteryCapacity':key['capacity'],'startingCapacity':key['capacity']}
        engine['controller']=[['fileName'],['companion_custom_ecu',{'imu':imu}]]
        for name in ('FL','FR','RL','RR'):
            motor='evMotor'+name;shaft='evHalfshaft'+name;reactor='evReaction'+name
            # Native shaft.validate binds the wheel's engine-axis couple only
            # through a torsionReactor ancestor. Motor reaction nodes alone
            # account for rotor inertia, not wheel propulsion reaction torque.
            engine['powertrain'] += [['electricMotor',motor,'dummy',0],['torsionReactor',reactor,motor,1],['shaft',shaft,reactor,1]]
            engine['vehicleController']['motorNames'].append(motor)
            engine[motor]={'torque':[['rpm','torque']]+curve,'regenTorqueCurve':[['rpm','torque']]+[[rpm,t*min(1,rpm/30)] for rpm,t in curve],'maxRPM':curve[-1][0],'inertia':.1,'friction':0,'dynamicFriction':0,'electricalEfficiency':.95,'energyStorage':'mainBattery','torqueReactionNodes:':[(name[0].lower()+'x'+str(i)+name[1].lower()) for i in ((1,2,4) if name[0]=='F' else (3,4,6))],'electricsThrottleName':'companionCustom'+name,'electricsThrottleFactorName':'companionCustomFactor','electricsRegenThrottleName':'companionCustomRegen'+name,'regenFadeRPM':30,'minimumWantedRegenTorque':0,'isAffectedByIgnition':False}
            engine[reactor]={'gearRatio':1,'torqueReactionNodes:':engine[motor]['torqueReactionNodes:'][:]}
            engine[shaft]={'connectedWheel':name,'gearRatio':1,'friction':0,'dynamicFriction':0,'breakTriggerBeam':'axle_'+name}
        pc=json.loads(z.read('vehicles/scintilla/gtx.pc'));pc['parts']['main']='scintilla'
        for name in list(pc['parts']):
            if any(s in name for s in ('DSE','exhaust','intake','oilpan','ecu','n2o','fueltank')):pc['parts'][name]=''
        # All source JBeams remain local to the cloned model. Shared wheels/tires
        # continue to resolve from BeamNG common; their settings are unchanged.
        CACHE.parent.mkdir(parents=True,exist_ok=True);staging=CACHE.with_suffix('.zip.tmp')
        with zipfile.ZipFile(staging,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as out:
            for info in z.infolist():
                name=info.filename
                if info.is_dir() or compiled_mesh_cache(name) or not name.startswith('vehicles/scintilla/'):continue
                relative=name[len('vehicles/scintilla/'):]
                if relative.endswith('.pc') and relative!='gtx.pc':continue
                if relative.startswith('info_') and relative!='info_gtx.json':continue
                raw=z.read(name)
                if relative.endswith('.jbeam'):
                    doc=JBeam(raw.decode('utf-8-sig'));changes=[]
                    for pn,pi in doc.props(0):
                        for field,value in doc.props(pi):
                            if field=='powertrain':changes.append((*doc.span(value),json.dumps([['type','name','inputName','inputIndex']])))
                            elif field in ('slots','slots2'):
                                table=data_value(doc,value)
                                for row in table[1:]:
                                    if isinstance(row,list) and row and any(k in str(row[0]) for k in ('DSE','fueltank')):
                                        row[3 if field=='slots2' else 1]=''
                                changes.append((*doc.span(value),json.dumps(table)))
                            elif field=='pressureWheels':
                                table=data_value(doc,value)
                                for row in table:
                                    if isinstance(row,dict):
                                        if 'brakeTorque' in row:row['brakeTorque']=0
                                        if 'enableABS' in row:row['enableABS']=False
                                changes.append((*doc.span(value),json.dumps(table)))
                            elif field=='controller':
                                table=data_value(doc,value)
                                table=[row for row in table if not (isinstance(row,list) and row and any(s in str(row[0]).lower() for s in ('esc','traction','abs','dse','shiftlogic','engine','electronicdifflock','electronicsplitshaftlock')))]
                                changes.append((*doc.span(value),json.dumps(table)))
                        if pn in ('scintilla_differential_F','scintilla_differential_R'):
                            ii=doc.prop(pi,'information');detail=data_value(doc,ii);detail['name']='Passive motor reaction support'
                            changes.append((*doc.span(ii),json.dumps(detail)))
                        if pn=='scintilla_engine_5.0_v10':changes.append((*doc.span(pi),json.dumps(engine)))
                        elif pn=='scintilla_transaxle_7DCT':
                            support=data_value(doc,pi)
                            for k in ('powertrain','gearbox','vehicleController','controller','flexbodies','props'):support.pop(k,None)
                            support['information']={'authors':'BeamNG / MihiOr','name':'Rear structural motor support'}
                            changes=[c for c in changes if not (doc.span(pi)[0]<=c[0]<doc.span(pi)[1])]
                            changes.append((*doc.span(pi),json.dumps(support)))
                    # Drop overlapping field replacements for the replaced engine.
                    if relative=='scintilla_engine.jbeam':
                        span=doc.span(doc.prop(0,'scintilla_engine_5.0_v10'))
                        changes=[c for c in changes if c[:2]==span or not (span[0]<=c[0]<span[1])]
                    raw=edits(doc.text,changes).encode()
                elif relative=='gtx.pc':raw=json.dumps(pc).encode()
                elif relative=='info.json':
                    data=json.loads(raw);data.update(Name='Civetta Scintilla EV',Brand='Civetta',default_pc='gtx');raw=json.dumps(data).encode()
                elif relative=='info_gtx.json':
                    data=json.loads(raw)
                    for field in list(data):
                        if field in ('Power','PowerPeakRPM','Torque','TorquePeakRPM','Top Speed','Weight','Weight/Power','Braking G','Drag Times','Induction Type','vehicleSelectorSubGroup') or re.match(r'^[0-9]+-',field):data.pop(field)
                    data.update(Configuration='GTx Electric - direct drive',Description='Four independent direct-drive motors, virtual battery and four chassis IMUs.',Propulsion='Electric',**{'Fuel Type':'Battery','Drivetrain':'AWD','Transmission':'Direct drive','Config Type':'Custom'})
                    raw=json.dumps(data).encode()
                if Path(relative).suffix.lower() in TEXT:
                    raw=raw.decode('utf-8-sig').replace('scintilla_engine_5.0_v10','scintilla_engine_ev_direct').replace('scintilla_transaxle_7DCT','scintilla_ev_rear_support').replace('scintilla',BASE).encode()
                out.writestr('vehicles/'+BASE+'/'+relative.replace('scintilla',BASE),raw)
            out.writestr('vehicles/'+BASE+'/companion_civetta.json',json.dumps({'source':'scintilla/gtx.pc','battery_mass_kg':0,'imu':imu,'cache':key}))
        with zipfile.ZipFile(staging) as check:
            if check.testzip():raise ValueError('Civetta conversion ZIP integrity failed')
        staging.replace(CACHE);manifest.write_text(json.dumps(key,indent=2))
    return CACHE,False

def validate(settings):
    if not str(settings.get('mods','')).strip():raise ValueError('Choose a BeamNG mods folder')
    if not re.fullmatch(r'v[0-9]+',str(settings.get('civetta_version','v00')).strip()):raise ValueError('Use a version such as v00')
    curve=read_curve(settings.get('civetta_csv',''))
    if max(t for _,t in curve)<=0:raise ValueError('Motor CSV must have a positive peak torque')
    peak_torque(settings)
    capacity=float(str(settings.get('civetta_capacity',100)).replace(',','.'))
    if not math.isfinite(capacity) or not 1<=capacity<=1000:raise ValueError('Battery capacity must be 1-1000 kWh')

def export(settings):
    validate(settings)
    from custom_control import build_controller,check_code
    source=(ROOT/'civetta/custom_motor_control.lua').read_text(encoding='utf-8-sig')
    check_code(source)
    cache,reused=build_physical(settings)
    mods=Path(settings['mods']);mods.mkdir(parents=True,exist_ok=True)
    version=str(settings.get('civetta_version','v00')).strip()
    if not re.fullmatch(r'v[0-9]+',version):raise ValueError('Civetta version must be v followed by digits, for example v00')
    label='Civetta_'+version
    numbers=[]
    for p in mods.glob(label+'_*.zip'):
        m=re.fullmatch(re.escape(label)+r'_(\d+)\.zip',p.name)
        if m:numbers.append(int(m[1]))
    number=max(numbers,default=0)+1;model=label+'_'+f'{number:02d}'
    target=mods/(model+'.zip');staging=target.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(cache) as z,zipfile.ZipFile(staging,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as out:
            for info in z.infolist():
                name=info.filename
                # Also protect exports made from an older physical cache.
                if compiled_mesh_cache(name):continue
                raw=z.read(name)
                if Path(name).suffix.lower() in TEXT:raw=raw.decode('utf-8-sig').replace(BASE,model).encode()
                new=name.replace(BASE,model)
                if new.endswith('/info.json'):
                    data=json.loads(raw);data['Name']='Civetta Scintilla EV '+version+'_'+f'{number:02d}';raw=json.dumps(data).encode()
                out.writestr(new,raw)
            prefix='vehicles/'+model+'/'
            out.writestr(prefix+'custom_motor_control.lua',source)
            out.writestr(prefix+'lua/controller/companion_custom_ecu.lua',build_controller(source))
        with zipfile.ZipFile(staging) as z:
            if z.testzip():raise ValueError('Civetta export ZIP integrity failed')
        staging.replace(target)
    finally:staging.unlink(missing_ok=True)
    return target,reused
