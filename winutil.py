import ctypes
import ctypes.wintypes as wt
import logging
import struct
import time
import winreg

log = logging.getLogger("povtoritel")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
dxgi = ctypes.windll.dxgi
gdi32 = ctypes.windll.gdi32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_HOTKEY = 0x0312
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
MSG_RELOAD = WM_APP + 1
MSG_SAVE = WM_APP + 2
MSG_QUIT = WM_APP + 3
MSG_SETTINGS = WM_APP + 4
MSG_TOAST = WM_APP + 5
MSG_TRAY = WM_APP + 10
WM_PAINT = 0x000F

MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4}
MOD_NOREPEAT = 0x4000
HOTKEY_ID = 1
WINDOW_CLASS = "PovtoritelTrayWindow"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Povtoritel"

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, wt.HMENU,
                                   wt.HINSTANCE, wt.LPVOID]
user32.FindWindowW.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, ctypes.c_uint, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wt.HMENU, ctypes.c_uint, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, ctypes.c_uint,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, ctypes.c_uint, wt.LPVOID]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.RegisterWindowMessageW.restype = ctypes.c_uint
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_uint]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
gdi32.D3DKMTSetProcessSchedulingPriorityClass.argtypes = [wt.HANDLE, ctypes.c_int]
gdi32.D3DKMTSetProcessSchedulingPriorityClass.restype = ctypes.c_int32

PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
ABOVE_NORMAL_CLASS = 0x00008000
HIGH_CLASS = 0x00000080
GPU_HIGH = 4
GPU_REALTIME = 5


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def list_processes():
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)
    procs = []
    if not snap or snap == wt.HANDLE(-1).value:
        return procs
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            procs.append((e.th32ProcessID, e.th32ParentProcessID,
                          e.szExeFile.lower()))
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return procs


def find_audio_root(tokens):
    procs = list_processes()
    exe_by_pid = {p: x for p, _pp, x in procs}
    matches = [(p, pp, x) for p, pp, x in procs
               if any(t in x for t in tokens)]
    if not matches:
        return None, None
    match_pids = {p for p, _pp, _x in matches}
    roots = [(p, x) for p, pp, x in matches if pp not in match_pids]
    if not roots:
        roots = [(matches[0][0], matches[0][2])]
    kids = {}
    for p, pp, _x in matches:
        kids[pp] = kids.get(pp, 0) + 1
    roots.sort(key=lambda r: -kids.get(r[0], 0))
    return roots[0]


kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]


def pid_alive(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = wt.DWORD()
    kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return code.value == 259


def boost_process(pid, gpu_level=GPU_HIGH, cpu_class=ABOVE_NORMAL_CLASS):
    h = kernel32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION,
                             False, pid)
    if not h:
        return False
    ok = False
    try:
        if cpu_class:
            kernel32.SetPriorityClass(h, cpu_class)
        for _ in range(60):
            st = gdi32.D3DKMTSetProcessSchedulingPriorityClass(h, gpu_level) & 0xFFFFFFFF
            if st == 0:
                ok = True
                break
            time.sleep(0.05)
    finally:
        kernel32.CloseHandle(h)
    return ok


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD),
                ("hWnd", wt.HWND),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", wt.HICON),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", wt.DWORD),
                ("dwStateMask", wt.DWORD),
                ("szInfo", ctypes.c_wchar * 256),
                ("uTimeout", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wt.DWORD),
                ("guidItem", ctypes.c_ubyte * 16),
                ("hBalloonIcon", wt.HICON)]


shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
NIIF_INFO = 1


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        try:
            user32.SetProcessDPIAware()
        except OSError:
            pass


def desktop_locked():
    user32.OpenInputDesktop.restype = wt.HANDLE
    h = user32.OpenInputDesktop(0, False, 0x0100)
    if h:
        user32.CloseDesktop(h)
        return False
    return True


def error_box(title, text):
    user32.MessageBoxW(None, text, title, 0x10)


_mutex = None


def single_instance(name):
    global _mutex
    _mutex = kernel32.CreateMutexW(None, True, name)
    return kernel32.GetLastError() != 183


def post_to_running(msg):
    hwnd = user32.FindWindowW(WINDOW_CLASS, None)
    if not hwnd:
        return False
    user32.PostMessageW(hwnd, msg, 0, 0)
    return True


def set_autostart(cmd):
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    key.Close()


