"""Mass override for AutoCraft explicit nodes and generated pressure wheels."""
import json
import math


def apply_weight(entries, prefix, settings):
    from patcher import JBeam, PatchError, edits, number
    from electric_patch import rows, values, node_positions
    target=number(settings,'ev_base_mass',1,10000)
    left=number(settings,'ev_passenger_left',0,500)
    right=number(settings,'ev_passenger_right',0,500)
    locations=[]; wheel_locations=[]; masses={}; motor_mass=0; battery_mass=0; wheel_mass=0
    docs={}
    def numeric(doc,v):
        try: n=float(doc.tokens[v].value)
        except ValueError: raise PatchError('Weight patch requires numeric node masses.')
        if not math.isfinite(n) or n<=0: raise PatchError('Weight patch found a nonpositive node mass.')
        return n
    for name,raw in entries.items():
        if not name.startswith(prefix) or not name.endswith('.jbeam'):continue
        text=raw.decode('utf-8-sig');d=JBeam(text);docs[name]=(text,d)
        for _,part in d.props(0):
            for section,array in d.props(part):
                if section not in ('nodes','pressureWheels'):continue
                state={}; i=array+1
                while i<d.ends[array]:
                    token=d.tokens[i].value
                    if token=='{':
                        state.update(dict(d.props(i)))
                    elif token=='[':
                        vals=values(d,i)
                        if vals and vals[0] not in ('id','name'):
                            local=dict(state); inline=None
                            j=i+1
                            while j<d.ends[i]:
                                if d.tokens[j].value=='{':
                                    inline=j;local.update(dict(d.props(j)))
                                j=d.ends.get(j,j)+1
                            if section=='nodes':
                                if 'nodeWeight' not in local:raise PatchError('Missing explicit node mass for '+str(vals[0]))
                                weight=numeric(d,local['nodeWeight']);node=vals[0]
                                if node in masses and abs(masses[node]-weight)>1e-6:
                                    raise PatchError('Conflicting node masses: '+node)
                                masses[node]=weight
                                locations.append((name,i,inline,node,weight))
                            else:
                                if 'numRays' not in local or 'hubNodeWeight' not in local or 'nodeWeight' not in local:
                                    raise PatchError('Unsupported pressure wheel mass layout.')
                                if 'enableHubcaps' in local and d.tokens[local['enableHubcaps']].value=='true':
                                    raise PatchError('Weight patch does not support generated hubcaps yet.')
                                rays=numeric(d,local['numRays'])
                                for key in ('nodeWeight','hubNodeWeight'):
                                    weight=numeric(d,local[key]);wheel_mass+=2*rays*weight
                                    wheel_locations.append((name,local[key],weight))
                    i=d.ends.get(i,i)+1
    motor_mass=sum(w for n,w in masses.items() if n.startswith('ev_') and n[3:5] in ('FL','FR','RL','RR'))
    battery_mass=sum(w for n,w in masses.items() if n.startswith('ev_battery_'))
    scalable=sum(masses.values())-motor_mass-battery_mass+wheel_mass
    if target<=motor_mass or scalable<=0:raise PatchError('Base vehicle mass must exceed the total motor mass.')
    factor=(target-motor_mass)/scalable
    replacements={name:[] for name in docs}
    for name,row,inline,node,weight in locations:
        if node.startswith('ev_battery_') or (node.startswith('ev_') and node[3:5] in ('FL','FR','RL','RR')):continue
        d=docs[name][1];new=weight*factor
        local=dict(d.props(inline)) if inline is not None else {}
        if 'nodeWeight' in local:
            replacements[name].append((*d.span(local['nodeWeight']),f'{new:.12g}'))
        elif inline is not None:
            start=d.tokens[inline].end
            replacements[name].append((start,start,f'"nodeWeight":{new:.12g},'))
        else:
            end=d.tokens[d.ends[row]].start
            comma='' if d.tokens[d.ends[row]-1].value==',' else ','
            replacements[name].append((end,end,comma+'{"nodeWeight":'+f'{new:.12g}'+'}'))
    seen=set()
    for name,v,weight in wheel_locations:
        if (name,v) in seen:continue
        seen.add((name,v));replacements[name].append((*docs[name][1].span(v),f'{weight*factor:.12g}'))
    result=dict(entries)
    for name,reps in replacements.items():result[name]=edits(docs[name][0],reps).encode()
    # Reducing mass without reducing stiffness/damping raises the solver's
    # natural frequencies and damping rates. Keep k/m and c/m from increasing.
    if factor < 1:
        import re
        for name in docs:
            text=result[name].decode();doc=JBeam(text);changes=[]
            for i,token in enumerate(doc.tokens[:-2]):
                if not token.value.startswith('"') or doc.tokens[i+1].value!=':':continue
                key=json.loads(token.value)
                if not re.fullmatch(r'(?:beam(?:Limit)?(?:Spring|Damp)|(?:hub|wheel)\w*Beam(?:Spring|Damp)(?:Expansion)?)',key):continue
                v=i+2;value=doc.tokens[v].value
                try:
                    n=float(value)
                    if n>0:changes.append((*doc.span(v),f'{n*factor:.12g}'))
                except ValueError:
                    if value.startswith('"$='):
                        expr=json.loads(value)
                        changes.append((*doc.span(v),json.dumps('$=('+expr[2:]+f')*{factor:.12g}')))
                    elif value.startswith('"$'):
                        expr=json.loads(value)
                        changes.append((*doc.span(v),json.dumps('$='+expr+f'*{factor:.12g}')))
            result[name]=edits(text,changes).encode()
    engine=json.loads(result[prefix+'engine.jbeam'])
    part=engine['engine'];positions={}
    for name,raw in result.items():
        if name.endswith('.jbeam'):positions.update(node_positions(raw.decode()))
    chassis=[(n,p) for n,p in positions.items() if n.startswith('cc')]
    main=JBeam(result[prefix+'main.jbeam'].decode())
    mainpart=main.prop(0,'main');seat=None
    for key,v in main.props(mainpart):
        if key=='camerasInternal':
            for r in rows(main,v):
                val=values(main,r)
                if val and str(val[0]).lower()=='driver':seat=val[1:4]
    if seat is None:
        # Fallback for exports without an interior camera: midway between axles.
        seat=[sum(positions[n][0] for n in ('fw1l','rw1l'))/2,.35,1.0]
    for side,weight,sign in [('left',left,1),('right',right,-1)]:
        if not weight:continue
        center=[seat[0],sign*max(abs(seat[1]),.25),seat[2]-.4]
        nodes=[]
        for i,delta in enumerate(((0,0,.1),(-.1,-.1,-.1),(.1,-.1,-.1),(0,.1,-.1))):
            node=f'ev_passenger_{side}_{i}';pos=[a+b for a,b in zip(center,delta)];nodes.append(node)
            part['nodes'].append([node,*pos,{'nodeWeight':weight/4,'collision':False,'selfCollision':False,'group':['ev_passenger_'+side]}])
            for anchor,_ in sorted(chassis,key=lambda pair:math.dist(pair[1],pos))[:4]:
                part['beams'].append([node,anchor,{'beamSpring':200000,'beamDamp':100,'beamDeform':100000,'beamStrength':'FLT_MAX'}])
    result[prefix+'engine.jbeam']=(json.dumps(engine,indent=2)+'\n').encode()
    total=target+battery_mass+left+right
    estimate={'base_kg':target,'motors_included_kg':motor_mass,'battery_kg':battery_mass,
              'left_passenger_kg':left,'right_passenger_kg':right,'total_kg':total,
              'nonmotor_mass_scale':factor,'estimated_generated_wheel_mass_kg':wheel_mass*factor,
              'stiffness_damping_scale':min(factor,1),
              'note':'Estimate for default exported parts, including pressure-wheel nodes; confirm in BeamNG.'}
    for name,raw in list(result.items()):
        if name.startswith(prefix) and name.rsplit('/',1)[-1].startswith('info') and name.endswith('.json'):
            data=json.loads(raw);data['Weight']=round(total,3);result[name]=(json.dumps(data,indent=2)+'\n').encode()
    report=json.loads(result[prefix+'companion_ev_report.json']);report['weight']=estimate
    result[prefix+'companion_ev_report.json']=(json.dumps(report,indent=2)+'\n').encode()
    return result
