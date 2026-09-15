"""Bounded external scan for validated native WAV sample-data objects."""
import _bootstrap  # Set up imports for direct CLI execution.
import argparse
import json
from pathlib import Path
import struct
import time
import pymem
from headless_host import find_process, process_identity, SUPPORTED_SHA256


def scan(address_file, output, seconds=20):
    pid = find_process()
    identity = process_identity(pid)
    if identity['sha256'] != SUPPORTED_SHA256:
        raise RuntimeError('Unsupported executable')
    with address_file.open(encoding='utf-8') as stream:
        latest = None
        for line in stream:
            try:
                latest = json.loads(line)
            except ValueError:
                pass
    if not latest or latest['pid'] != pid:
        raise RuntimeError('Address snapshot must belong to the live process')
    pm = pymem.Pymem(pid)
    started = time.time()
    deadline = time.monotonic() + seconds
    result = {'identity': identity, 'started': started, 'address_snapshot_time': latest['time'],
              'objects': [], 'trace_record_candidates': [], 'bytes_scanned': 0, 'read_errors': 0, 'completed': True,
              'limitation': 'Non-atomic scan of snapshot regions. Vtable, plausible reference count and RIFF/WAVE header validate candidates, not lifetime or ownership. Misses non-WAV data.'}
    seen = set()
    try:
        for region in latest['regions']:
            if region['state'] != 0x1000 or region['type'] != 0x20000 or region['protect'] & 0x101:
                continue
            for base in range(region['base'], region['base'] + region['size'], 1024*1024):
                if time.monotonic() >= deadline:
                    result['completed'] = False
                    break
                length = min(1024*1024+3, region['base']+region['size']-base)
                try:
                    data = pm.read_bytes(base, length)
                except Exception:
                    result['read_errors'] += 1
                    continue
                result['bytes_scanned'] += length
                # Native tracer Entry: pointer,size,birth,stack[6]. This locates
                # candidate copies in tracer storage, not authoritative lifetimes.
                pos = data.find(b'\x0a\xe5\x50\x00\xa6\x43\x5c\x00\x29\x3c\x5c\x00')
                while pos >= 0:
                    try:
                        pointer, size, birth = struct.unpack('<3I', pm.read_bytes(base+pos-12, 12))
                        if pointer and 65536 <= size <= 128*1024*1024 and birth < 1000:
                            candidate = {'record': hex(base+pos-12), 'buffer': hex(pointer),
                                         'bytes': size, 'birth': birth}
                            try:
                                header = pm.read_bytes(pointer, 12)
                                candidate['is_riff_wave'] = header[:4] == b'RIFF' and header[8:12] == b'WAVE'
                            except Exception:
                                candidate['buffer_unreadable'] = True
                            result['trace_record_candidates'].append(candidate)
                    except Exception:
                        pass
                    pos = data.find(b'\x0a\xe5\x50\x00\xa6\x43\x5c\x00\x29\x3c\x5c\x00', pos+4)
                pos = data.find(b'\x14\xac\xda\x00')
                while pos >= 0:
                    obj = base+pos
                    if obj % 4 == 0 and obj not in seen:
                        seen.add(obj)
                        try:
                            words = struct.unpack('<14I', pm.read_bytes(obj, 56))
                            if 0 < words[1] < 10000 and words[2] & 1 and words[3]:
                                header = pm.read_bytes(words[3], 12)
                                if header[:4] == b'RIFF' and header[8:12] == b'WAVE':
                                    result['objects'].append({'address': hex(obj), 'references': words[1],
                                        'flags': words[2], 'buffer': hex(words[3]),
                                        'riff_bytes': struct.unpack_from('<I', header, 4)[0]+8})
                        except Exception:
                            pass
                    pos = data.find(b'\x14\xac\xda\x00', pos+4)
            if not result['completed']:
                break
    finally:
        pm.close_process()
    result['finished'] = time.time()
    result['unique_buffers'] = len({x['buffer'] for x in result['objects']})
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('address_file', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=float, default=20)
    args = parser.parse_args()
    result = scan(args.address_file, args.output, args.seconds)
    print(json.dumps({k: v for k, v in result.items() if k not in ('objects', 'identity', 'trace_record_candidates')}, indent=2))
