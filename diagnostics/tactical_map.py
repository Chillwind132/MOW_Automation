"""Local reverse-engineering helpers; all target-process access is read-only."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'validation/tactical_mapping_20260907'


class Image:
    def __init__(self):
        self.data = (ROOT / 'diagnostics/reference/mowas_2_dumped.exe').read_bytes()
        pe = self.u32(60)
        n = struct.unpack_from('<H', self.data, pe+6)[0]
        size = struct.unpack_from('<H', self.data, pe+20)[0]
        self.sections = [struct.unpack_from('<IIII', self.data, pe+24+size+i*40+8) for i in range(n)]

    def u32(self, off):
        return struct.unpack_from('<I', self.data, off)[0]

    def offset(self, va):
        for _, start, size, raw in self.sections:
            if start+0x400000 <= va < start+0x400000+size:
                return raw+va-start-0x400000
        raise ValueError(hex(va))

    def va(self, off):
        for _, start, size, raw in self.sections:
            if raw <= off < raw+size:
                return 0x400000+start+off-raw
        return None

    def refs(self, value):
        return [self.va(m.start()) for m in re.finditer(re.escape(struct.pack('<I', value)), self.data) if self.va(m.start())]


class Reader:
    def __init__(self, pid):
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.ReadProcessMemory.argtypes = [w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
        self.k.ReadProcessMemory.restype = w.BOOL
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.OpenProcess(0x410, False, pid)
        if not self.handle: raise c.WinError(c.get_last_error())

    def read(self, va, size):
        buf = c.create_string_buffer(size)
        got = c.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, va, buf, size, c.byref(got)) or got.value != size:
            raise OSError(f'Read failed at {va:x}: {c.get_last_error()}')
        return buf.raw

    def close(self):
        self.k.CloseHandle(self.handle)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('decompile'); d.add_argument('name'); d.add_argument('addresses', nargs='+')
    r = sub.add_parser('refs'); r.add_argument('addresses', nargs='+')
    r = sub.add_parser('read'); r.add_argument('pid',type=int); r.add_argument('addresses',nargs='+'); r.add_argument('--size',type=lambda x:int(x,0),default=128)
    args = p.parse_args(); OUT.mkdir(exist_ok=True,parents=True)
    if args.command == 'decompile':
        if not re.fullmatch(r'[A-Za-z0-9_]+', args.name):
            p.error('name must be alphanumeric or underscores')
        addresses = [('x' if address.startswith('x') else '') +
                     format(int(address[1:] if address.startswith('x') else address, 16), 'x')
                     for address in args.addresses]
        command = [str(ROOT.parent/'ghidra_12.0.3_PUBLIC/support/analyzeHeadless.bat'),
                   str(ROOT/'archive/reverse_engineering/ghidra_project'),'mow_dumped',
                   '-process','mowas_2_dumped.exe','-readOnly','-noanalysis',
                   '-scriptPath',str(ROOT/'diagnostics'),
                   '-postScript','AnalyzeTactical.java',str(OUT/(args.name+'.txt')),*addresses]
        with (OUT/(args.name+'.log')).open('w') as f:
            result = subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
        print(json.dumps({'exit_code':result.returncode,'output':str(OUT/(args.name+'.txt'))}))
        if result.returncode: raise SystemExit(result.returncode)
        output = OUT / (args.name + '.txt')
        if not output.exists() or not output.read_text().strip():
            raise RuntimeError('Ghidra produced no analysis; inspect the saved log')
    elif args.command == 'refs':
        image=Image()
        for address in args.addresses:
            va=int(address,16); print(address,[hex(a) for a in image.refs(va)])
    else:
        reader=Reader(args.pid)
        try:
            for address in args.addresses:
                va=int(address,16); b=reader.read(va,args.size)
                print(address,[(hex(i),hex(struct.unpack_from('<I',b,i)[0]),round(struct.unpack_from('<f',b,i)[0],4)) for i in range(0,len(b)-3,4)])
        finally: reader.close()


if __name__ == '__main__': main()
