"""Strengthen the hub-to-upright beams, not the suspension or halfshafts."""
import json
import math
import re

from patcher import JBeam, PatchError, edits, number
from electric_patch import values


def properties(doc, obj):
    # AutoCraft sometimes leaves inline option names unquoted.
    result={};i=obj+1
    while i<doc.ends[obj]:
        token=doc.tokens[i]
        if i+2<doc.ends[obj] and doc.tokens[i+1].value==':':
            key=json.loads(token.value) if token.value.startswith('"') else token.value
            value=i+2;result[key]=value;i=doc.ends.get(value,value)+1
        else:i=doc.ends.get(i,i)+1
    return result


def attachment_side(nodes, axle):
    if len(nodes)<2:return None
    letter=axle.lower()
    for wheel,upright in (nodes[:2],nodes[:2][::-1]):
        match=re.fullmatch(letter+r'w[12]([lr])',str(wheel))
        if match and str(upright) in {letter+part+match[1] for part in ('na','nc','h1','h2')}:
            return match[1]
    return None


def patch_axle(text, axle, multiplier):
    doc=JBeam(text);part=doc.prop(0,'suspension_'+axle);table=doc.prop(part,'beams')
    state={};changes=[];report=[];seen=set();counts={'l':0,'r':0};i=table+1
    while i<doc.ends[table]:
        token=doc.tokens[i].value
        if token=='{':state.update(properties(doc,i))
        elif token=='[':
            nodes=values(doc,i);side=attachment_side(nodes,axle)
            if side:
                pair=tuple(sorted(nodes[:2]))
                if pair in seen:raise PatchError('Duplicate wheel attachment beam: '+' / '.join(pair))
                seen.add(pair);counts[side]+=1
                inline=next((j for j in range(i+1,doc.ends[i]) if doc.tokens[j].value=='{'),None)
                own=properties(doc,inline) if inline is not None else {}
                local=dict(state);local.update(own);added={};details={'nodes':nodes[:2]}
                for key in ('beamStrength','beamDeform'):
                    if key not in local:
                        if key=='beamDeform':continue
                        raise PatchError('Missing wheel attachment beam strength.')
                    value=doc.tokens[local[key]].value
                    if value in ('"FLT_MAX"','FLT_MAX'):continue
                    try:base=float(value)
                    except ValueError:raise PatchError('Wheel attachment strength must be numeric or FLT_MAX.') from None
                    if not math.isfinite(base) or base<=0:raise PatchError('Invalid wheel attachment strength.')
                    scaled=base*multiplier
                    details[key]={'before':base,'after':scaled}
                    if key in own:changes.append((*doc.span(own[key]),format(scaled,'.12g')))
                    else:added[key]=scaled
                if added:
                    if inline is not None:
                        start=doc.tokens[inline].end
                        changes.append((start,start,json.dumps(added)[1:-1]+(',' if own else '')))
                    else:
                        end=doc.tokens[doc.ends[i]].start
                        comma='' if doc.tokens[doc.ends[i]-1].value==',' else ','
                        changes.append((end,end,comma+json.dumps(added)))
                report.append(details)
        i=doc.ends.get(i,i)+1
    if counts!={'l':8,'r':8}:
        raise PatchError('Wheel attachment override expects eight hub-to-upright beams per wheel on axle '+axle+'.')
    return edits(text,changes),report


def apply(entries, prefix, settings):
    result=dict(entries)
    if not settings.get('wheel_attachment_enabled',False):return result
    multiplier=number({'wheel_attachment_multiplier':settings.get('wheel_attachment_multiplier',2)},
                      'wheel_attachment_multiplier',.1,100)
    report={'multiplier':multiplier,'axles':{},'note':'Break and finite deformation thresholds only; no stiffness, damping, mass, geometry or break-group changes.'}
    for axle in ('F','R'):
        name=prefix+'suspension_'+axle+'.jbeam'
        if name not in result:raise PatchError('Missing suspension for wheel attachment override: '+axle)
        text,report['axles'][axle]=patch_axle(result[name].decode('utf-8-sig'),axle,multiplier)
        result[name]=text.encode('utf-8')
    result[prefix+'companion_wheel_attachment_report.json']=(json.dumps(report,indent=2)+'\n').encode()
    return result
