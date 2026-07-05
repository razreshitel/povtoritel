import array
import collections
import ctypes
import ctypes.wintypes as wt
import datetime
import logging
import msvcrt
import os
import subprocess
import threading
import time
from pathlib import Path

import audio
import winutil

log = logging.getLogger("povtoritel")

CREATE_NO_WINDOW = 0x08000000
QUALITY = {"low": (32, 8), "medium": (28, 15), "high": (23, 25)}
KEEP_PAD = 12
SAVE_PAD = 3
HARD_CAP = 3 * 1024 ** 3
PIPE_SIZE = 32 * 1024 * 1024
READ_SIZE = 262144
DEV_THRESH = 1e-4
MIC_THRESH = 0.003

kernel32 = ctypes.windll.kernel32
kernel32.CreateNamedPipeW.restype = wt.HANDLE
kernel32.CreateNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD,
                                      wt.DWORD, wt.DWORD, wt.DWORD, wt.LPVOID]
kernel32.ConnectNamedPipe.argtypes = [wt.HANDLE, wt.LPVOID]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID,
                                 wt.DWORD, wt.DWORD, wt.HANDLE]


def _big_pipe(size):
    rh, wh = wt.HANDLE(), wt.HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(rh), ctypes.byref(wh), None, size):
        raise OSError("CreatePipe failed")
    rfd = msvcrt.open_osfhandle(rh.value, os.O_RDONLY | os.O_BINARY)
    wfd = msvcrt.open_osfhandle(wh.value, 0)
    return rfd, wfd


def _named_pipe(name):
    h = kernel32.CreateNamedPipeW(name, 2, 0, 1, 4 * 1024 * 1024, 0, 0, None)
    if not h or h == wt.HANDLE(-1).value:
        raise OSError("CreateNamedPipe failed")
    return h


def _poke_pipe(name):
    h = kernel32.CreateFileW(name, 0x80000000, 0, None, 3, 0, None)
    if h and h != wt.HANDLE(-1).value:
        kernel32.CloseHandle(h)


def _close_pipe(src):
    h = src.get("pipe_handle")
    if h:
        kernel32.CloseHandle(h)
        src["pipe_handle"] = None