def remove_autostart():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, APP_NAME)
        key.Close()
    except FileNotFoundError:
        pass


def get_autostart():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        key.Close()
        return val
    except FileNotFoundError:
        return None


def write_ico(path, rgb):
    size = 32
    px = bytearray()
    c = (size - 1) / 2
    r = 12.5
    for y in range(size - 1, -1, -1):
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            a = max(0, min(255, int((r - d) * 255)))
            px += bytes((rgb[2], rgb[1], rgb[0], a))
    mask = bytes(size * 4)
    bih = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      len(px) + len(mask), 0, 0, 0, 0)
    img = bih + bytes(px) + mask
    hdr = struct.pack("<HHH", 0, 1, 1) + struct.pack(
        "<BBBBHHII", size, size, 0, 0, 1, 32, len(img), 22)
    with open(path, "wb") as f:
        f.write(hdr + img)


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16),
                ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        p = s.split("-")
        self.d1, self.d2, self.d3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
        self.d4 = (ctypes.c_ubyte * 8)(*bytes.fromhex(p[3] + p[4]))


class _ADAPTER_DESC(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint),
                ("DeviceId", ctypes.c_uint), ("SubSysId", ctypes.c_uint),
                ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", ctypes.c_int64)]


class _OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", ctypes.c_wchar * 32), ("Coords", wt.RECT),
                ("Attached", ctypes.c_int), ("Rotation", ctypes.c_int),
                ("Monitor", ctypes.c_void_p)]


def _vt(obj, idx, restype, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[idx])


def _release(obj):
    _vt(obj, 2, ctypes.c_ulong)(obj)


def list_outputs():
    res = []
    fac = ctypes.c_void_p()
    iid = _GUID("7b7166ec-21c7-44ae-b21a-c9ae321ae369")
    if dxgi.CreateDXGIFactory(ctypes.byref(iid), ctypes.byref(fac)) != 0:
        return res
    ai = 0
    while True:
        ad = ctypes.c_void_p()
        if _vt(fac, 7, ctypes.c_int32, ctypes.c_uint,
               ctypes.POINTER(ctypes.c_void_p))(fac, ai, ctypes.byref(ad)) != 0:
            break
        d = _ADAPTER_DESC()
        _vt(ad, 8, ctypes.c_int32, ctypes.POINTER(_ADAPTER_DESC))(ad, ctypes.byref(d))
        oi = 0
        while True:
            out = ctypes.c_void_p()
            if _vt(ad, 7, ctypes.c_int32, ctypes.c_uint,
                   ctypes.POINTER(ctypes.c_void_p))(ad, oi, ctypes.byref(out)) != 0:
                break
            od = _OUTPUT_DESC()
            _vt(out, 7, ctypes.c_int32, ctypes.POINTER(_OUTPUT_DESC))(out, ctypes.byref(od))
            if od.Attached:
                res.append({"adapter": ai, "output": oi,
                            "gpu": d.Description.strip(),
                            "vendor": hex(d.VendorId),
                            "w": od.Coords.right - od.Coords.left,
                            "h": od.Coords.bottom - od.Coords.top,
                            "x": od.Coords.left, "y": od.Coords.top,
                            "primary": od.Coords.left == 0 and od.Coords.top == 0})
            _release(out)
            oi += 1
        _release(ad)
        ai += 1
    _release(fac)
    return res


