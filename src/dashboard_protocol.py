"""PC -> STM32 full snapshots, matching ANDROID_BINARY_PROTOCOL.md bit layout."""
import math
from datetime import datetime

# id, name, width, signed, raw minimum, raw maximum, physical -> raw multiplier
FIELDS = [
 (0x00,'speedKmh',12,False,0,2550,10),
 (0x01,'longitudinalG',12,True,-2048,2047,1000),
 (0x02,'lateralG',12,True,-2048,2047,1000),
 (0x03,'mode',1,False,0,1,1),(0x04,'gear',8,False,0,2,1),
 (0x05,'parking',1,False,0,1,1),(0x06,'speedLimit',12,False,1,300,1),
 (0x07,'throttle',12,False,0,4095,4095),(0x08,'brake',12,False,0,4095,4095),
 (0x09,'steering',12,True,-2047,2047,2047),(0x0A,'launch',8,False,0,2,1),
 (0x0B,'powerKw',16,True,-32768,32767,10),
 (0x0C,'leftDoor',1,False,0,1,1),(0x0D,'rightDoor',1,False,0,1,1),
 (0x0E,'leftTurn',1,False,0,1,1),(0x0F,'rightTurn',1,False,0,1,1),
 (0x11,'lowBeam',1,False,0,1,1),(0x12,'highBeam',1,False,0,1,1),
 (0x13,'flBattery',8,False,0,100,1),(0x14,'flTemperature',16,True,-32768,32767,10),
 (0x15,'frBattery',8,False,0,100,1),(0x16,'frTemperature',16,True,-32768,32767,10),
 (0x17,'rlBattery',8,False,0,100,1),(0x18,'rlTemperature',16,True,-32768,32767,10),
 (0x19,'rrBattery',8,False,0,100,1),(0x1A,'rrTemperature',16,True,-32768,32767,10),
 (0x1B,'recoveredKwh',32,False,0,4294967295,1000),
 (0x1C,'recoveredKm',32,False,0,4294967295,1000),
 (0x1D,'tripKm',32,False,0,4294967295,1000),
 (0x1E,'tripKwh',32,False,0,4294967295,1000),
 (0x1F,'averageKwh',32,False,0,4294967295,1000),
 (0x20,'rangeKm',32,False,0,4294967295,1000),
 (0x21,'remainingKwh',32,False,0,4294967295,1000),
 (0x22,'outsideC',16,True,-32768,32767,10),
 (0x23,'clock',12,False,0,1439,1),
]
BY_ID={f[0]:f for f in FIELDS}
BY_ID[0x2B]=(0x2B,'seq',32,False,0,4294967295,1)


def raw_value(field, value):
    _,_,_,_,lo,hi,scale=field
    if not isinstance(value,(int,float)) or not math.isfinite(value): return lo
    if field[0]==0x23 and value==4095: return 4095
    x=value*scale
    # Nearest integer, halves away from zero.
    raw=math.floor(x+.5) if x>=0 else math.ceil(x-.5)
    return max(lo,min(hi,raw))


def encode_cells(cells):
    if not 2<=len(cells)<=63 or cells[0][0]!=0x2B: raise ValueError('Sequence must be first.')
    stream=len(cells); bits=8; seen=set()
    for ident,raw in cells:
        if ident not in BY_ID or ident in seen: raise ValueError('Unknown/duplicate telemetry ID')
        seen.add(ident)
        _,_,width,_,lo,hi,_=BY_ID[ident]
        if not lo<=raw<=hi and not (ident==0x23 and raw==4095): raise ValueError('Out-of-range raw value')
        stream=(stream<<6)|ident
        stream=(stream<<width)|(raw&((1<<width)-1));bits+=6+width
    padding=(-bits)%8
    return (stream<<padding).to_bytes((bits+padding)//8,'big')


def encode_snapshot(values, seq):
    values=dict(values)
    if 'clock' not in values:
        now=datetime.now();values['clock']=now.hour*60+now.minute
    cells=[(0x2B,seq&0xffffffff)]
    cells.extend((f[0],raw_value(f,values.get(f[1]))) for f in FIELDS)
    return encode_cells(cells)
