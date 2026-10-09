"""Bézier profile storage and deterministic curve baking for the custom Lua."""
import copy
import json
import math
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parent
FOLDER = ROOT/'motor_graphs'
ACTIVE = FOLDER/'_active.json'
LABELS = {
    'steering': ('Steering input → yaw rate', 'Steering wheel (degrees; right +)',
                 'Yaw rate at reference speed (degrees/s; left +)'),
    'correction': ('Yaw-rate error → correction', 'Yaw-rate error (degrees/s)',
                   'Angular acceleration correction (degrees/s²)'),
}


def number(value):
    if isinstance(value, bool):
        raise ValueError('Enter a number.')
    value = float(str(value).replace(',', '.'))
    if not math.isfinite(value) or abs(value)>1e8:
        raise ValueError('Values must be finite and below 100,000,000 in magnitude.')
    return value


def validate(profile):
    try:
        return _validate(profile)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError('Invalid motor graph file structure.') from exc


def _validate(profile):
    p = copy.deepcopy(profile)
    if not isinstance(p, dict):
        raise ValueError('A motor graph profile must be an object.')
    if p.get('version') != 1:
        raise ValueError('Unsupported graph file version.')
    for key in ('reference_speed_kmh', 'steering_lock_degrees'):
        p[key] = number(p[key])
        if not 0 < p[key] <= 10000:
            raise ValueError(f'Invalid {key}.')
    for key in LABELS:
        graph = p['graphs'][key]
        if graph.get('mode') not in ('auto', 'manual'):
            raise ValueError('Curve mode must be auto or manual.')
        points = graph['points']
        if not isinstance(points, list) or any(not isinstance(pt, dict) for pt in points):
            raise ValueError('Graph points must be a list of X/Y objects.')
        if not 2 <= len(points) <= 2000:
            raise ValueError('Each graph needs 2–2000 points.')
        for pt in points:
            pt['x'],pt['y'] = number(pt['x']),number(pt['y'])
            if 'measured_y' in pt:pt.setdefault('measured_x',pt['x'])
            for measured in ('measured_x','measured_y'):
                if measured in pt:pt[measured]=number(pt[measured])
            for handle in ('in', 'out'):
                if handle in pt:
                    if not isinstance(pt[handle], (list, tuple)) or len(pt[handle]) != 2:
                        raise ValueError('A Bézier handle needs X and Y.')
                    pt[handle] = [number(v) for v in pt[handle]]
        points.sort(key=lambda pt:pt['x'])
        if any(b['x']-a['x']<1e-6 for a,b in zip(points,points[1:])):
            raise ValueError('Point X values must be distinct.')
        for a,b in zip(points,points[1:]):
            if graph['mode']=='manual':
                for pt,handle in ((a,'out'),(b,'in')):
                    if handle in pt and not a['x']<=pt[handle][0]<=b['x']:
                        raise ValueError('Handle X must stay between adjacent points.')
    return p


def slopes(points):
    """PCHIP tangents: interpolate every knot without overshooting monotone data."""
    h = [b['x']-a['x'] for a,b in zip(points,points[1:])]
    d = [(b['y']-a['y'])/dx for a,b,dx in zip(points,points[1:],h)]
    if len(points)==2:
        return [d[0],d[0]]
    m = [0.0]*len(points)
    def edge(h0,h1,d0,d1):
        v=((2*h0+h1)*d0-h0*d1)/(h0+h1)
        if v*d0<=0:return 0.0
        if d0*d1<0 and abs(v)>3*abs(d0):return 3*d0
        return v
    m[0] = edge(h[0],h[1],d[0],d[1])
    m[-1] = edge(h[-1],h[-2],d[-1],d[-2])
    for i in range(1,len(points)-1):
        if d[i-1]*d[i]>0:
            w1,w2=2*h[i]+h[i-1],h[i]+2*h[i-1]
            m[i]=(w1+w2)/(w1/d[i-1]+w2/d[i])
    return m


def segments(graph):
    pts=graph['points'];tangents=slopes(pts)
    out=[]
    for i,(a,b) in enumerate(zip(pts,pts[1:])):
        dx=(b['x']-a['x'])/3
        c1=(a['x']+dx,a['y']+dx*tangents[i])
        c2=(b['x']-dx,b['y']-dx*tangents[i+1])
        if graph['mode']=='manual':
            c1=tuple(a.get('out',c1));c2=tuple(b.get('in',c2))
        out.append(((a['x'],a['y']),c1,c2,(b['x'],b['y'])))
    return out


def bezier(segment,t):
    a,b,c,d=segment;u=1-t
    return tuple(u**3*a[i]+3*u*u*t*b[i]+3*u*t*t*c[i]+t**3*d[i] for i in (0,1))


