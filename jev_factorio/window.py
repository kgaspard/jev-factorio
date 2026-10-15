"""Win32 helpers: find the Factorio window, its client area, focus and the kill switch."""

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from . import config

# Must run before any coordinates are read, otherwise screenshot and mouse coordinates
# disagree on scaled displays.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
except OSError:
    ctypes.windll.user32.SetProcessDPIAware()

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    def as_mss(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def _process_exe(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return Path(buf.value).name
    finally:
        kernel32.CloseHandle(handle)


def _is_factorio(hwnd: int) -> bool:
    return _process_exe(hwnd).lower() == config.FACTORIO_EXE


def find_factorio() -> int | None:
    """Handle of the visible top-level Factorio window, or None."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _is_factorio(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def client_rect(hwnd: int) -> Rect:
    """The game's drawable area (no title bar or borders) in screen pixels."""
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return Rect(origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top)


def place_client(hwnd: int, width: int, height: int, left: int = 0, top: int = 0):
    """Move/resize the window so its client area is exactly width x height at (left, top)."""
    GWL_STYLE, GWL_EXSTYLE = -16, -20
    rect = wintypes.RECT(left, top, left + width, top + height)
    user32.AdjustWindowRectEx(
        ctypes.byref(rect),
        user32.GetWindowLongW(hwnd, GWL_STYLE),
        False,
        user32.GetWindowLongW(hwnd, GWL_EXSTYLE),
    )
    # The outer frame can extend left of/above the screen; shift so the title bar stays visible.
    dx, dy = max(0, -rect.left), max(0, -rect.top)
    SWP_NOZORDER = 0x0004
    user32.SetWindowPos(
        hwnd,
        0,
        rect.left + dx,
        rect.top + dy,
        rect.right - rect.left,
        rect.bottom - rect.top,
        SWP_NOZORDER,
    )


def factorio_is_active() -> bool:
    return _is_factorio(user32.GetForegroundWindow())


def foreground_owner() -> str:
    """Which window has focus, for logging: 'exe: title'."""
    hwnd = user32.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    # Titles can hold symbols (e.g. a spinner) that a cp1252 console cannot print.
    safe = title.value.encode("ascii", "replace").decode()
    return f"{_process_exe(hwnd) or '?'}: {safe}"


def focus(hwnd: int) -> bool:
    """Bring Factorio to the front. Windows only lets the process that has focus hand it over,
    but a synthetic Alt tap counts as user input and lifts that lock."""
    VK_MENU, KEYEVENTF_KEYUP, SW_RESTORE = 0x12, 0x0002, 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    return factorio_is_active()


def kill_switch_pressed() -> bool:
    return bool(user32.GetAsyncKeyState(config.KILL_SWITCH_VK) & 0x8000)
