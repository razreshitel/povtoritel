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


def _big_pipe(size):
    rh, wh = wt.HANDLE(), wt.HANDLE()
    if not ctypes.windll.kernel32.CreatePipe(ctypes.byref(rh), ctypes.byref(wh),
                                             None, size):
        raise OSError("CreatePipe failed")
    rfd = msvcrt.open_osfhandle(rh.value, os.O_RDONLY | os.O_BINARY)
    wfd = msvcrt.open_osfhandle(wh.value, 0)
    return rfd, wfd


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
        self.priority = True
        self.offset_ms = 0
        self.proc = None
        self.paused = False
        self.fail_cb = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._restart = False
        self._fails = 0
        self._audio_warned = False
        self.thread = None

    def configure(self, cfg):
        restart = (dict(cfg["screen"]) != self.screen
                   or int(cfg["fps"]) != self.fps
                   or cfg["quality"] != self.quality
                   or bool(cfg.get("audio", True)) != self.audio_on
                   or bool(cfg.get("capture_priority", True)) != self.priority
                   or int(cfg.get("audio_offset_ms", 0)) != self.offset_ms)
        self.screen = dict(cfg["screen"])
        self.fps = int(cfg["fps"])
        self.quality = cfg["quality"]
        self.minutes = max(1, min(10, int(cfg["minutes"])))
        self.audio_on = bool(cfg.get("audio", True))
        self.priority = bool(cfg.get("capture_priority", True))
        self.offset_ms = int(cfg.get("audio_offset_ms", 0))
        if restart and self.thread and not self.paused:
            self.restart()

    def _probe_audio(self):
        try:
            audio.com_init()
            lb = audio.Loopback()
            fmt = (lb.rate, lb.channels, lb.is_float)
            lb.close()
            self._audio_warned = False
            return fmt
        except Exception as e:
            if not self._audio_warned:
                self._audio_warned = True
                log.warning("desktop audio unavailable: %s", e)
            return None

    def _cmd(self, afmt):
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
        if afmt:
            rate, ch, is_float = afmt
            if self.offset_ms:
                cmd += ["-itsoffset", str(self.offset_ms / 1000)]
            cmd += ["-f", "f32le" if is_float else "s16le",
                    "-ar", str(rate), "-ac", str(ch), "-i", "pipe:0"]
        cmd += enc
        if afmt:
            cmd += ["-c:a", "aac", "-b:a", "160k", "-map", "0:a"]
        cmd += ["-g", str(self.fps), "-r", str(self.fps), "-fps_mode", "cfr",
                "-f", "mpegts", "pipe:1"]
        return cmd

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _audio_feed(self, proc, spawn_t):
        audio.com_init()
        cap = None
        stdin = proc.stdin
        try:
            cap = audio.Loopback()
            rate, block = cap.rate, cap.block
            lead = int((time.monotonic() - spawn_t) * rate)
            sent = 0
            if 0 < lead < rate * 3:
                stdin.write(bytes(lead * block))
                sent = lead
            quiet = time.monotonic()
            while proc.poll() is None and not self._stop.is_set():
                data = cap.read()
                now = time.monotonic()
                if data:
                    stdin.write(data)
                    sent += len(data) // block
                    quiet = now
                target = int((now - spawn_t) * rate)
                if target - sent > rate // 20:
                    n = min(target - sent, rate // 2)
                    stdin.write(bytes(n * block))
                    sent += n
                if now - quiet > 10:
                    cap.close()
                    cap = audio.Loopback()
                    quiet = now
                time.sleep(0.005)
        except (OSError, ValueError) as e:
            log.warning("audio feed ended: %s", e)
        except Exception:
            log.exception("audio feed failed")
        finally:
            if cap:
                try:
                    cap.close()
                except Exception:
                    pass
            try:
                stdin.close()
            except (OSError, ValueError):
                pass

    def _run(self):
        try:
            k = ctypes.windll.kernel32
            k.SetThreadPriority(k.GetCurrentThread(), 2)
        except Exception:
            pass
        while not self._stop.is_set():
            if self.paused:
                self._wake.wait()
                self._wake.clear()
                continue
            with self.lock:
                self.chunks.clear()
                self.total = 0
            afmt = self._probe_audio() if self.audio_on else None
            cmd = self._cmd(afmt)
            try:
                rfd, wfd = _big_pipe(PIPE_SIZE)
            except OSError as e:
                log.error("pipe failed: %s", e)
                self._stop.wait(10)
                continue
            try:
                errf = open(self.err_log, "ab")
            except OSError:
                errf = subprocess.DEVNULL
            spawn_t = time.monotonic()
            try:
                proc = subprocess.Popen(
                    cmd, stdout=wfd,
                    stdin=subprocess.PIPE if afmt else subprocess.DEVNULL,
                    stderr=errf, bufsize=0, creationflags=CREATE_NO_WINDOW)
            except OSError as e:
                os.close(rfd)
                os.close(wfd)
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
            feeder = None
            if afmt:
                feeder = threading.Thread(target=self._audio_feed,
                                          args=(proc, spawn_t), daemon=True)
                feeder.start()
            log.info("capture started: adapter=%s output=%s fps=%s quality=%s"
                     " audio=%s", self.screen.get("adapter"),
                     self.screen.get("output"), self.fps, self.quality,
                     bool(afmt))
            started = time.monotonic()
            while True:
                try:
                    data = os.read(rfd, READ_SIZE)
                except OSError:
                    data = b""
                if not data:
                    break
                now = time.monotonic()
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
            if feeder:
                feeder.join(2)
            if self._stop.is_set() or self.paused or self._restart:
                continue
            alive = time.monotonic() - started
            self._fails = 0 if alive > 60 else self._fails + 1
            wait = min(30, 2 * self._fails) if self._fails else 1
            log.warning("capture exited rc=%s after %.0fs, retry in %ss", rc, alive, wait)
            if self._fails in (3, 8) and self.fail_cb:
                try:
                    self.fail_cb(self._fails)
                except Exception:
                    pass
            if self._fails >= 8:
                self.paused = True
                self._fails = 0
                continue
            self._stop.wait(wait)

    def _boost(self, pid):
        try:
            ok = winutil.boost_process(pid)
            log.info("capture priority boost: %s", "ok" if ok else "failed")
        except Exception:
            log.exception("boost failed")

    def _kill(self):
        p = self.proc
        if p:
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

    def save(self, folder):
        with self.lock:
            snap = list(self.chunks)
        if len(snap) < 2:
            raise RuntimeError("nothing buffered yet")
        cut = snap[-1][0] - (self.minutes * 60 + SAVE_PAD)
        snap = [c for c in snap if c[0] >= cut]
        dur = snap[-1][0] - snap[0][0]
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        name = "replay_" + datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".mp4"
        out = folder / name
        with open(self.err_log, "ab") as errf:
            proc = subprocess.Popen(
                [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "mpegts", "-i", "pipe:0", "-c", "copy",
                 "-movflags", "+faststart", str(out)],
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