def bake(graph,tolerance=.01,max_dx=2):
    """Adaptive polyline, preserving every knot and bounding interpolation error."""
    result=[]
    def split(seg,t0,t1,depth=0):
        a,b=bezier(seg,t0),bezier(seg,t1)
        bad=b[0]-a[0]>max_dx
        for fraction in (.25,.5,.75):
            q=bezier(seg,t0+(t1-t0)*fraction)
            linear=a[1]+(q[0]-a[0])/(b[0]-a[0])*(b[1]-a[1]) if b[0]>a[0] else a[1]
            bad=bad or abs(q[1]-linear)>tolerance
        if bad:
            if depth>=18:
                raise ValueError('Curve is too sharp to sample reliably. Move its handles closer.')
            mid=(t0+t1)/2;split(seg,t0,mid,depth+1);split(seg,mid,t1,depth+1)
        else:
            result.append(b)
            if len(result)>6000:
                raise ValueError('Curve needs too many samples. Reduce sharp handle bends.')
    for seg in segments(graph):
        if not result:result.append(seg[0])
        split(seg,0,1)
    return result


def defaults():
    calibration=json.loads((ROOT/'steering_calibration.json').read_text())
    speed=calibration['reference_speed_kmh']/3.6
    pts=[dict(x=p['degrees'],measured_x=p['degrees'],y=p.get('fitted_curvature',p['curvature'])*speed*180/math.pi,
              measured_y=p['yaw_rad_s']*180/math.pi) for p in calibration['points']]
    return validate(dict(version=1,reference_speed_kmh=calibration['reference_speed_kmh'],
                         steering_lock_degrees=calibration['steering_wheel_lock_degrees'],
                         graphs=dict(steering=dict(mode='auto',points=pts),
                                     correction=dict(mode='auto',points=[dict(x=x,y=12*x) for x in (-180,0,180)]))))


def load(path):
    try:return validate(json.loads(Path(path).read_text(encoding='utf-8')))
    except (KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('Invalid motor graph file.') from exc


def save(path,profile):
    path=Path(path);p=validate(profile)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(p,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    tmp.replace(path)


def ensure_files():
    FOLDER.mkdir(exist_ok=True)
    default=FOLDER/'Measured default.json'
    if not default.exists():save(default,defaults())
    if not ACTIVE.exists():save(ACTIVE,load(default))
    return load(ACTIVE)


def lua_source(source,profile):
    p=validate(profile)
    def replace(start,end,text):
        nonlocal source
        pattern=re.escape(start)+r'.*?'+re.escape(end)
        source,count=re.subn(pattern,lambda _:start+'\n'+text+'\n'+end,source,flags=re.S)
        if count!=1:raise ValueError(f'Missing graph section: {start}.')
    steering=bake(p['graphs']['steering'],tolerance=.01,max_dx=2)
    correction=bake(p['graphs']['correction'],tolerance=.05,max_dx=2)
    def table(name,rows):
        return 'local '+name+' = {\n'+',\n'.join(f'  {{{x:.17g}, {y:.17g}}}' for x,y in rows)+'\n}'
    replace('-- BEGIN_MEASURED_STEERING','-- END_MEASURED_STEERING',
            table('steeringCurve',[(x/p['steering_lock_degrees'],math.radians(y)/(p['reference_speed_kmh']/3.6)) for x,y in steering]))
    replace('-- BEGIN_YAW_CORRECTION_GRAPH','-- END_YAW_CORRECTION_GRAPH',
            f"local steeringGraphLockDegrees = {p['steering_lock_degrees']:.14g}\n"+
            table('yawCorrectionCurve',[(math.radians(x),math.radians(y)) for x,y in correction]))
    return source


def _atomic_write(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'-',suffix='.tmp',dir=path.parent)
    import os
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw)
        Path(tmp).replace(path)
    finally:Path(tmp).unlink(missing_ok=True)


def apply(profile,save_path=None):
    from custom_control import USER_FILE,check_code
    profile=validate(profile)
    source=USER_FILE.read_text(encoding='utf-8-sig')
    candidate=lua_source(source,profile)
    check_code(candidate)
    raw=(json.dumps(profile,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
    updates={FOLDER/'_previous_motor_control.lua':source.encode('utf-8')}
    if save_path:updates[Path(save_path)]=raw
    updates[ACTIVE]=raw;updates[USER_FILE]=candidate.encode('utf-8')
    previous={path:path.read_bytes() if path.exists() else None for path in updates}
    written=[]
    try:
        for path,data in updates.items():
            _atomic_write(path,data);written.append(path)
    except OSError:
        for path in reversed(written):
            if previous[path] is None:path.unlink(missing_ok=True)
            else:_atomic_write(path,previous[path])
        raise
    return len(bake(profile['graphs']['steering'])),len(bake(profile['graphs']['correction'],tolerance=.05))
