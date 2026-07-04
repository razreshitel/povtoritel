import ctypes
import logging
import threading

log = logging.getLogger("povtoritel")

ole32 = ctypes.windll.ole32
mmdevapi = ctypes.windll.mmdevapi
CLSCTX_ALL = 0x17
LOOPBACK = 0x00020000
EVENTCALLBACK = 0x00040000
SILENT_FLAG = 0x2
VT_LPWSTR = 31
VT_BLOB = 65
PROC_LOOPBACK_PATH = "VAD\\Process_Loopback"


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16),
                ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s=None):
        if s:
            p = s.split("-")
            self.d1, self.d2, self.d3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
            self.d4 = (ctypes.c_ubyte * 8)(*bytes.fromhex(p[3] + p[4]))


CLSID_ENUM = GUID("bcde0395-e52f-467c-8e3d-c4579291692e")
IID_ENUM = GUID("a95664d2-9614-4f35-a746-de8db63617e6")
IID_CLIENT = GUID("1cb9ad4c-dbfa-4c32-b178-c2f568a703b2")
IID_CAPTURE = GUID("c8adbd64-e71e-48a0-a4de-185c395cd317")


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_ushort), ("nChannels", ctypes.c_ushort),
                ("nSamplesPerSec", ctypes.c_uint), ("nAvgBytesPerSec", ctypes.c_uint),
                ("nBlockAlign", ctypes.c_ushort), ("wBitsPerSample", ctypes.c_ushort),
                ("cbSize", ctypes.c_ushort)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("pwszVal", ctypes.c_void_p), ("pad", ctypes.c_int64)]


def _vt(obj, idx, restype, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[idx])


def _release(obj):
    if obj:
        _vt(obj, 2, ctypes.c_ulong)(obj)


def com_init():
    ole32.CoInitializeEx(None, 0)


def _enumerator():
    enum = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ENUM), None, CLSCTX_ALL,
                                ctypes.byref(IID_ENUM), ctypes.byref(enum))
    if hr != 0:
        raise OSError(f"CoCreateInstance {hr & 0xFFFFFFFF:#x}")
    return enum


def list_mics():
    com_init()
    enum = _enumerator()
    out = []
    try:
        coll = ctypes.c_void_p()
        hr = _vt(enum, 3, ctypes.c_int32, ctypes.c_int, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_void_p))(enum, 1, 1, ctypes.byref(coll))
        if hr != 0:
            return out
        n = ctypes.c_uint()
        _vt(coll, 3, ctypes.c_int32, ctypes.POINTER(ctypes.c_uint))(
            coll, ctypes.byref(n))
        for i in range(n.value):
            dev = ctypes.c_void_p()
            if _vt(coll, 4, ctypes.c_int32, ctypes.c_uint,
                   ctypes.POINTER(ctypes.c_void_p))(coll, i, ctypes.byref(dev)) != 0:
                continue
            id_ptr = ctypes.c_void_p()
            _vt(dev, 5, ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p))(
                dev, ctypes.byref(id_ptr))
            dev_id = ctypes.wstring_at(id_ptr) if id_ptr else ""
            if id_ptr:
                ole32.CoTaskMemFree(id_ptr)
            name = dev_id
            store = ctypes.c_void_p()
            if _vt(dev, 4, ctypes.c_int32, ctypes.c_uint,
                   ctypes.POINTER(ctypes.c_void_p))(dev, 0, ctypes.byref(store)) == 0:
                key = PROPERTYKEY()
                key.fmtid = GUID("a45c254e-df1c-4efd-8020-67d146a850e0")
                key.pid = 14
                pv = PROPVARIANT()
                if _vt(store, 5, ctypes.c_int32, ctypes.POINTER(PROPERTYKEY),
                       ctypes.POINTER(PROPVARIANT))(store, ctypes.byref(key),
                                                    ctypes.byref(pv)) == 0:
                    if pv.vt == VT_LPWSTR and pv.pwszVal:
                        name = ctypes.wstring_at(pv.pwszVal)
                    ole32.PropVariantClear(ctypes.byref(pv))
                _release(store)
            out.append({"id": dev_id, "name": name})
            _release(dev)
        _release(coll)
    finally:
        _release(enum)
    return out


