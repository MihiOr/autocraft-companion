"""Restore exported physical parking torque after earlier regen-only patches."""
import base64
import json
from patcher import JBeam, MANIFEST, PatchError, edits
from suspension_values import beam_rows
from electric_patch import values


def wheel_parking(text):
    doc=JBeam(text);found={}
    for _,part in doc.props(0):
        if doc.tokens[part].value!='{':continue
        for key,table in doc.props(part):
            if key not in ('pressureWheels','wheels','rotators'):continue
            for _,row,props,_ in beam_rows(doc,table):
                if not row or row[0] in ('name','name:'):continue
                if 'parkingTorque' in props:
                    value=json.loads(doc.tokens[props['parkingTorque']].value)
                    if not isinstance(value,(int,float)) or value<0:raise PatchError('Parking brake needs numeric exported torque.')
                    found[str(row[0])]=value
    return found


def restore(entries,prefix):
    result=dict(entries);manifest=json.loads(entries.get(MANIFEST,b'{}'));originals=manifest.get('originals',{})
    torques={}
    for name,raw in originals.items():
        if name.startswith(prefix) and name.endswith(('wheels_F.jbeam','wheels_R.jbeam')):
            torques.update(wheel_parking(base64.b64decode(raw).decode('utf-8-sig')))
    if not torques:raise PatchError('Original parking torque is unavailable; export/reapply from the original download.')
    for name,raw in entries.items():
        if not name.startswith(prefix) or not name.endswith('.jbeam'):continue
        doc=JBeam(raw.decode('utf-8-sig'));changes=[]
        for _,part in doc.props(0):
            if doc.tokens[part].value!='{':continue
            for key,table in doc.props(part):
                if key not in ('pressureWheels','wheels','rotators'):continue
                for row,vals,props,inline in beam_rows(doc,table):
                    if not vals or str(vals[0]) not in torques:continue
                    value=torques[str(vals[0])]
                    # Set row-local value to cover original and every tire preset
                    # without changing the zero service-brake actuator.
                    if inline is not None:
                        own=dict(doc.props(inline))
                        if 'parkingTorque' in own:changes.append((*doc.span(own['parkingTorque']),json.dumps(value)))
                        else:
                            pos=doc.tokens[doc.ends[inline]].start
                            sep='' if doc.tokens[doc.ends[inline]-1].value==',' or not own else ','
                            changes.append((pos,pos,sep+'"parkingTorque":'+json.dumps(value)))
                    else:
                        pos=doc.tokens[doc.ends[row]].start
                        sep='' if doc.tokens[doc.ends[row]-1].value==',' else ','
                        changes.append((pos,pos,sep+json.dumps({'parkingTorque':value})))
        if changes:result[name]=edits(doc.text,changes).encode()
    result[prefix+'companion_parking_brake.json']=(json.dumps({'wheel_torque_nm':torques,'service_brakes':'regen only'},indent=2)+'\n').encode()
    return result
