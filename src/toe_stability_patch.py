"""Reduce elastic wheel/toe wobble without adding suspension constraints."""
import json
import math
import re

from patcher import JBeam, PatchError, edits, number
from suspension_values import beam_rows
from wheel_attachment_patch import properties
from electric_patch import values


def category(nodes, axle, section):
    a,b=map(str,nodes[:2]);letter=axle.lower()
    rack=lambda n: bool(re.fullmatch(r'st[12][lr]',n))
    toe_mount=lambda n: bool(re.fullmatch(r'tlm[lr]',n))
    mount=lambda n: bool(re.fullmatch(letter+r'x[1-4][lr]',n))
    upright=lambda n: bool(re.fullmatch(letter+r'(na|nc|h1|h2)[lr]',n))
    hub=lambda n: bool(re.fullmatch(letter+r'w[12][lr]',n))
    if section=='hydros':
        return 'rack_actuator' if rack(a) and rack(b) else None
    if rack(a) or rack(b):
        return 'front_toe_link' if upright(a) or upright(b) else 'rack_support'
    if toe_mount(a) or toe_mount(b):
        return 'rear_toe_link' if upright(a) or upright(b) else 'rear_toe_support'
    if (upright(a) or hub(a)) and (upright(b) or hub(b)):
        return 'hub_upright'
    if (mount(a) and upright(b)) or (mount(b) and upright(a)):
        return 'wishbone'
    return None


def node_masses(doc,part):
    table=doc.prop(part,'nodes');masses={};state={};i=table+1
    while i<doc.ends[table]:
        if doc.tokens[i].value=='{':state.update(properties(doc,i))
        elif doc.tokens[i].value=='[':
            row=values(doc,i)
            if row and row[0]!='id':
                own=dict(state)
                for j in range(i+1,doc.ends[i]):
                    if doc.tokens[j].value=='{':own.update(properties(doc,j))
                if 'nodeWeight' in own:
                    try:masses[str(row[0])]=float(doc.tokens[own['nodeWeight']].value)
                    except ValueError:raise PatchError('Toe stability requires numeric node weights.') from None
        i=doc.ends.get(i,i)+1
    return masses


def apply(entries,prefix,settings):
    result=dict(entries)
    if not settings.get('toe_stability_enabled',False):return result
    multiplier=number({'toe_stability_multiplier':settings.get('toe_stability_multiplier',1)},
                      'toe_stability_multiplier',1,1.5)
    damping=number({'toe_stability_damping_ratio':settings.get('toe_stability_damping_ratio',.03)},
                   'toe_stability_damping_ratio',0,.5)
    report_name=prefix+'companion_toe_stability.json'
    previous=json.loads(entries[report_name]) if report_name in entries else {}
    originals={r['key']:r for r in previous.get('beams',[])}
    report={'multiplier':multiplier,'damping_ratio':damping,'beams':[],
            'note':'Existing positive-stiffness structural links only. No added beams or geometry, spring, shock, mass, strength or collision edits.'}
    for axle in ('F','R'):
        name=prefix+'suspension_'+axle+'.jbeam'
        if name not in entries:raise PatchError('Toe stability: missing suspension '+axle)
        doc=JBeam(entries[name].decode('utf-8-sig'));part=doc.prop(0,'suspension_'+axle)
        masses=node_masses(doc,part);changes=[];counts={};seen=set()
        for section in ('beams','hydros'):
            sections=dict(doc.props(part))
            if section not in sections:continue
            for row,nodes,props,inline in beam_rows(doc,sections[section]):
                if len(nodes)<2:continue
                kind=category(nodes,axle,section)
                if not kind:continue
                own=properties(doc,inline) if inline is not None else {}
                local=dict(props);local.update(own)
                beam_type=doc.tokens[local['beamType']].value if 'beamType' in local else '"|NORMAL"'
                if beam_type not in ('"|NORMAL"','|NORMAL'):continue
                key=axle+'/'+section+'/'+':'.join(sorted(map(str,nodes[:2])))
                if key in seen:raise PatchError('Toe stability: duplicate structural link '+key)
                seen.add(key)
                try:
                    spring=float(doc.tokens[local['beamSpring']].value)
                    damp=float(doc.tokens[local['beamDamp']].value)
                except (KeyError,ValueError):raise PatchError('Toe stability requires numeric structural spring/damping.') from None
                if spring<=0:continue
                before=originals.get(key,{})
                spring=before.get('spring_before',spring);damp=before.get('damp_before',damp)
                if not math.isfinite(spring) or not math.isfinite(damp) or spring<=0 or damp<0:
                    raise PatchError('Toe stability: invalid structural spring/damping.')
                ma,mb=(masses.get(str(n)) for n in nodes[:2])
                if not ma or not mb or ma<=0 or mb<=0:
                    raise PatchError('Toe stability: missing positive node masses for '+key)
                stiffness=spring*multiplier
                # Local two-node estimate, not a claim about the complete assembly's modes.
                reduced_mass=ma*mb/(ma+mb)
                coefficient=max(damp*math.sqrt(multiplier),2*damping*math.sqrt(stiffness*reduced_mass))
                added={}
                for prop,value in (('beamSpring',stiffness),('beamDamp',coefficient)):
                    if prop in own:
                        current=float(doc.tokens[own[prop]].value)
                        if not math.isclose(current,value,rel_tol=1e-10,abs_tol=1e-10):
                            changes.append((*doc.span(own[prop]),format(value,'.12g')))
                    else:added[prop]=value
                if added:
                    if inline is not None:
                        pos=doc.tokens[inline].end
                        changes.append((pos,pos,json.dumps(added)[1:-1]+(',' if own else '')))
                    else:
                        pos=doc.tokens[doc.ends[row]].start
                        sep='' if doc.tokens[doc.ends[row]-1].value==',' else ','
                        changes.append((pos,pos,sep+json.dumps(added)))
                counts[kind]=counts.get(kind,0)+1
                report['beams'].append(dict(key=key,kind=kind,nodes=nodes[:2],
                    spring_before=spring,damp_before=damp,spring_after=stiffness,damp_after=coefficient))
        if not counts.get('hub_upright') or not counts.get('wishbone') or not counts.get('front_toe_link' if axle=='F' else 'rear_toe_link'):
            raise PatchError('Toe stability supports the AutoCraft double-wishbone steering/toe layout only.')
        result[name]=edits(doc.text,changes).encode('utf-8')
    result[report_name]=(json.dumps(report,indent=2)+'\n').encode()
    return result