class Tray:
    def __init__(self, tip, icon_path, handler):
        self.handler = handler
        self._icons = {}
        self._tip = tip
        hinst = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        self._taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = WINDOW_CLASS
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, WINDOW_CLASS, "Povtoritel", 0,
                                           0, 0, 0, 0, None, None, hinst, None)
        self._nid = NOTIFYICONDATAW()
        self._nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self._nid.hWnd = self.hwnd
        self._nid.uID = 1
        self._nid.uCallbackMessage = MSG_TRAY
        self._nid.hIcon = self._load_icon(icon_path)
        self._nid.szTip = tip[:127]
        self._add_icon()

    def _add_icon(self):
        import time
        for _ in range(5):
            self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)):
                return
            time.sleep(2)
        log.error("tray icon add failed")

    def _load_icon(self, path):
        p = str(path)
        if p not in self._icons:
            self._icons[p] = user32.LoadImageW(None, p, 1, 0, 0, 0x10 | 0x40)
        return self._icons[p]

    def set_icon(self, path):
        self._nid.hIcon = self._load_icon(path)
        self._nid.uFlags = NIF_ICON
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def set_tip(self, tip):
        self._tip = tip
        self._nid.szTip = tip[:127]
        self._nid.uFlags = NIF_TIP
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def balloon(self, title, text):
        self._nid.szInfoTitle = title[:63]
        self._nid.szInfo = text[:255]
        self._nid.dwInfoFlags = NIIF_INFO
        self._nid.uTimeout = 5000
        self._nid.uFlags = NIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def popup(self, items):
        menu = user32.CreatePopupMenu()
        for it in items:
            if it is None:
                user32.AppendMenuW(menu, 0x800, 0, None)
            else:
                mid, label, checked, enabled = it
                flags = (0x8 if checked else 0) | (0 if enabled else 0x3)
                user32.AppendMenuW(menu, flags, mid, label)
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, 0x102, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)
        return cmd

    def register_hotkey(self, mods, vk):
        for hid in getattr(self, "_hk_ids", []):
            user32.UnregisterHotKey(self.hwnd, hid)
        self._hk_ids = []
        base = 0
        for m in mods:
            base |= MODS.get(m, 0)
        extras = [v for v in MODS.values() if not base & v]
        ok = False
        hid = HOTKEY_ID
        # extra held modifiers tolerated
        for n in range(1 << len(extras)):
            val = base
            for i, ev in enumerate(extras):
                if n & (1 << i):
                    val |= ev
            if user32.RegisterHotKey(self.hwnd, hid, val | MOD_NOREPEAT, vk):
                self._hk_ids.append(hid)
                if n == 0:
                    ok = True
            elif n == 0:
                log.warning("hotkey register failed vk=%#x mods=%#x", vk, val)
            else:
                log.info("hotkey combo taken elsewhere, mods=%#x", val)
            hid += 1
        return ok

    def start_timer(self, ms):
        user32.SetTimer(self.hwnd, 1, ms, None)

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_HOTKEY:
                self.handler("save", None)
                return 0
            if msg == MSG_TRAY:
                ev = lp & 0xFFFF
                if ev in (WM_LBUTTONUP, WM_RBUTTONUP):
                    self.handler("menu", None)
                elif ev == WM_LBUTTONDBLCLK:
                    self.handler("settings", None)
                return 0
            if msg == MSG_RELOAD:
                self.handler("reload", None)
                return 0
            if msg == MSG_SAVE:
                self.handler("save", None)
                return 0
            if msg == MSG_QUIT:
                self.handler("quit", None)
                return 0
            if msg == MSG_SETTINGS:
                self.handler("settings", None)
                return 0
            if msg == WM_TIMER:
                self.handler("timer", None)
                return 0
            if msg == MSG_TOAST:
                self.handler("toast", None)
                return 0
            if msg == self._taskbar_msg:
                self._add_icon()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("wndproc error")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def run(self):
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def destroy(self):
        for hid in getattr(self, "_hk_ids", [HOTKEY_ID]):
            user32.UnregisterHotKey(self.hwnd, hid)
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        user32.DestroyWindow(self.hwnd)


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
                ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


user32.BeginPaint.restype = wt.HDC
user32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(wt.RECT), ctypes.c_uint]
user32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
user32.SetWindowRgn.argtypes = [wt.HWND, wt.HRGN, wt.BOOL]
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF,
                                              ctypes.c_ubyte, wt.DWORD]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
gdi32.CreateSolidBrush.restype = wt.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wt.COLORREF]
gdi32.CreateRoundRectRgn.restype = wt.HRGN
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateFontW.restype = wt.HFONT
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.GetStockObject.restype = wt.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
gdi32.Ellipse.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int]


def _rgb(r, g, b):
    return r | (g << 8) | (b << 16)


TOAST_CLASS = "PovtoritelToast"
DT_FLAGS = 0x20 | 0x800 | 0x8000  # SINGLELINE|NOPREFIX|END_ELLIPSIS


