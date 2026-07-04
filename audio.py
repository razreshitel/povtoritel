import ctypes
import logging

log = logging.getLogger("povtoritel")

ole32 = ctypes.windll.ole32
CLSCTX_ALL = 0x17
LOOPBACK = 0x00020000
SILENT_FLAG = 0x2


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


def _vt(obj, idx, restype, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[idx])


def _release(obj):
    if obj:
        _vt(obj, 2, ctypes.c_ulong)(obj)


def com_init():
    ole32.CoInitializeEx(None, 0)


class Loopback:
    def __init__(self):
        self.enum = ctypes.c_void_p()
        self.dev = ctypes.c_void_p()
        self.client = ctypes.c_void_p()
        self.cap = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ENUM), None, CLSCTX_ALL,
                                    ctypes.byref(IID_ENUM), ctypes.byref(self.enum))
        if hr != 0:
            raise OSError(f"CoCreateInstance {hr & 0xFFFFFFFF:#x}")
        hr = _vt(self.enum, 4, ctypes.c_int32, ctypes.c_int, ctypes.c_int,
                 ctypes.POINTER(ctypes.c_void_p))(self.enum, 0, 0,
                                                  ctypes.byref(self.dev))
        if hr != 0:
            raise OSError(f"GetDefaultAudioEndpoint {hr & 0xFFFFFFFF:#x}")
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
        hr = _vt(self.client, 3, ctypes.c_int32, ctypes.c_int, ctypes.c_uint,
                 ctypes.c_longlong, ctypes.c_longlong, ctypes.c_void_p,
                 ctypes.c_void_p)(self.client, 0, LOOPBACK, 4_000_000, 0,
                                  ctypes.cast(pwfx, ctypes.c_void_p), None)
        ole32.CoTaskMemFree(pwfx)
        if hr != 0:
            raise OSError(f"Initialize {hr & 0xFFFFFFFF:#x}")
        hr = _vt(self.client, 14, ctypes.c_int32, ctypes.POINTER(GUID),
                 ctypes.POINTER(ctypes.c_void_p))(
            self.client, ctypes.byref(IID_CAPTURE), ctypes.byref(self.cap))
        if hr != 0:
            raise OSError(f"GetService {hr & 0xFFFFFFFF:#x}")
        hr = _vt(self.client, 10, ctypes.c_int32)(self.client)
        if hr != 0:
            raise OSError(f"Start {hr & 0xFFFFFFFF:#x}")

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
        self.cap = self.client = self.dev = self.enum = None
