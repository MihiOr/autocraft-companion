"""Local BeamNG diagnostic client. Standard Python only; Companion needn't run."""
import argparse
import json
import socket
import time
from pathlib import Path
from zipfile import ZipFile


class DebugClient:
    def __init__(self, command_port=28580, telemetry_port=28581):
        self.command_port=command_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', telemetry_port))
        self.sock.settimeout(.1)
        self.vehicle_id = None
        self.control_owned = False

    def receive(self):
        try:
            raw, address = self.sock.recvfrom(65535)
        except socket.timeout:
            return None
        if address[0] != '127.0.0.1':
            return None
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            return None
        if not isinstance(data, dict) or data.get('schema') != 1:
            return None
        if data.get('status') == 'ready' and self.vehicle_id is None:
            self.vehicle_id = data.get('vehicleID')
        return data

    def send(self, op, **values):
        if self.vehicle_id is None:
            raise RuntimeError('No supported Minini car detected yet.')
        packet = dict(schema=1, vehicleID=self.vehicle_id, op=op, **values)
        self.sock.sendto(json.dumps(packet, allow_nan=False).encode(), ('127.0.0.1', self.command_port))
        if op == 'control':
            self.control_owned = True
        elif op == 'release':
            self.control_owned = False

    def close(self):
        if self.control_owned:
            try:
                self.send('release')
            except OSError:
                pass
        self.sock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('watch', 'drive', 'replace', 'reload'), nargs='?', default='watch')
    p.add_argument('--zip', type=Path, help='Installed Companion vehicle ZIP to replace the active car with')
    p.add_argument('--model', help='Installed vehicle folder ID for replace')
    p.add_argument('--seconds', type=float, default=10)
    p.add_argument('--throttle', type=float, default=0)
    p.add_argument('--brake', type=float, default=0)
    p.add_argument('--steering', type=float, default=0)
    p.add_argument('--parkingbrake', type=float, default=0)
    p.add_argument('--gear', type=int, choices=(-1, 0, 1), help='Optional stock selector request; omitted leaves direction to the custom ECU')
    p.add_argument('--log', type=Path, help='Write complete telemetry as JSON lines')
    args = p.parse_args()
    model = args.model
    if args.mode == 'replace':
        if args.zip:
            with ZipFile(args.zip) as z:
                roots = {n.split('/')[1] for n in z.namelist() if n.startswith('vehicles/') and n.endswith('/engine.jbeam')}
            if len(roots) != 1:
                p.error('Vehicle ZIP must contain one engine.jbeam')
            model = roots.pop()
        if not model:
            p.error('replace requires --zip or --model')
    if not 0 < args.seconds <= 120:
        p.error('--seconds must be above 0 and at most 120')
    for name in ('throttle', 'brake', 'steering', 'parkingbrake'):
        value = getattr(args, name)
        if not (-1 if name == 'steering' else 0) <= value <= 1:
            p.error(f'Invalid --{name}')
    client = DebugClient()
    output = args.log.open('w', encoding='utf-8') if args.log else None
    last, heartbeat, requested, completed = 0, 0, False, False
    try:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            data = client.receive()
            now = time.monotonic()
            if data:
                if output:
                    output.write(json.dumps(dict(receivedAt=now, **data), allow_nan=False) + '\n')
                    output.flush()
                if data.get('status') == 'error':
                    raise RuntimeError(data.get('error'))
                if args.mode in ('replace', 'reload') and client.vehicle_id is not None and not requested:
                    client.send(args.mode, **({'model': model} if args.mode == 'replace' else {}))
                    requested = True
                if requested and args.mode == 'replace' and data.get('model') == model and data.get('status') == 'ready':
                    print('Replacement loaded:', model, flush=True)
                    completed = True
                    break
                if requested and args.mode == 'reload' and data.get('status') == 'reloading':
                    print('Game Lua reload requested (Ctrl+L equivalent).', flush=True)
                    completed = True
                    break
                if now - last >= .5:
                    last = now
                    ecu = data.get('ecu', {})
                    torque = {w: round(m.get('torque', 0), 1) for w, m in data.get('motors', {}).items()}
                    imus = sum(bool(s.get('valid')) for s in data.get('imu', {}).values())
                    print(f"{data.get('status')} id={data.get('vehicleID')} "
                          f"speed={data.get('speed', 0)*3.6:.1f}km/h "
                          f"gear={data.get('gear')} pedals={data.get('pedals')} "
                          f"torque={torque} IMUs={imus}/4 error={ecu.get('error') or data.get('imuError')}", flush=True)
                # Never transfer an active test to another vehicle automatically.
                if args.mode == 'drive' and data.get('vehicleID') != client.vehicle_id:
                    raise RuntimeError('Active vehicle changed; drive test stopped.')
            if args.mode == 'drive' and client.vehicle_id is not None and now - heartbeat >= .1:
                heartbeat = now
                client.send('control', **{k: getattr(args, k) for k in
                            ('throttle', 'brake', 'steering', 'parkingbrake', 'gear')
                            if getattr(args,k) is not None})
        if last == 0:
            if not requested:
                raise RuntimeError('No debug packets received. Enable MininiDebug.zip and reload game Lua (Ctrl+L).')
        if args.mode in ('replace', 'reload') and not requested:
            raise RuntimeError('No supported Companion EV detected.')
        if args.mode in ('replace', 'reload') and not completed:
            raise RuntimeError('Command was not acknowledged before timeout. The loaded debug bridge may need updating.')
    finally:
        client.close()
        if output:
            output.close()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, KeyboardInterrupt) as exc:
        raise SystemExit(str(exc))
