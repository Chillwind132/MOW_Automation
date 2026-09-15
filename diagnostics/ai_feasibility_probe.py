"""Capture AI source evidence and optionally compare bounded live code reads.

Does not inject, write process memory, issue game commands, or modify game assets.
Native byte matches validate reference-code identity, not behavior or unit offsets.
"""
import argparse
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
from pathlib import Path
import struct
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Men of War Assault Squad 2')
MEMBERS = ('properties/human.ext', 'set/small.firearms.accuracy',
           'set/target/human_bullet.inc', 'script/multiplayer/bot.lua')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, default=DEFAULT_GAME)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--base', type=lambda v: int(v, 0))
    args = parser.parse_args()
    if (args.pid is None) != (args.base is None):
        parser.error('--pid and --base must be supplied together')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    out = ROOT / 'validation' / ('ai_feasibility_' + stamp)
    out.mkdir(parents=True)
    report = {'utc': stamp, 'pid': args.pid, 'sources': [], 'native_checks': [],
              'limitations': ['Installed files do not prove runtime load precedence.',
                              'Code matches do not prove active unit state or behavior.',
                              'No behavior changes were applied.']}
    for label, archive in [('base', args.game / 'resource/gamelogic.pak'),
                           ('robz', args.game / 'mods/robz realism mod 1.30.10/resource/gamelogic.pak')]:
        with zipfile.ZipFile(archive) as bundle:
            for member in MEMBERS:
                if member not in bundle.namelist():
                    continue
                raw = bundle.read(member)
                dest = out / label / member
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                report['sources'].append({'archive': str(archive), 'member': member,
                                          'sha256': hashlib.sha256(raw).hexdigest()})
    if args.pid is not None:
        data = (ROOT / 'diagnostics/reference/mowas_2_dumped.exe').read_bytes()
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        if data[pe:pe+4] != b'PE\0\0':
            raise ValueError('Invalid reference PE')
        count = struct.unpack_from('<H', data, pe+6)[0]
        optional_size = struct.unpack_from('<H', data, pe+20)[0]
        preferred = struct.unpack_from('<I', data, pe+24+28)[0]
        if args.base != preferred:
            raise ValueError('Relocated image comparison is not supported')
        sections = []
        for index in range(count):
            offset = pe + 24 + optional_size + index * 40
            virtual_size, rva, raw_size, raw_offset = struct.unpack_from('<IIII', data, offset+8)
            sections.append((rva, raw_size, raw_offset))
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_size_t,
                                             ctypes.POINTER(ctypes.c_size_t)]
        kernel.ReadProcessMemory.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x10, False, args.pid)  # PROCESS_VM_READ only
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            for address, size in [(0x914ea0, 0x144), (0x95b3e0, 0x650), (0xdfc01c, 0x2a)]:
                rva = address - preferred
                matches = [(raw + rva-start) for start, length, raw in sections
                           if start <= rva and rva+size <= start+length]
                if len(matches) != 1:
                    raise ValueError('Reference range is ambiguous or unavailable')
                expected = data[matches[0]:matches[0]+size]
                buffer = ctypes.create_string_buffer(size)
                read = ctypes.c_size_t()
                if not kernel.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(read)):
                    raise ctypes.WinError(ctypes.get_last_error())
                actual = buffer.raw[:read.value]
                report['native_checks'].append({'address': hex(address), 'bytes': size,
                    'read_bytes': read.value, 'matches_reference': actual == expected,
                    'live_sha256': hashlib.sha256(actual).hexdigest(),
                    'reference_sha256': hashlib.sha256(expected).hexdigest()})
        finally:
            kernel.CloseHandle(handle)
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(out), 'sources': len(report['sources']),
                      'native_checks': report['native_checks']}, indent=2))


if __name__ == '__main__':
    main()
