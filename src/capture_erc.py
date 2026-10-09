"""Record the RC mod's read-only, localhost IMU/estimator trace."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
import time

ROOT=Path(__file__).resolve().parent

def capture(seconds=120, output=None):
    output=Path(output) if output else ROOT/'diagnostics'/('erc_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.jsonl')
    output.parent.mkdir(parents=True,exist_ok=True)
    count=jumps=0
    previous=None
    last_notice=time.monotonic()
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receiver, output.open('w',encoding='utf-8') as file:
        receiver.bind(('127.0.0.1',28610));receiver.settimeout(.5)
        end=time.monotonic()+seconds
        print('Listening for ERC trace on localhost:28610',flush=True)
        print('Recording to '+str(output),flush=True)
        while time.monotonic()<end:
            try: raw,address=receiver.recvfrom(65535)
            except socket.timeout:
                if time.monotonic()-last_notice>=10:
                    print(f'{count} samples received; {jumps} candidate jumps',flush=True);last_notice=time.monotonic()
                continue
            if address[0]!='127.0.0.1':continue
            try: row=json.loads(raw)
            except (ValueError,UnicodeError):continue
            if not isinstance(row,dict) or row.get('schema')!=1:continue
            row['receivedMonotonic']=time.monotonic()
            radius=row.get('radius')
            if previous and previous.get('vehicleID')==row.get('vehicleID'):
                prior=previous.get('radius')
                if isinstance(radius,(int,float)) and isinstance(prior,(int,float)) and prior>1:
                    if abs(radius-prior)>max(1,prior*.25):
                        jumps+=1;row['candidateJump']=True
                        print(f"Candidate jump at t={row.get('time')}: {prior:.2f} -> {radius:.2f} m",flush=True)
            file.write(json.dumps(row,separators=(',',':'))+'\n');file.flush()
            count+=1;previous=row
    print(f'Saved {count} samples and {jumps} candidate jumps to {output}',flush=True)
    return output,count,jumps

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=120)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    capture(args.seconds,args.output)
