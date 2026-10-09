"""Triangulate AutoCraft's fixed steering-rack housing onto the chassis."""
import json
import math

from electric_patch import node_positions
from patcher import JBeam, PatchError, edits
from suspension_values import beam_rows


def apply(entries, prefix):
    result = dict(entries)
    name = prefix + 'suspension_F.jbeam'
    chassis = prefix + 'main.jbeam'
    if name not in entries or chassis not in entries:
        raise PatchError('Rack mounts require the AutoCraft front suspension and chassis.')
    text = entries[name].decode('utf-8-sig')
    doc = JBeam(text)
    part = doc.prop(0, 'suspension_F')
    nodes = node_positions(entries[chassis].decode('utf-8-sig'))
    nodes.update(node_positions(text))
    pairs = [(housing, anchor) for housing, anchors in (
        ('st2l', ('cc1l', 'cc1r', 'cc5l')),
        ('st2r', ('cc1r', 'cc1l', 'cc5r')),
    ) for anchor in anchors]
    if any(n not in nodes for pair in pairs for n in pair):
        raise PatchError('Rack mounts require AutoCraft st2 housing and cc1/cc5 chassis nodes.')
    # Three independent directions fix translation without tying down the
    # sliding st1 rack ends or adding any constraint to the outer ball joints.
    for side in ('l', 'r'):
        origin = nodes['st2' + side]
        directions = [tuple(b-a for a, b in zip(origin, nodes[anchor]))
                      for housing, anchor in pairs if housing == 'st2' + side]
        if any(math.sqrt(sum(x*x for x in v)) < .02 for v in directions):
            raise PatchError('Rack mount is too short for a stable chassis brace.')
        a, b, c = directions
        determinant = (a[0]*(b[1]*c[2]-b[2]*c[1])
                       - a[1]*(b[0]*c[2]-b[2]*c[0])
                       + a[2]*(b[0]*c[1]-b[1]*c[0]))
        normalized = abs(determinant) / math.prod(math.sqrt(sum(x*x for x in v)) for v in directions)
        if normalized < .02:
            raise PatchError('Rack mounts need three independent chassis brace directions.')
    table = doc.prop(part, 'beams')
    existing = {frozenset(row[:2]) for _, row, _, _ in beam_rows(doc, table) if len(row) >= 2}
    properties = dict(beamType='|NORMAL', beamSpring=600000, beamDamp=50,
                      beamPrecompression=1, beamDeform='FLT_MAX', beamStrength='FLT_MAX',
                      breakGroup='', dampCutoffHz=500)
    additions = [[a, b, dict(properties)] for a, b in pairs if frozenset((a, b)) not in existing]
    if additions:
        end = doc.tokens[doc.ends[table]].start
        sep = '' if doc.tokens[doc.ends[table]-1].value == ',' else ','
        extra = sep + '\n// Companion rack housing chassis anchors\n' + ',\n'.join(map(json.dumps, additions)) + ',\n'
        result[name] = edits(text, [(end, end, extra)]).encode('utf-8')
    result[prefix + 'companion_rack_mounts.json'] = (json.dumps(dict(
        housing_nodes=['st2l', 'st2r'], mounts=pairs,
        beam_spring=properties['beamSpring'], beam_damp=properties['beamDamp'],
        note='Chassis braces only; moving st1 nodes, steering hydros, rails and joints unchanged.'
    ), indent=2) + '\n').encode()
    return result
