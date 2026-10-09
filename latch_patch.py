"""Remove unsafe force assistance between coincident AutoCraft latch nodes."""
import json
import math
from electric_patch import node_positions, rows, values
from patcher import JBeam, PatchError, edits


def apply(entries,prefix):
    positions={}
    for name,raw in entries.items():
        if name.startswith(prefix) and name.endswith('.jbeam'):
            positions.update(node_positions(raw.decode('utf-8-sig')))
    result=dict(entries);report=[]
    for name,raw in entries.items():
        if not name.startswith(prefix) or not name.endswith('.jbeam'):continue
        text=raw.decode('utf-8-sig');doc=JBeam(text);changes=[]
        for _,part in doc.props(0):
            props=dict(doc.props(part))
            controllers=props.get('controller')
            if controllers is None:continue
            for row in rows(doc,controllers):
                if values(doc,row)[0]!='advancedCouplerControl':continue
                i=row+1;config_name=None
                while i<doc.ends[row]:
                    if doc.tokens[i].value=='{':
                        for key,v in doc.props(i):
                            if key=='name':config_name=json.loads(doc.tokens[v].value)
                    i=doc.ends.get(i,i)+1
                if config_name not in props:continue
                config=props[config_name];fields=dict(doc.props(config))
                if 'couplerNodes' not in fields:continue
                pairs=list(rows(doc,fields['couplerNodes']))
                if len(pairs)<2:continue
                header=values(doc,pairs[0]);pairs=[values(doc,p) for p in pairs[1:]]
                if not all(k in header for k in ('cid1','cid2')):continue
                unsafe=False;resolved=[]
                for p in pairs:
                    a,b=p[header.index('cid1')],p[header.index('cid2')]
                    if a not in positions or b not in positions:
                        raise PatchError('Latch patch: missing latch/catch node in '+config_name)
                    resolved.append(a)
                    unsafe |= math.dist(positions[a],positions[b])<.001
                updates={'soundNode:':[resolved[0]]}
                if unsafe:
                    # A zero duration prevents applyForceTime from being called,
                    # even with a zero magnitude and undefined direction.
                    updates.update(openForceMagnitude=0,closeForceMagnitude=0,
                                   openForceDuration=0,closeForceDuration=0)
                additions={}
                for key,value in updates.items():
                    if key in fields:changes.append((*doc.span(fields[key]),json.dumps(value)))
                    else:additions[key]=value
                if additions:
                    pos=doc.tokens[config].end
                    changes.append((pos,pos,json.dumps(additions)[1:-1]+','))
                report.append({'controller':config_name,'force_assist_disabled':unsafe,'sound_node':resolved[0]})
        if changes:result[name]=edits(text,changes).encode()
    result[prefix+'companion_latches.json']=(json.dumps(report,indent=2)+'\n').encode()
    return result
