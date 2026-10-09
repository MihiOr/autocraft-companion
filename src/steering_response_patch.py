"""Change only steering hydro actuator rates, not geometry or stiffness."""
import json
from patcher import JBeam, edits, number, PatchError
from suspension_values import beam_rows


def apply(entries, prefix, settings):
    options={'steering_hydro_rate':'20'}
    options.update(settings)
    rate=number(options,'steering_hydro_rate',1,200)
    result=dict(entries);count=0
    for name,raw in entries.items():
        if not name.startswith(prefix) or not name.endswith('.jbeam'): continue
        doc=JBeam(raw.decode('utf-8-sig'));changes=[]
        for _,part in doc.props(0):
            for section,table in doc.props(part):
                if section!='hydros': continue
                for row,nodes,props,inline in beam_rows(doc,table):
                    source=json.loads(doc.tokens[props['inputSource']].value) if 'inputSource' in props else 'steering_input'
                    if source not in ('steering','steering_input'): continue
                    existing=dict(doc.props(inline)) if inline is not None else {}
                    added={}
                    for key in ('inRate','outRate','autoCenterRate'):
                        if key in existing: changes.append((*doc.span(existing[key]),json.dumps(rate)))
                        else: added[key]=rate
                    if added:
                        if inline is not None:
                            pos=doc.tokens[inline].end
                            changes.append((pos,pos,json.dumps(added)[1:-1]+','))
                        else:
                            pos=doc.tokens[doc.ends[row]].start
                            sep='' if doc.tokens[doc.ends[row]-1].value==',' else ','
                            changes.append((pos,pos,sep+json.dumps(added)))
                    count+=1
        if changes: result[name]=edits(doc.text,changes).encode('utf-8')
    if not count: raise PatchError('Steering response: no steering hydros found in this vehicle.')
    result[prefix+'companion_steering_response.json']=json.dumps({'rate':rate,'steering_hydros':count}).encode()
    return result
