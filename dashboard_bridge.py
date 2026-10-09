"""Loopback UDP telemetry -> 24 Hz raw serial snapshots; ECU receive receipts provide USB flow control."""
import json
import os
import re
import socket
import threading
import time
from dashboard_protocol import encode_snapshot
from dashboard_dummy import DummyReceiver
import serial
from serial.tools import list_ports
UDP_PORT=28574
DUMMY='Dummy receiver (no hardware)'
ECU_USB_SERIAL=os.environ.get('AUTOCRAFT_ECU_USB_SERIAL', '').strip().upper()
def ports():
    return [DUMMY]+[p.device for p in list_ports.comports()
                    if not ECU_USB_SERIAL or (p.serial_number or '').upper()==ECU_USB_SERIAL]
def validate_ecu_port(port):
    if not ECU_USB_SERIAL: return
    found=next((p for p in list_ports.comports() if p.device.upper()==port.upper()),None)
    if found is None or (found.serial_number or '').upper()!=ECU_USB_SERIAL:
        raise ValueError('Selected port is not the ECU configured by AUTOCRAFT_ECU_USB_SERIAL.')
class DashboardBridge:
    def __init__(self):
        self.stop_event=threading.Event();self.thread=None
        self.status='Disconnected';self.sent=0;self.bytes_sent=0
        self.receiver=DummyReceiver();self.last_packet=b''
        self.udp=None;self.serial=None
        self.last_telemetry_at=None;self.mfi_confirmed=0
    @property
    def running(self): return self.thread is not None and self.thread.is_alive()
    @property
    def beamng_connected(self):
        received = self.last_telemetry_at
        return self.running and received is not None and time.monotonic() - received < 1
    @property
    def beamng_status(self):
        if self.beamng_connected:
            return 'BeamNG: Connected — receiving vehicle telemetry'
        if self.running:
            return 'BeamNG: Not connected — waiting for vehicle telemetry'
        return 'BeamNG: Not connected — click Connect in Dashboard'
    def start(self, port, baud=921600, udp_port=UDP_PORT):
        if self.running: raise ValueError('Disconnect before changing ports.')
        baud=int(baud)
        if not 38400<=baud<=4000000: raise ValueError('Use 38400–4000000 baud for 24 Hz full snapshots.')
        if not port: raise ValueError('Choose a COM port or dummy receiver.')
        if port!=DUMMY and not re.fullmatch(r'COM[1-9]\d*',port,re.IGNORECASE):
            raise ValueError('Choose a COM port (such as COM3) or the dummy receiver.')
        if port!=DUMMY: validate_ecu_port(port)
        self.udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            self.udp.bind(('127.0.0.1',udp_port));self.udp.setblocking(False)
            self.serial=serial.serial_for_url('loop://' if port==DUMMY else port,
                baudrate=baud,bytesize=8,parity='N',stopbits=1,timeout=0,
                write_timeout=.25,xonxoff=False,rtscts=False,dsrdtr=False)
        except Exception:
            self.udp.close();self.udp=None;raise
        self.sent=0;self.bytes_sent=0;self.receiver=DummyReceiver()
        self.last_telemetry_at=None;self.mfi_confirmed=0
        self.stop_event.clear();self.status='Waiting for BeamNG telemetry'
        self.thread=threading.Thread(target=self._run,args=(port==DUMMY,),daemon=True)
        self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=3)
        if not self.running: self.status='Disconnected'
    def _write_physical_batch(self, packets):
        # Keep even-sized USB writes; advance only after ECU processing receipt.
        batch=b''.join(packets)
        if len(packets)!=2 or len(batch)!=182:
            raise ValueError('Expected two complete 91-byte dashboard snapshots.')
        for offset in range(0,len(batch),64):
            chunk=batch[offset:offset+64]
            if self.serial.write(chunk)!=len(chunk):
                raise IOError('Incomplete serial batch; reset ECU before reconnecting.')
            self._wait_ecu_receipt(len(chunk))
    def _wait_ecu_receipt(self, length):
        deadline=time.monotonic()+2.5  # ECU MFI timeout is 2 seconds.
        line=bytearray()
        while time.monotonic()<deadline:
            byte=self.serial.read(1)
            if not byte:
                time.sleep(.001)
                continue
            line.extend(byte)
            if len(line)>160: raise IOError('Invalid ECU feedback; reset ECU before reconnecting.')
            if byte==b'\n':
                text=line.decode('ascii',errors='replace').strip()
                if text.startswith('ECU TERMINAL ERROR:'): raise IOError(text)
                match=re.fullmatch(r'ECU RX (\d+) MFI (\d+)',text)
                if not match or int(match[1])!=length:
                    raise IOError('Unexpected ECU receipt: '+text)
                self.mfi_confirmed=int(match[2])
                return
        raise IOError('ECU receipt timeout; stop and reset ECU before reconnecting. No automatic retry.')
    def _run(self, dummy):
        pending=[]
        latest=None; received=0; seq=1; deadline=time.monotonic(); source=None
        try:
            while not self.stop_event.is_set():
                # Drain bounded batches; retain the newest complete local telemetry datagram.
                for _ in range(100):
                    try: data,_=self.udp.recvfrom(16384)
                    except BlockingIOError: break
                    try:
                        message=json.loads(data)
                        if message.get('schema')!=1 or not isinstance(message.get('values'),dict): continue
                        if source!=message.get('source'): source=message.get('source')
                        latest=message['values'];received=time.monotonic()
                        self.last_telemetry_at=received
                    except (ValueError,AttributeError,TypeError): continue
                now=time.monotonic()
                if now>=deadline:
                    deadline+=1/24
                    if deadline<now: deadline=now+1/24  # no catch-up bursts
                    if latest is not None and now-received<1:
                        packet=encode_snapshot(latest,(seq+len(pending))&0xffffffff)
                        if dummy:
                            if self.serial.write(packet)!=len(packet): raise IOError('Incomplete serial packet; reconnect receiver to reset framing.')
                            completed=[packet]
                        else:
                            pending.append(packet)
                            completed=[]
                            if len(pending)==2:
                                self._write_physical_batch(pending)
                                completed=pending
                                pending=[]
                        if completed:
                            self.last_packet=completed[-1]
                            self.sent+=len(completed)
                            self.bytes_sent+=sum(map(len,completed))
                            seq=(seq+len(completed))&0xffffffff
                        if dummy:
                            # Intentionally split reads across fields and packet boundaries.
                            for _ in range(40):
                                chunk=self.serial.read(3)
                                if not chunk: break
                                self.receiver.feed(chunk)
                        destination='Dummy' if dummy else (f'ECU received · MFI ACKs {self.mfi_confirmed}' if self.sent else 'Awaiting ECU receipt')
                        self.status=f"{destination} · 24 Hz target · {self.sent} packets · {self.bytes_sent} bytes"
                    else:
                        pending=[] # Nothing was sent: discard an unmatched stale snapshot.
                        self.status='Waiting for BeamNG telemetry (no fresh vehicle data)'
                self.stop_event.wait(min(.005,max(0,deadline-time.monotonic())))
        except Exception as exc:
            self.status='Bridge error: '+str(exc)
        finally:
            if self.serial: self.serial.close()
            if self.udp: self.udp.close()