IID_IUNKNOWN = GUID("00000000-0000-0000-c000-000000000046")
IID_COMPLETION = GUID("41d949ab-9862-444a-80f6-c261334da5eb")
IID_AGILE = GUID("94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90")
IID_SESSION_MGR2 = GUID("77aa99a0-1bd6-484f-8bc7-2c654c9a9b6f")
IID_SESSION_CTL2 = GUID("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d")


def list_audio_sessions():
    com_init()
    enum = _enumerator()
    out = []
    dev = ctypes.c_void_p()
    mgr = ctypes.c_void_p()
    se = ctypes.c_void_p()
    try:
        if _vt(enum, 4, ctypes.c_int32, ctypes.c_int, ctypes.c_int,
               ctypes.POINTER(ctypes.c_void_p))(enum, 0, 0, ctypes.byref(dev)) != 0:
            return out
        if _vt(dev, 3, ctypes.c_int32, ctypes.POINTER(GUID), ctypes.c_uint,
               ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                dev, ctypes.byref(IID_SESSION_MGR2), CLSCTX_ALL, None,
                ctypes.byref(mgr)) != 0:
            return out
        if _vt(mgr, 5, ctypes.c_int32,
               ctypes.POINTER(ctypes.c_void_p))(mgr, ctypes.byref(se)) != 0:
            return out
        n = ctypes.c_int()
        _vt(se, 3, ctypes.c_int32, ctypes.POINTER(ctypes.c_int))(
            se, ctypes.byref(n))
        for i in range(n.value):
            ctl = ctypes.c_void_p()
            if _vt(se, 4, ctypes.c_int32, ctypes.c_int,
                   ctypes.POINTER(ctypes.c_void_p))(se, i, ctypes.byref(ctl)) != 0:
                continue
            st = ctypes.c_int(0)
            _vt(ctl, 3, ctypes.c_int32, ctypes.POINTER(ctypes.c_int))(
                ctl, ctypes.byref(st))
            pid = ctypes.c_uint(0)
            is_sys = False
            ctl2 = ctypes.c_void_p()
            qi = _vt(ctl, 0, ctypes.c_int32, ctypes.POINTER(GUID),
                     ctypes.POINTER(ctypes.c_void_p))
            if qi(ctl, ctypes.byref(IID_SESSION_CTL2), ctypes.byref(ctl2)) == 0:
                _vt(ctl2, 14, ctypes.c_int32, ctypes.POINTER(ctypes.c_uint))(
                    ctl2, ctypes.byref(pid))
                is_sys = _vt(ctl2, 15, ctypes.c_int32)(ctl2) == 0
                _release(ctl2)
            _release(ctl)
            out.append((pid.value, st.value, is_sys))
        return out
    finally:
        for o in (se, mgr, dev, enum):
            _release(o)

_QI_T = ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(GUID),
                            ctypes.POINTER(ctypes.c_void_p))
_REF_T = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_DONE_T = ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p)


class _HandlerVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _QI_T), ("AddRef", _REF_T),
                ("Release", _REF_T), ("ActivateCompleted", _DONE_T)]


class _HandlerObj(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_HandlerVtbl))]


class _ProcLoopbackParams(ctypes.Structure):
    _fields_ = [("TargetProcessId", ctypes.c_uint32),
                ("ProcessLoopbackMode", ctypes.c_uint32)]


class _ActivationParams(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_uint32),
                ("ProcessLoopbackParams", _ProcLoopbackParams)]


class _PropVariantBlob(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("cbSize", ctypes.c_ulong), ("pBlobData", ctypes.c_void_p)]


def _guid_eq(a, b):
    return bytes(a) == bytes(b)


