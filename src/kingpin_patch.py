"""Passive kingpin rotation stops calibrated to the exported suspension pose."""
import json
import math

from electric_patch import node_positions
from patcher import JBeam, PatchError, edits, number


def rotation_limit(lower, upper, point, anchor, allowance):
    axis = tuple(b-a for a,b in zip(lower,upper))
    length = math.sqrt(sum(v*v for v in axis))
    if length < .01:
        raise PatchError('Kingpin stops: degenerate steering axis.')
    axis = tuple(v/length for v in axis)
    v = tuple(p-a for p,a in zip(point,lower))
    dot = sum(a*b for a,b in zip(v,axis))
    parallel = tuple(a*dot for a in axis)
    radial = tuple(a-b for a,b in zip(v,parallel))
    if math.sqrt(sum(v*v for v in radial)) < .01:
        raise PatchError('Kingpin stops: upright lever lies on the steering axis.')
    cross = (axis[1]*v[2]-axis[2]*v[1],axis[2]*v[0]-axis[0]*v[2],axis[0]*v[1]-axis[1]*v[0])
    offset = tuple(a+b-c for a,b,c in zip(lower,parallel,anchor))
    # Squared distance is constant + A*cos(theta) + B*sin(theta).
    A = 2*sum(a*b for a,b in zip(offset,radial))
    B = 2*sum(a*b for a,b in zip(offset,cross))
    bound = math.radians(allowance)
    angles = [-bound,0,bound]
    critical = math.atan2(B,A)
    angles += [critical+k*math.pi for k in range(-2,3) if -bound <= critical+k*math.pi <= bound]
    def distance(theta):
        return math.sqrt(sum((o+r*math.cos(theta)+c*math.sin(theta))**2 for o,r,c in zip(offset,radial,cross)))
    lengths = list(map(distance,angles))
    return math.dist(point,anchor),min(lengths),max(lengths)


def patch_axle(text, axle, allowance):
    doc = JBeam(text)
    part = doc.prop(0, 'suspension_'+axle)
    if 'DWB_' not in text:
        raise PatchError('Kingpin stops supports AutoCraft double wishbones only.')
    nodes = node_positions(text)
    letter = axle.lower()
    required = [letter+base+side for side in ('l','r') for base in ('h1','h2','na','nc','x3','x4')]
    if any(n not in nodes for n in required):
        raise PatchError('Kingpin stops: missing upright or wishbone nodes on axle '+axle)
    additions, report = [], []
    for side in ('l','r'):
        lower,upper = nodes[letter+'h2'+side],nodes[letter+'h1'+side]
        for lever in ('na','nc'):
            other = letter+lever+side
            for anchor_id in ('x3','x4'):
                anchor = letter+anchor_id+side
                rest,low,high = rotation_limit(lower,upper,nodes[other],nodes[anchor],allowance)
                if rest < .01:
                    raise PatchError('Kingpin stops: degenerate stop length.')
                props = {'beamType':'|BOUNDED','beamPrecompression':1,
                         'beamSpring':0,'beamDamp':0,'beamLimitSpring':3000000,'beamLimitDamp':250,
                         'beamShortBound':max(0,1-low/rest),'beamLongBound':max(0,high/rest-1),'boundZone':.002,
                         'beamDeform':'FLT_MAX','beamStrength':'FLT_MAX','breakGroup':''}
                additions.append([other,anchor,props])
                report.append({'axis':[letter+'h2'+side,letter+'h1'+side],
                               'nodes':[other,anchor],'min_m':low,'max_m':high})
    beams = doc.prop(part,'beams')
    end = doc.tokens[doc.ends[beams]].start
    sep = '' if doc.tokens[doc.ends[beams]-1].value == ',' else ','
    addition = sep+'\n// Companion kingpin rotation stops\n'+',\n'.join(map(json.dumps,additions))+',\n'
    return edits(text,[(end,end,addition)]), report


def apply(entries, prefix, settings):
    result, report = dict(entries), {'reference':'exported joint position','axles':{}}
    for axle, label in (('F','front'),('R','rear')):
        key = 'kingpin_'+label+'_angle'
        allowance = number({key:settings.get(key,45)},key,5,45)
        name = prefix+'suspension_'+axle+'.jbeam'
        text, limits = patch_axle(result[name].decode('utf-8-sig'),axle,allowance)
        result[name] = text.encode()
        report['axles'][axle] = {'allowance_deg':allowance,'limits':limits}
    result[prefix+'companion_kingpin_stops.json'] = (json.dumps(report,indent=2)+'\n').encode()
    return result
