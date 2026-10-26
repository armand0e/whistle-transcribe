"""Visible Windows windows and process-tree loopback transport."""
import ctypes
from ctypes import wintypes as wt
from dataclasses import dataclass
import os
from pathlib import Path

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]

@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    app: str

def window_exists(window):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(window.hwnd, ctypes.byref(pid))
    return bool(user32.IsWindow(window.hwnd)) and pid.value == window.pid

def list_windows():
    windows = []
    @ENUMPROC
    def visit(hwnd, unused):
        if not user32.IsWindowVisible(hwnd):
            return True
        size = user32.GetWindowTextLengthW(hwnd)
        if not size:
            return True
        title = ctypes.create_unicode_buffer(size + 1)
        user32.GetWindowTextW(hwnd, title, size + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return True
        app = f'Process {pid.value}'
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if handle:
            name = ctypes.create_unicode_buffer(32768)
            length = wt.DWORD(len(name))
            if kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
                app = Path(name.value).stem
            kernel32.CloseHandle(handle)
        windows.append(Window(int(hwnd), pid.value, title.value, app))
        return True
    user32.EnumWindows(visit, 0)
    return sorted(windows, key=lambda item: (item.app.casefold(), item.title.casefold()))
