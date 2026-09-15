"""Read-only process lifetime evidence, retained even after the PID exits."""
import ctypes
from ctypes import wintypes


class ProcessDiagnostics:
    def __init__(self, pid):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def snapshot(self):
        if not self.handle:
            return {'available': False}
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result == 0x102:
            return {'alive': True}
        if result != 0:
            return {'error': 'process wait failed', 'winerror': ctypes.get_last_error()}
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return {'alive': False, 'winerror': ctypes.get_last_error()}
        return {'alive': False, 'exit_code': code.value, 'exit_code_hex': f'0x{code.value:08X}'}

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
