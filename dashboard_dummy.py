"""Incremental virtual STM32 receiver. Handles fragmented and combined reads."""
from dashboard_protocol import BY_ID


class DummyReceiver:
    def __init__(self):
        self.buffer=bytearray()
        self.packets=0
        self.latest={}

    def feed(self, data):
        self.buffer.extend(data)
        decoded=[]
        while self.buffer:
            count=self.buffer[0]
            if not 2<=count<=63: raise ValueError('Invalid COUNT')
            offset=8; values={}; complete=True
            def read(width):
                nonlocal offset
                if offset+width>len(self.buffer)*8: raise EOFError
                value=0
                for pos in range(offset,offset+width):
                    value=(value<<1)|((self.buffer[pos//8]>>(7-pos%8))&1)
                offset+=width
                return value
            try:
                for index in range(count):
                    ident=read(6)
                    if ident not in BY_ID or (index==0 and ident!=0x2B): raise ValueError('Invalid ID/sequence')
                    _,name,width,signed,lo,hi,scale=BY_ID[ident]
                    if name in values: raise ValueError('Duplicate field')
                    raw=read(width)
                    if signed and raw&(1<<(width-1)): raw-=1<<width
                    if not lo<=raw<=hi and not (ident==0x23 and raw==4095): raise ValueError('Invalid range')
                    values[name]=raw/scale if scale!=1 else raw
                if read((-offset)%8)!=0: raise ValueError('Nonzero padding')
            except EOFError:
                complete=False
            if not complete: break
            del self.buffer[:offset//8]
            self.latest=values;self.packets+=1;decoded.append(values)
        return decoded