def _peak(data, is_float):
    if is_float:
        arr = array.array("f")
        arr.frombytes(data)
        return max(map(abs, arr[::16]), default=0.0)
    arr = array.array("h")
    arr.frombytes(data[: len(data) // 2 * 2])
    return max(map(abs, arr[::16]), default=0) / 32768.0


class Recorder:
    def __init__(self, ffmpeg, err_log):
        self.ffmpeg = str(ffmpeg)
        self.err_log = Path(err_log)
        self.lock = threading.Lock()
        self.chunks = collections.deque()
        self.total = 0
        self.minutes = 5
        self.screen = {"adapter": 0, "output": 0, "vendor": "0x10de"}
        self.fps = 30
        self.quality = "medium"
        self.audio_on = True
        self.mic_on = False
        self.mic_device = ""
        self.app_auto = True
        self.app_slots = 6
        self.priority = False
        self.offset_ms = 0
        self.layout = []
        self.activity = {}
        self.slot_names = {}
        self._overflow = set()
        self.proc = None
        self.paused = False
        self.fail_cb = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._restart = False
        self._fails = 0
        self._warned = set()
        self._pipe_seq = 0
        self.last_data = time.monotonic()
        self.thread = None

    def configure(self, cfg):
        restart = (dict(cfg["screen"]) != self.screen
                   or int(cfg["fps"]) != self.fps
                   or cfg["quality"] != self.quality
                   or bool(cfg.get("audio", True)) != self.audio_on
                   or bool(cfg.get("mic", False)) != self.mic_on
                   or cfg.get("mic_device", "") != self.mic_device
                   or bool(cfg.get("app_auto", True)) != self.app_auto
                   or int(cfg.get("app_slots", 6)) != self.app_slots
                   or bool(cfg.get("capture_priority", False)) != self.priority
                   or int(cfg.get("audio_offset_ms", 0)) != self.offset_ms)
        self.screen = dict(cfg["screen"])
        self.fps = int(cfg["fps"])
        self.quality = cfg["quality"]
        self.minutes = max(1, min(10, int(cfg["minutes"])))
        self.audio_on = bool(cfg.get("audio", True))
        self.mic_on = bool(cfg.get("mic", False))
        self.mic_device = cfg.get("mic_device", "")
        self.app_auto = bool(cfg.get("app_auto", True))
        self.app_slots = max(1, min(10, int(cfg.get("app_slots", 6))))
        self.priority = bool(cfg.get("capture_priority", False))
        self.offset_ms = int(cfg.get("audio_offset_ms", 0))
        if restart and self.thread and not self.paused:
            self.restart()

    def _probe(self, loopback, device, label):
        try:
            audio.com_init()
            c = audio.Capture(loopback, device or None)
            fmt = (c.rate, c.channels, c.is_float)
            c.close()
            self._warned.discard(label)
            return fmt
        except Exception as e:
            if label not in self._warned:
                self._warned.add(label)
                log.warning("%s audio unavailable: %s", label, e)
            return None

    def _plan(self):
        srcs = []
        if self.audio_on:
            fmt = self._probe(True, None, "desktop")
            if fmt:
                srcs.append({"label": "desktop", "title": "Desktop",
                             "kind": "loopback", "fmt": fmt,
                             "device": "", "thresh": DEV_THRESH})
        if self.app_auto:
            for i in range(self.app_slots):
                srcs.append({"label": f"slot{i}", "title": "App",
                             "kind": "slot", "fmt": (48000, 2, True),
                             "thresh": DEV_THRESH, "bind": None})
        if self.mic_on:
            fmt = self._probe(False, self.mic_device, "microphone")
            if fmt:
                srcs.append({"label": "mic", "title": "Microphone",
                             "kind": "mic", "fmt": fmt,
                             "device": self.mic_device, "thresh": MIC_THRESH})
        for s in srcs:
            s["act"] = collections.deque()
        return srcs

    def _cmd(self, srcs):
        cq, mbit = QUALITY.get(self.quality, QUALITY["medium"])
        a = int(self.screen.get("adapter", 0))
        o = int(self.screen.get("output", 0))
        vendor = self.screen.get("vendor", "")
        grab = f"ddagrab=output_idx={o}:framerate={self.fps}"
        if vendor == "0x1002":
            enc = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak",
                   "-b:v", f"{max(2, mbit * 2 // 3)}M", "-maxrate", f"{mbit}M"]
        else:
            if vendor != "0x10de":
                grab += ",hwdownload,format=bgra"
            enc = ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
                   "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                   "-maxrate", f"{mbit}M", "-bufsize", f"{mbit * 2}M"]
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
               "-init_hw_device", f"d3d11va=gpu:{a}", "-filter_hw_device", "gpu",
               "-filter_complex", grab]
        maps = []
        for idx, s in enumerate(srcs):
            rate, ch, is_float = s["fmt"]
            if self.offset_ms:
                cmd += ["-itsoffset", str(self.offset_ms / 1000)]
            cmd += ["-f", "f32le" if is_float else "s16le", "-ar", str(rate),
                    "-ac", str(ch), "-i", s["pipe_name"]]
            maps += ["-map", f"{idx}:a"]
        cmd += enc
        if srcs:
            cmd += ["-c:a", "aac", "-b:a", "160k"] + maps
        cmd += ["-g", str(self.fps), "-r", str(self.fps), "-fps_mode", "cfr",
                "-f", "mpegts", "pipe:1"]
        return cmd

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _boost(self, pid):
        try:
            ok = winutil.boost_process(pid)
            log.info("capture priority boost: %s", "ok" if ok else "failed")
        except Exception:
            log.exception("boost failed")

    def _mark(self, src, now):
        dq = src["act"]
        if not dq or now - dq[-1] > 0.5:
            dq.append(now)
            cut = now - 660
            while dq and dq[0] < cut:
                dq.popleft()

    def _sink_for(self, proc, src):
        ok = kernel32.ConnectNamedPipe(src["pipe_handle"], None)
        if not ok and kernel32.GetLastError() != 535:
            _close_pipe(src)
            raise OSError(f"ConnectNamedPipe {kernel32.GetLastError()}")
        if proc.poll() is not None:
            _close_pipe(src)
            return None
        fd = msvcrt.open_osfhandle(src["pipe_handle"], 0)
        src["pipe_handle"] = None
        return os.fdopen(fd, "wb", 0)

    def _feed_dev(self, proc, spawn_t, src):
        audio.com_init()
        cap = None
        sink = None
        loopback = src["kind"] == "loopback"
        try:
            sink = self._sink_for(proc, src)
            if sink is None:
                return
            cap = audio.Capture(loopback, src.get("device") or None)
            rate, block, isf = cap.rate, cap.block, cap.is_float
            lead = int((time.monotonic() - spawn_t) * rate)
            sent = 0
            if 0 < lead < rate * 3:
                sink.write(bytes(lead * block))
                sent = lead
            quiet = time.monotonic()
            while proc.poll() is None and not self._stop.is_set():
                data = cap.read()
                now = time.monotonic()
                if data:
                    sink.write(data)
                    sent += len(data) // block
                    quiet = now
                    if _peak(data, isf) >= src["thresh"]:
                        self._mark(src, now)
                target = int((now - spawn_t) * rate)
                if target - sent > rate // 20:
                    n = min(target - sent, rate // 2)
                    sink.write(bytes(n * block))
                    sent += n
                if loopback and now - quiet > 10:
                    quiet = now
                    try:
                        ncap = audio.Capture(True, src.get("device") or None)
                    except OSError:
                        pass
                    else:
                        cap.close()
                        cap = ncap
                time.sleep(0.005)
        except (OSError, ValueError) as e:
            log.warning("%s feed ended: %s", src["label"], e)
        except Exception:
            log.exception("%s feed failed", src["label"])
        finally:
            if cap:
                try:
                    cap.close()
                except Exception:
                    pass
            if sink:
                try:
                    sink.close()
                except (OSError, ValueError):
                    pass

    def _feed_slot(self, proc, spawn_t, src):
        audio.com_init()
        cap = None
        sink = None
        pid = None
        rate, block = 48000, 8
        try:
            sink = self._sink_for(proc, src)
            if sink is None:
                return
            lead = int((time.monotonic() - spawn_t) * rate)
            sent = 0
            if 0 < lead < rate * 3:
                sink.write(bytes(lead * block))
                sent = lead
            next_check = 0.0
            while proc.poll() is None and not self._stop.is_set():
                now = time.monotonic()
                bind = src.get("bind")
                want = bind.get("pid") if bind else None
                if cap is None and want:
                    try:
                        cap = audio.Capture(process_pid=want)
                        pid = want
                        next_check = now + 5
                        log.info("track '%s' attached: pid=%s",
                                 bind.get("exe"), want)
                    except OSError as e:
                        bind["pid"] = None
                        key = "attach_" + str(want)
                        if key not in self._warned:
                            self._warned.add(key)
                            log.warning("track '%s' attach failed: %s",
                                        bind.get("exe"), e)
                data = b""
                if cap:
                    try:
                        data = cap.read()
                    except OSError:
                        data = b""
                        cap.close()
                        cap = None
                        if bind:
                            bind["pid"] = None
                        log.info("track slot detached (pid %s)", pid)
                    if cap and now >= next_check:
                        next_check = now + 5
                        if not winutil.pid_alive(pid):
                            cap.close()
                            cap = None
                            if bind:
                                bind["pid"] = None
                            log.info("track '%s' target exited",
                                     bind.get("exe") if bind else "?")
                if data:
                    sink.write(data)
                    sent += len(data) // block
                    if _peak(data, True) >= src["thresh"]:
                        self._mark(src, now)
                target = int((now - spawn_t) * rate)
                if target - sent > rate // 20:
                    n = min(target - sent, rate // 2)
                    sink.write(bytes(n * block))
                    sent += n
                time.sleep(0.005)
        except (OSError, ValueError) as e:
            log.warning("%s feed ended: %s", src["label"], e)
        except Exception:
            log.exception("%s feed failed", src["label"])
        finally:
            if cap:
                try:
                    cap.close()
                except Exception:
                    pass
            if sink:
                try:
                    sink.close()
                except (OSError, ValueError):
                    pass

    def _watch_sessions(self, proc, slots, names):
        audio.com_init()
        me = os.getpid()
        while proc.poll() is None and not self._stop.is_set():
            try:
                sessions = audio.list_audio_sessions()
                procs = winutil.list_processes()
            except Exception:
                if self._stop.wait(3):
                    return
                continue
            exe_by_pid = {p: x for p, _pp, x in procs}
            active = {}
            for pid, state, is_sys in sessions:
                if is_sys or state != 1 or pid in (0, 4, me):
                    continue
                exe = exe_by_pid.get(pid)
                if not exe or exe in ("audiodg.exe", "ffmpeg.exe"):
                    continue
                active.setdefault(exe, pid)
            by_exe = {}
            for s in slots:
                b = s.get("bind")
                if b:
                    by_exe[b["exe"]] = s
            for exe, sess_pid in active.items():
                s = by_exe.get(exe)
                if s is None:
                    s = next((x for x in slots if not x.get("bind")), None)
                    if s is None:
                        if exe not in self._overflow:
                            self._overflow.add(exe)
                            log.warning("no free track slot for %s"
                                        " (audio stays in Desktop mix)", exe)
                        continue
                    root, _exe = winutil.find_audio_root([exe])
                    s["bind"] = {"exe": exe, "pid": root or sess_pid}
                    stem = exe[:-4] if exe.endswith(".exe") else exe
                    names[s["label"]] = stem
                    log.info("%s -> %s", s["label"], exe)
                else:
                    b = s["bind"]
                    if not b.get("pid"):
                        root, _exe = winutil.find_audio_root([exe])
                        b["pid"] = root or sess_pid
            if self._stop.wait(1.5):
                return

    def _run(self):
        try:
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 2)
        except Exception:
            pass
        while not self._stop.is_set():
            if self.paused:
                self._wake.wait()
                self._wake.clear()
                continue
            srcs = self._plan()
            live = []
            for s in srcs:
                self._pipe_seq += 1
                s["pipe_name"] = (rf"\\.\pipe\povtoritel_{s['label']}_"
                                  rf"{os.getpid()}_{self._pipe_seq}")
                try:
                    s["pipe_handle"] = _named_pipe(s["pipe_name"])
                    live.append(s)
                except OSError as e:
                    log.warning("pipe for %s failed: %s", s["label"], e)
            srcs = live
            names = {}
            with self.lock:
                self.chunks.clear()
                self.total = 0
                self.layout = [(s["label"], s["title"]) for s in srcs]
                self.activity = {s["label"]: s["act"] for s in srcs}
                self.slot_names = names
                self._overflow = set()
            cmd = self._cmd(srcs)
            try:
                rfd, wfd = _big_pipe(PIPE_SIZE)
            except OSError as e:
                log.error("pipe failed: %s", e)
                for s in srcs:
                    _close_pipe(s)
                self._stop.wait(10)
                continue
            try:
                errf = open(self.err_log, "ab")
            except OSError:
                errf = subprocess.DEVNULL
            spawn_t = time.monotonic()
            try:
                proc = subprocess.Popen(
                    cmd, stdout=wfd, stdin=subprocess.PIPE,
                    stderr=errf, bufsize=0, creationflags=CREATE_NO_WINDOW)
            except OSError as e:
                os.close(rfd)
                os.close(wfd)
                for s in srcs:
                    _close_pipe(s)
                log.error("ffmpeg launch failed: %s", e)
                self._stop.wait(10)
                continue
            finally:
                if errf is not subprocess.DEVNULL:
                    errf.close()
            os.close(wfd)
            self.proc = proc
            self._restart = False
            if self.priority:
                threading.Thread(target=self._boost, args=(proc.pid,),
                                 daemon=True).start()
            feeders = []
            for s in srcs:
                fn = self._feed_slot if s["kind"] == "slot" else self._feed_dev
                th = threading.Thread(target=fn, args=(proc, spawn_t, s),
                                      daemon=True)
                th.start()
                feeders.append(th)
            slots = [s for s in srcs if s["kind"] == "slot"]
            if slots:
                threading.Thread(target=self._watch_sessions,
                                 args=(proc, slots, names), daemon=True).start()
            log.info("capture started: adapter=%s output=%s fps=%s quality=%s"
                     " audio=%s app_slots=%s",
                     self.screen.get("adapter"), self.screen.get("output"),
                     self.fps, self.quality, self.audio_on, len(slots))
            started = time.monotonic()
            self.last_data = started
            while True:
                try:
                    data = os.read(rfd, READ_SIZE)
                except OSError:
                    data = b""
                if not data:
                    break
                now = time.monotonic()
                self.last_data = now
                with self.lock:
                    self.chunks.append((now, data))
                    self.total += len(data)
                    keep = self.minutes * 60 + KEEP_PAD
                    while self.chunks and self.chunks[0][0] < now - keep:
                        self.total -= len(self.chunks.popleft()[1])
                    while self.total > HARD_CAP and len(self.chunks) > 1:
                        self.total -= len(self.chunks.popleft()[1])
            os.close(rfd)
            rc = proc.wait()
            self.proc = None
            for s in srcs:
                _poke_pipe(s["pipe_name"])
            for th in feeders:
                th.join(2)
            if self._stop.is_set() or self.paused or self._restart:
                continue
            alive = time.monotonic() - started
            self._fails = 0 if alive > 60 else min(self._fails + 1, 99)
            wait = min(60, 2 * self._fails) if self._fails else 1
            log.warning("capture exited rc=%s after %.0fs, retry in %ss", rc, alive, wait)
            if (self._fails in (3, 8) and self.fail_cb
                    and not winutil.desktop_locked()):
                try:
                    self.fail_cb(self._fails)
                except Exception:
                    pass
            self._stop.wait(wait)

    def _kill(self):
        p = self.proc
        if not p:
            return
        try:
            p.stdin.write(b"q\n")
            p.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass
        try:
            p.wait(3)
            return
        except subprocess.TimeoutExpired:
            log.warning("graceful quit timed out, killing")
        try:
            p.kill()
        except OSError:
            pass

    def restart(self):
        self._restart = True
        self._kill()

    def pause(self):
        self.paused = True
        self._kill()

    def resume(self):
        self.paused = False
        self._wake.set()

    def stop(self):
        self._stop.set()
        self.paused = False
        self._wake.set()
        self._kill()
        if self.thread:
            self.thread.join(5)

    def buffered(self):
        with self.lock:
            if len(self.chunks) < 2:
                return 0.0, self.total
            return self.chunks[-1][0] - self.chunks[0][0], self.total

    def stalled(self, limit=150):
        if self.paused or self.proc is None or self._stop.is_set():
            return False
        return time.monotonic() - self.last_data > limit

    def save(self, folder):
        with self.lock:
            snap = list(self.chunks)
            layout = list(self.layout)
            names = dict(self.slot_names)
            last_act = {k: (dq[-1] if dq else None)
                        for k, dq in self.activity.items()}
        if len(snap) < 2:
            raise RuntimeError("nothing buffered yet")
        cut = snap[-1][0] - (self.minutes * 60 + SAVE_PAD)
        snap = [c for c in snap if c[0] >= cut]
        dur = snap[-1][0] - snap[0][0]
        maps = ["-map", "0:v:0"]
        meta = []
        kept = []
        out_a = 0
        for i, (label, title) in enumerate(layout):
            title = names.get(label, title)
            last = last_act.get(label)
            if last is not None and last >= cut - 2:
                maps += ["-map", f"0:a:{i}?"]
                meta += [f"-metadata:s:a:{out_a}", f"handler_name={title}",
                         f"-metadata:s:a:{out_a}", f"title={title}"]
                kept.append(title)
                out_a += 1
        log.info("saving tracks: %s (of %s)", kept or "none",
                 [t for _l, t in layout])
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        name = "replay_" + datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".mp4"
        out = folder / name
        with open(self.err_log, "ab") as errf:
            proc = subprocess.Popen(
                [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "mpegts", "-i", "pipe:0"] + maps +
                ["-c", "copy"] + meta + ["-movflags", "+faststart", str(out)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errf,
                creationflags=CREATE_NO_WINDOW)
            try:
                for _, b in snap:
                    proc.stdin.write(b)
                proc.stdin.close()
            except OSError:
                pass
            rc = proc.wait()
        if rc != 0 or not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"remux failed rc={rc}")
        size = out.stat().st_size
        log.info("saved %s (%.0f s, %.1f MB)", out.name, dur, size / 1e6)
        return out, dur, size