def _activate_process_client(pid):
    done = threading.Event()

    def qi(this, riid, ppv):
        if _guid_eq(riid.contents, IID_IUNKNOWN) or \
           _guid_eq(riid.contents, IID_COMPLETION) or \
           _guid_eq(riid.contents, IID_AGILE):
            ppv[0] = this
            return 0
        ppv[0] = None
        return -2147467262  # E_NOINTERFACE

    def completed(_this, _op):
        done.set()
        return 0

    vtbl = _HandlerVtbl(_QI_T(qi), _REF_T(lambda t: 2), _REF_T(lambda t: 1),
                        _DONE_T(completed))
    obj = _HandlerObj(ctypes.pointer(vtbl))
    params = _ActivationParams(1, _ProcLoopbackParams(pid, 0))
    pv = _PropVariantBlob(VT_BLOB, 0, 0, 0, ctypes.sizeof(params),
                          ctypes.cast(ctypes.byref(params), ctypes.c_void_p))
    op = ctypes.c_void_p()
    hr = mmdevapi.ActivateAudioInterfaceAsync(
        ctypes.c_wchar_p(PROC_LOOPBACK_PATH), ctypes.byref(IID_CLIENT),
        ctypes.byref(pv), ctypes.byref(obj), ctypes.byref(op))
    if hr != 0:
        raise OSError(f"ActivateAsync {hr & 0xFFFFFFFF:#x}")
    if not done.wait(5):
        _release(op)
        raise OSError("activation timeout")
    hr_act = ctypes.c_int32()
    client = ctypes.c_void_p()
    hr = _vt(op, 3, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32),
             ctypes.POINTER(ctypes.c_void_p))(op, ctypes.byref(hr_act),
                                              ctypes.byref(client))
    _release(op)
    if hr != 0 or hr_act.value != 0:
        raise OSError(f"GetActivateResult {hr & 0xFFFFFFFF:#x}"
                      f" act={hr_act.value & 0xFFFFFFFF:#x}")
    return client


