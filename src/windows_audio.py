"""Visible Windows windows and the audio sources Whistle can record."""
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import struct
import sys

@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    app: str
    path: str = ''
    kind: str = 'window'  # window: one app's process tree; system: everything; mic: default microphone

SYSTEM_AUDIO = Window(0, 0, 'All System Audio', 'This PC', kind='system')
MICROPHONE = Window(0, 0, 'Microphone', 'Default input', kind='mic')
BROWSERS = {'chrome', 'msedge', 'firefox', 'brave', 'opera', 'vivaldi', 'arc'}

def is_browser(window):
    return Path(window.path).stem.casefold() in BROWSERS if window.path else window.app.casefold() in BROWSERS

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    dwmapi = ctypes.WinDLL('dwmapi')
    version = ctypes.WinDLL('version')
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindow.argtypes = [wt.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user32.GetWindow.restype = wt.HWND
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    version.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
    version.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT)]
    ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]
    GWL_EXSTYLE, GW_OWNER, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, DWMWA_CLOAKED = -20, 4, 0x80, 0x40000, 14

    @lru_cache(maxsize=256)
    def app_description(path):
        """The friendly product name from an executable's version resource, e.g. 'Google Chrome'."""
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, data):
            return None
        pointer, length = ctypes.c_void_p(), wt.UINT()
        codes = [(0x0409, 0x04B0), (0x0409, 0x04E4), (0x0000, 0x04B0)]
        if version.VerQueryValueW(data, '\\VarFileInfo\\Translation', ctypes.byref(pointer), ctypes.byref(length)) and length.value >= 4:
            codes.insert(0, struct.unpack('<HH', ctypes.string_at(pointer.value, 4)))
        for language, codepage in codes:
            key = f'\\StringFileInfo\\{language:04x}{codepage:04x}\\FileDescription'
            if version.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length)) and length.value > 1:
                text = ctypes.wstring_at(pointer.value, length.value).split('\0', 1)[0].strip()
                if text:
                    return text
        return None

    def _alt_tab_window(hwnd):
        """Match the windows a person sees in Alt+Tab, not hidden helper or cloaked UWP windows."""
        if not user32.IsWindowVisible(hwnd):
            return False
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_TOOLWINDOW:
            return False
        if user32.GetWindow(hwnd, GW_OWNER) and not style & WS_EX_APPWINDOW:
            return False
        cloaked = wt.DWORD()
        if not dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) and cloaked.value:
            return False
        return True

    def window_exists(window):
        if window.kind != 'window':
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(window.hwnd, ctypes.byref(pid))
        return bool(user32.IsWindow(window.hwnd)) and pid.value == window.pid

    def list_windows():
        windows = []
        @ENUMPROC
        def visit(hwnd, unused):
            if not _alt_tab_window(hwnd):
                return True
            size = user32.GetWindowTextLengthW(hwnd)
            if not size:
                return True
            title = ctypes.create_unicode_buffer(size + 1)
            user32.GetWindowTextW(hwnd, title, size + 1)
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid() or title.value == 'Program Manager':
                return True
            app, path = f'Process {pid.value}', ''
            handle = kernel32.OpenProcess(0x1000, False, pid.value)
            if handle:
                name = ctypes.create_unicode_buffer(32768)
                length = wt.DWORD(len(name))
                if kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
                    path = name.value
                    try:
                        app = app_description(path) or Path(path).stem
                    except OSError:
                        app = Path(path).stem
                kernel32.CloseHandle(handle)
            windows.append(Window(int(hwnd), pid.value, title.value, app, path))
            return True
        user32.EnumWindows(visit, 0)
        return sorted(windows, key=lambda item: (item.app.casefold(), item.title.casefold()))
else:
    # Capture is Windows-only; other platforms can still browse, import, and transcribe files.
    def window_exists(window):
        return window.kind != 'window'

    def list_windows():
        return []
