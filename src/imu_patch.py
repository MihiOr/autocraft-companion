"""Place four virtual IMUs on existing chassis nodes; no added physical mass."""
import math
from electric_patch import node_positions


def mounts(entries, prefix):
    if prefix+'main.jbeam' not in entries:
        return None
    positions={}
    for file in ('main','suspension_F','suspension_R'):
        if prefix+file+'.jbeam' in entries:
            positions.update(node_positions(entries[prefix+file+'.jbeam'].decode('utf-8-sig')))
    chassis={n:p for n,p in positions.items() if n.startswith('cc')}
    if len(chassis)<4:return None
    def sub(a,b):return [x-y for x,y in zip(a,b)]
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    def unit(a):
        length=math.sqrt(dot(a,a))
        if length<1e-8:raise ValueError('Degenerate IMU mounting geometry')
        return [x/length for x in a]
    def mean(a,b):return [(x+y)/2 for x,y in zip(a,b)]
    hubs={n:mean(positions[n[0].lower()+'w1'+n[1].lower()],positions[n[0].lower()+'w2'+n[1].lower()])
          for n in ('FL','FR','RL','RR')}
    front=mean(hubs['FL'],hubs['FR']);rear=mean(hubs['RL'],hubs['RR'])
    forward=unit(sub(front,rear));left=unit(sub(hubs['FL'],hubs['FR']));up=unit(cross(forward,left))
    left=unit(cross(up,forward));center=mean(front,rear)
    selected={};used=set()
    for name,hub in hubs.items():
        node=min((n for n in chassis if n not in used),key=lambda n:math.dist(chassis[n],hub))
        selected[name]=node;used.add(node)
    mount_center=[sum(chassis[n][i] for n in selected.values())/4 for i in range(3)]
    sensors={}
    for name,node in selected.items():
        p=chassis[node];near=sorted((n for n in chassis if n!=node),key=lambda n:math.dist(chassis[n],p))
        triangle=None
        for a in near:
            for b in near:
                edge=sub(chassis[a],p);other=sub(chassis[b],p)
                if math.sqrt(dot(cross(edge,other),cross(edge,other)))>.025:
                    triangle=(a,b);break
            if triangle:break
        if triangle is None:raise ValueError('No stable chassis triangle for IMU '+name)
        a,b=triangle;u=unit(sub(chassis[a],p));normal=unit(cross(u,sub(chassis[b],p)));side=unit(cross(normal,u))
        offset=sub(p,mount_center)
        sensors[name]={'nodes':[node,a,b],
            'forward':[dot(forward,e) for e in (u,normal,side)],
            'left':[dot(left,e) for e in (u,normal,side)],
            'up':[dot(up,e) for e in (u,normal,side)],
            'offset':{'forward':dot(offset,forward),'left':dot(offset,left),'up':dot(offset,up)}}
    return {'mounts':sensors,'wheelbase':math.dist(front,rear),
            'trackFront':math.dist(hubs['FL'],hubs['FR']),'trackRear':math.dist(hubs['RL'],hubs['RR']),
            'note':'Four chassis IMUs: specific force in m/s^2, gyro in rad/s; forward/left/up. No heading or true slip angle exposed.'}