class Capture:
    def __init__(self, loopback=True, device_id=None, process_pid=None):
        self.enum = None
        self.dev = None
        self.client = ctypes.c_void_p()
        self.cap = ctypes.c_void_p()
        self._event = None
        if process_pid is not None:
            self._init_process(process_pid)
        else:
            self._init_device(loopback, device_id)
        hr = _vt(self.client, 14, ctypes.c_int32, ctypes.POINTER(GUID),
                 ctypes.POINTER(ctypes.c_void_p))(
            self.client, ctypes.byref(IID_CAPTURE), ctypes.byref(self.cap))
        if hr != 0:
            raise OSError(f"GetService {hr & 0xFFFFFFFF:#x}")
        hr = _vt(self.client, 10, ctypes.c_int32)(self.client)
        if hr != 0:
            raise OSError(f"Start {hr & 0xFFFFFFFF:#x}")

    def _init_process(self, pid):
        self.client = _activate_process_client(pid)
        self.rate, self.channels, self.block = 48000, 2, 8
        self.is_float = True
        fmt = WAVEFORMATEX(3, 2, 48000, 48000 * 8, 8, 32, 0)
        init = _vt(self.client, 3, ctypes.c_int32, ctypes.c_int, ctypes.c_uint,
                   ctypes.c_longlong, ctypes.c_longlong, ctypes.c_void_p,
                   ctypes.c_void_p)
        hr = init(self.client, 0, LOOPBACK, 2_000_000, 0,
                  ctypes.byref(fmt), None)
        if hr != 0:
            kernel32 = ctypes.windll.kernel32
            self._event = kernel32.CreateEventW(None, False, False, None)
            hr = init(self.client, 0, LOOPBACK | EVENTCALLBACK, 2_000_000, 0,
                      ctypes.byref(fmt), None)
            if hr == 0:
                _vt(self.client, 13, ctypes.c_int32, ctypes.c_void_p)(
                    self.client, self._event)
        if hr != 0:
            raise OSError(f"Initialize(proc) {hr & 0xFFFFFFFF:#x}")

    def _init_device(self, loopback, device_id):
        self.enum = _enumerator()
        self.dev = ctypes.c_void_p()
        if device_id:
            hr = _vt(self.enum, 5, ctypes.c_int32, ctypes.c_wchar_p,
                     ctypes.POINTER(ctypes.c_void_p))(self.enum, device_id,
                                                      ctypes.byref(self.dev))
        else:
            flow = 0 if loopback else 1
            hr = _vt(self.enum, 4, ctypes.c_int32, ctypes.c_int, ctypes.c_int,
                     ctypes.POINTER(ctypes.c_void_p))(self.enum, flow, 0,
                                                      ctypes.byref(self.dev))
        if hr != 0:
            raise OSError(f"endpoint {hr & 0xFFFFFFFF:#x}")
        hr = _vt(self.dev, 3, ctypes.c_int32, ctypes.POINTER(GUID), ctypes.c_uint,
                 ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            self.dev, ctypes.byref(IID_CLIENT), CLSCTX_ALL, None,
            ctypes.byref(self.client))
        if hr != 0:
            raise OSError(f"Activate {hr & 0xFFFFFFFF:#x}")
        pwfx = ctypes.POINTER(WAVEFORMATEX)()
        hr = _vt(self.client, 8, ctypes.c_int32,
                 ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)))(
            self.client, ctypes.byref(pwfx))
        if hr != 0:
            raise OSError(f"GetMixFormat {hr & 0xFFFFFFFF:#x}")
        f = pwfx.contents
        self.rate = f.nSamplesPerSec
        self.channels = f.nChannels
        self.block = f.nBlockAlign
        self.is_float = f.wFormatTag == 3
        if f.wFormatTag == 0xFFFE and f.cbSize >= 22:
            sub = ctypes.cast(ctypes.addressof(f) + 24,
                              ctypes.POINTER(ctypes.c_uint32)).contents.value
            self.is_float = sub == 3
        flags = LOOPBACK if loopback else 0
        hr = _vt(self.client, 3, ctypes.c_int32, ctypes.c_int, ctypes.c_uint,
                 ctypes.c_longlong, ctypes.c_longlong, ctypes.c_void_p,
                 ctypes.c_void_p)(self.client, 0, flags, 4_000_000, 0,
                                  ctypes.cast(pwfx, ctypes.c_void_p), None)
        ole32.CoTaskMemFree(pwfx)
        if hr != 0:
            raise OSError(f"Initialize {hr & 0xFFFFFFFF:#x}")

    def read(self):
        out = bytearray()
        n = ctypes.c_uint()
        while True:
            hr = _vt(self.cap, 5, ctypes.c_int32,
                     ctypes.POINTER(ctypes.c_uint))(self.cap, ctypes.byref(n))
            if hr != 0:
                raise OSError(f"GetNextPacketSize {hr & 0xFFFFFFFF:#x}")
            if n.value == 0:
                return bytes(out)
            data = ctypes.c_void_p()
            frames = ctypes.c_uint()
            flags = ctypes.c_uint()
            hr = _vt(self.cap, 3, ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p),
                     ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                     ctypes.c_void_p, ctypes.c_void_p)(
                self.cap, ctypes.byref(data), ctypes.byref(frames),
                ctypes.byref(flags), None, None)
            if hr != 0:
                raise OSError(f"GetBuffer {hr & 0xFFFFFFFF:#x}")
            nbytes = frames.value * self.block
            if flags.value & SILENT_FLAG or not data.value:
                out += bytes(nbytes)
            else:
                out += ctypes.string_at(data.value, nbytes)
            _vt(self.cap, 4, ctypes.c_int32, ctypes.c_uint)(self.cap, frames.value)

    def close(self):
        try:
            _vt(self.client, 11, ctypes.c_int32)(self.client)
        except Exception:
            pass
        for o in (self.cap, self.client, self.dev, self.enum):
            _release(o)
        if self._event:
            ctypes.windll.kernel32.CloseHandle(self._event)
            self._event = None
        self.cap = self.client = self.dev = self.enum = None