class Toast:
    def __init__(self):
        self._title = ""
        self._body = ""
        self._ok = True
        self._alpha = 235
        dpi = 96
        try:
            dpi = user32.GetDpiForSystem() or 96
        except Exception:
            pass
        self.s = dpi / 96.0
        self.W = int(360 * self.s)
        self.H = int(92 * self.s)
        self.M = int(24 * self.s)
        self.pad = int(20 * self.s)
        self.dot = int(13 * self.s)
        r = int(18 * self.s)
        self._bg = gdi32.CreateSolidBrush(_rgb(28, 28, 42))
        self._ok_brush = gdi32.CreateSolidBrush(_rgb(70, 210, 120))
        self._err_brush = gdi32.CreateSolidBrush(_rgb(232, 84, 84))
        self._nullpen = gdi32.GetStockObject(8)  # NULL_PEN
        self._title_col = _rgb(240, 240, 246)
        self._body_col = _rgb(176, 176, 196)
        self._title_font = self._font(int(18 * self.s), 700)
        self._body_font = self._font(int(15 * self.s), 400)
        hinst = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = TOAST_CLASS
        user32.RegisterClassW(ctypes.byref(wc))
        exstyle = 0x80000 | 0x8 | 0x80 | 0x8000000 | 0x20  # LAYERED|TOPMOST|TOOLWINDOW|NOACTIVATE|TRANSPARENT
        self.hwnd = user32.CreateWindowExW(exstyle, TOAST_CLASS, "Povtoritel",
                                           0x80000000, 0, 0, self.W, self.H,
                                           None, None, hinst, None)
        rgn = gdi32.CreateRoundRectRgn(0, 0, self.W + 1, self.H + 1, r * 2, r * 2)
        user32.SetWindowRgn(self.hwnd, rgn, False)
        try:
            user32.SetWindowDisplayAffinity(self.hwnd, 0x11)  # EXCLUDEFROMCAPTURE
        except Exception:
            pass
        user32.SetLayeredWindowAttributes(self.hwnd, 0, self._alpha, 0x2)

    def _font(self, px, weight):
        return gdi32.CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0,
                                 "Segoe UI")

    def show(self, title, body, ok=True):
        self._title = title
        self._body = body
        self._ok = ok
        self._alpha = 235
        sw = user32.GetSystemMetrics(0)
        x = sw - self.W - self.M
        user32.KillTimer(self.hwnd, 1)
        user32.KillTimer(self.hwnd, 2)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, self._alpha, 0x2)
        user32.SetWindowPos(self.hwnd, -1, x, self.M, self.W, self.H, 0x10 | 0x40)
        user32.InvalidateRect(self.hwnd, None, True)
        user32.SetTimer(self.hwnd, 1, 1800, None)

    def _paint(self):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        rc = wt.RECT(0, 0, self.W, self.H)
        user32.FillRect(hdc, ctypes.byref(rc), self._bg)
        oldpen = gdi32.SelectObject(hdc, self._nullpen)
        brush = self._ok_brush if self._ok else self._err_brush
        oldbrush = gdi32.SelectObject(hdc, brush)
        cy = self.H // 2
        gdi32.Ellipse(hdc, self.pad, cy - self.dot, self.pad + self.dot * 2,
                      cy + self.dot)
        gdi32.SelectObject(hdc, oldbrush)
        gdi32.SelectObject(hdc, oldpen)
        gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
        tx = self.pad + self.dot * 2 + self.pad // 2
        gdi32.SelectObject(hdc, self._title_font)
        gdi32.SetTextColor(hdc, self._title_col)
        tr = wt.RECT(tx, int(16 * self.s), self.W - self.pad, int(48 * self.s))
        user32.DrawTextW(hdc, self._title, -1, ctypes.byref(tr), DT_FLAGS)
        gdi32.SelectObject(hdc, self._body_font)
        gdi32.SetTextColor(hdc, self._body_col)
        br = wt.RECT(tx, int(47 * self.s), self.W - self.pad, self.H - int(12 * self.s))
        user32.DrawTextW(hdc, self._body, -1, ctypes.byref(br), DT_FLAGS)
        user32.EndPaint(self.hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_PAINT:
                self._paint()
                return 0
            if msg == WM_TIMER:
                if wp == 1:
                    user32.KillTimer(hwnd, 1)
                    self._alpha = 235
                    user32.SetTimer(hwnd, 2, 22, None)
                    return 0
                if wp == 2:
                    self._alpha -= 26
                    if self._alpha <= 0:
                        user32.KillTimer(hwnd, 2)
                        user32.ShowWindow(hwnd, 0)  # SW_HIDE
                    else:
                        user32.SetLayeredWindowAttributes(hwnd, 0, self._alpha, 0x2)
                    return 0
        except Exception:
            log.exception("toast wndproc error")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)
