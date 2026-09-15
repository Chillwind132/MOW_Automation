"""Bounded external observation of selected human units; no injection or orders."""
import argparse
import datetime
import json
import struct
import time
from tactical_map import Reader, Image, OUT


def snapshot(reader):
    def u(a): return struct.unpack('<I',reader.read(a,4))[0]
    game=u(0xfe6384)
    if u(game)!=0xe12468: raise ValueError('Unrecognized game-control object')
    selection=u(game+0x58)
    if u(selection)!=0xe125b8: raise ValueError('Unrecognized selection object')
    begin,end,capacity=struct.unpack('<3I',reader.read(selection+4,12))
    if not begin<=end<=capacity or (end-begin)%8 or end-begin>32*8:
        raise ValueError('Invalid selection vector')
    records=[]
    vector=reader.read(begin,end-begin) if end>begin else b''
    for i in range(0,len(vector),8):
        actor=struct.unpack_from('<I',vector,i)[0]
        if not actor: continue
        actor_data=reader.read(actor,0x79c)
        brain=struct.unpack_from('<I',actor_data,0x78c)[0]
        if not brain or u(brain)!=0xdfbed0: continue
        b=reader.read(brain,0x2d8)
        if struct.unpack_from('<I',b,0x20)[0]!=actor: raise ValueError('Brain owner mismatch')
        pose=struct.unpack_from('<I',actor_data,0x798)[0]
        cover=struct.unpack_from('<I',actor_data,0x788)[0]
        records.append({'actor':hex(actor),'brain':hex(brain),
            'position':struct.unpack_from('<3f',actor_data,0x44),
            'transform_rows_xy':struct.unpack_from('<6f',actor_data,0x20),
            'flags210':hex(struct.unpack_from('<I',b,0x210)[0]),
            'flags214':hex(struct.unpack_from('<I',b,0x214)[0]),
            'movement_bits':hex(struct.unpack_from('<I',b,0x210)[0]&0x3000),
            'pose':u(pose+0x20),'cover_state':u(cover+0x1c),
            'no_advance':b[0x2c8],'no_retreat':b[0x2c9],
            'advance_ratio':struct.unpack_from('<f',b,0x2cc)[0],
            'retreat_ratio':struct.unpack_from('<f',b,0x2d0)[0],
            'tactical_state':struct.unpack_from('<I',b,0x2d4)[0],
            'force_values':struct.unpack_from('<2f',b,0x2c0),
            'target_record':hex(struct.unpack_from('<I',b,0x224)[0]),
            'active_order':hex(struct.unpack_from('<I',b,0x7c)[0])})
    if (u(game+0x58)!=selection or reader.read(selection+4,8)!=struct.pack('<2I',begin,end)):
        raise ValueError('Selection changed during sample')
    return {'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'game_control':hex(game),'direct_control':hex(u(game+0x240)), 'units':records}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--duration',type=float,default=1)
    p.add_argument('--name',default='selected_observation')
    a=p.parse_args()
    if not 0<a.duration<=300: p.error('duration must be 0..300 seconds')
    if not a.name.replace('_','').isalnum():p.error('name must be alphanumeric or underscores')
    OUT.mkdir(exist_ok=True,parents=True)
    reader=Reader(a.pid);im=Image();count=0;errors=0
    try:
        # Verify relevant code identity before using this build-specific map.
        for addr in [0xa642d0,0xa63400,0x916540,0x914ea0]:
            off=im.offset(addr)
            if reader.read(addr,48)!=im.data[off:off+48]:raise ValueError(f'Code mismatch {addr:x}')
        until=time.monotonic()+a.duration
        with (OUT/(a.name+'.jsonl')).open('x',encoding='utf-8') as f:
            while time.monotonic()<until:
                try: record=snapshot(reader)
                except (OSError,ValueError) as exc:
                    record={'error':str(exc)};errors+=1
                f.write(json.dumps(record,allow_nan=False)+'\n');f.flush();count+=1
                if errors>=5:break
                time.sleep(.2)
    finally:reader.close()
    print(json.dumps({'samples':count,'errors':errors,'path':str(OUT/(a.name+'.jsonl'))}))


if __name__=='__main__':main()
