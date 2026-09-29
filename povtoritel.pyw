import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import winutil
from recorder import Recorder

log = logging.getLogger("povtoritel")

MENU_SAVE, MENU_RECORD, MENU_PAUSE, MENU_FOLDER, MENU_SETTINGS, MENU_AUTOSTART, MENU_QUIT = range(1, 8)


class App:
    def __init__(self, ffmpeg):
        self.cfg = common.load_cfg()
        self.recorder = Recorder(ffmpeg, common.FF_LOG)
        self.recorder.configure(self.cfg)
        self.recorder.fail_cb = self._capture_failing
        self.busy = threading.Lock()
        self.record_busy = threading.Lock()
        self.ticks = 0
        self._reminded = 0
        self._pending_toast = None
        self.tray = winutil.Tray(self._tip(), common.ICON_ACTIVE, self.handle)
        try:
            self.toast = winutil.Toast()
        except Exception:
            log.exception("toast init failed")
            self.toast = None
        self._register_hotkeys()
        self.recorder.start()
        self.tray.start_timer(60000)

    def _tip(self):
        active, dur, _size = self.recorder.recording_status()
        if active:
            return f"Povtoritel: recording {int(dur)}s"
        if self.recorder.paused:
            return "Povtoritel: paused"
        secs, size = self.recorder.buffered()
        return (f"Povtoritel: {int(secs)}s of {self.cfg['minutes']} min buffered,"
                f" {size / 1e6:.0f} MB RAM, {self.cfg['hotkey']['label']}")

    def _update_tray(self):
        if self.recorder.recording():
            icon = common.ICON_REC
        elif self.recorder.paused:
            icon = common.ICON_PAUSE
        else:
            icon = common.ICON_ACTIVE
        self.tray.set_icon(icon)
        self.tray.set_tip(self._tip())

    def handle(self, kind, _data):
        if kind == "save":
            self.save_async()
        elif kind == "record":
            self.toggle_recording()
        elif kind == "menu":
            self.menu()
        elif kind == "settings":
            self.open_settings()
        elif kind == "reload":
            self.reload()
        elif kind == "toast":
            if self.toast and self._pending_toast:
                title, body, ok, monitor, fallback = self._pending_toast
                try:
                    shown = self.toast.show(title, body, ok, monitor)
                except Exception:
                    log.exception("toast display failed")
                    shown = False
                if not shown and fallback:
                    self.tray.balloon(title, body)
                elif not shown:
                    log.warning("toast not shown: %s", title)
        elif kind == "timer":
            if self.recorder.stalled():
                log.warning("capture stalled, restarting")
                self.recorder.restart()
            self._update_tray()
            self.ticks += 1
            if self.ticks % 5 == 0:
                secs, size = self.recorder.buffered()
                log.info("buffer: %.0fs, %.1f MB", secs, size / 1e6)
            self._remind_recording()
        elif kind == "quit":
            self.quit()

    def menu(self):
        paused = self.recorder.paused
        recording = self.recorder.recording()
        record_label = "Stop long recording" if recording else "Start long recording"
        if self.cfg.get("hold_for_recording", False):
            record_label += f" (hold {self.cfg['hotkey']['label']} 2s)"
        else:
            record_label += f" ({self.cfg['record_hotkey']['label']})"
        items = [
            (MENU_SAVE, f"Save replay now ({self.cfg['hotkey']['label']})",
             False, True),
            (MENU_RECORD, record_label, recording, True),
            (MENU_PAUSE, "Resume buffering" if paused else "Pause buffering",
             False, not recording),
            None,
            (MENU_FOLDER, "Open replays folder", False, True),
            (MENU_SETTINGS, "Settings...", False, True),
            (MENU_AUTOSTART, "Start with Windows",
             winutil.get_autostart() is not None, True),
            None,
            (MENU_QUIT, "Quit Povtoritel", False, True),
        ]
        cmd = self.tray.popup(items)
        if cmd == MENU_SAVE:
            self.save_async()
        elif cmd == MENU_RECORD:
            self.toggle_recording()
        elif cmd == MENU_PAUSE:
            if paused:
                self.recorder.resume()
            else:
                self.recorder.pause()
            self._update_tray()
        elif cmd == MENU_FOLDER:
            Path(self.cfg["folder"]).mkdir(parents=True, exist_ok=True)
            os.startfile(self.cfg["folder"])
        elif cmd == MENU_SETTINGS:
            self.open_settings()
        elif cmd == MENU_AUTOSTART:
            if winutil.get_autostart() is None:
                winutil.set_autostart(common.startup_cmd())
                self.cfg["autostart"] = True
            else:
                winutil.remove_autostart()
                self.cfg["autostart"] = False
            common.save_cfg(self.cfg)
        elif cmd == MENU_QUIT:
            self.quit()

    def save_async(self):
        if not self.busy.acquire(blocking=False):
            return
        threading.Thread(target=self._save_job, daemon=True).start()

    def _save_job(self):
        try:
            out, dur, size = self.recorder.save(self.cfg["folder"])
            self._notify("Replay saved", f"{dur:.0f}s  -  {size / 1e6:.0f} MB", True)
        except Exception as e:
            log.exception("save failed")
            self._notify("Save failed", str(e)[:60], False)
        finally:
            self.busy.release()

    def toggle_recording(self):
        if not self.record_busy.acquire(blocking=False):
            return
        threading.Thread(target=self._record_job, daemon=True).start()

    def _record_job(self):
        try:
            if self.recorder.recording():
                out, dur, size = self.recorder.stop_recording()
                self._notify("Recording saved",
                             f"{dur:.0f}s  -  {size / 1e6:.0f} MB", True)
            else:
                self.recorder.start_recording(self.cfg["folder"])
                self._reminded = 0
                self._notify("Recording started", "Press the hotkey again to stop", True)
        except Exception as e:
            log.exception("continuous recording failed")
            self._notify("Recording failed", str(e)[:80], False)
        finally:
            self.record_busy.release()
            self._update_tray()

    def _remind_recording(self):
        try:
            every = float(self.cfg.get("record_reminder_min", 30)) * 60
        except (TypeError, ValueError):
            every = 30 * 60
        active, dur, _size = self.recorder.recording_status()
        if not active or every <= 0:
            self._reminded = 0
            return
        due = int(dur // every)
        if due <= self._reminded:
            return
        self._reminded = due
        elapsed = _minutes_text(round(due * every / 60))
        if self.cfg.get("hold_for_recording", False):
            hint = f"Hold {self.cfg['hotkey']['label']} for 2s to stop"
        else:
            hint = f"Press {self.cfg['record_hotkey']['label']} to stop"
        log.info("recording reminder: %s", elapsed)
        # balloons would be captured
        self._notify(f"Still recording: {elapsed}", hint, True, fallback=False)

    def _notify(self, title, body, ok, fallback=True):
        if self.toast and (fallback or self.toast.excluded):
            try:
                monitor = winutil.output_rect(self.cfg["screen"])
                self._pending_toast = (title, body, ok, monitor, fallback)
                if not winutil.user32.PostMessageW(self.tray.hwnd,
                                                   winutil.MSG_TOAST, 0, 0):
                    raise OSError("toast message queue failed")
            except Exception:
                log.exception("toast queue failed")
                if fallback:
                    self.tray.balloon(title, body)
        elif fallback:
            self.tray.balloon(title, body)
        else:
            log.warning("notification skipped: %s: %s", title, body)

    def open_settings(self):
        subprocess.Popen(common.launch_cmd("--settings"))

    def reload(self):
        self.cfg = common.load_cfg()
        self.recorder.configure(self.cfg)
        if self._register_hotkeys():
            self.tray.balloon("Settings applied",
                              f"{self.cfg['minutes']} min buffer,"
                              f" save with {self.cfg['hotkey']['label']}")
        self._update_tray()

    def _register_hotkeys(self):
        ok = self.tray.register_hotkeys(
            self.cfg["hotkey"], self.cfg["record_hotkey"],
            self.cfg.get("hold_for_recording", False))
        if not ok:
            self.tray.balloon("Hotkeys unavailable",
                              "Global keyboard hook failed. Restart Povtoritel.")
        return ok

    def _capture_failing(self, fails):
        if fails >= 8:
            self.tray.balloon("Capture failing",
                              "Screen capture keeps failing; retrying every"
                              " minute. It resumes by itself once the screen"
                              " is available (see ffmpeg.log).")
        else:
            self.tray.balloon("Capture failing",
                              "Screen capture keeps failing. If this persists,"
                              " re-pick the screen in Settings"
                              " (see ffmpeg.log).")

    def quit(self):
        with self.busy, self.record_busy:
            if self.recorder.recording():
                try:
                    self.recorder.stop_recording()
                except Exception:
                    log.exception("recording finalization on quit failed")
            self.recorder.stop()
            self.tray.destroy()


def _minutes_text(minutes):
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def run_app():
    common.setup_logging()
    # run under Povtoritel.exe
    if (common.EXE.exists() and not common.in_exe()
            and not os.environ.get("POVTORITEL_RELAUNCH")):
        log.info("relaunching via %s", common.EXE.name)
        env = dict(os.environ, POVTORITEL_RELAUNCH="1")
        subprocess.Popen(common.launch_cmd(), env=env)
        return
    winutil.set_dpi_aware()
    winutil.kernel32.SetErrorMode(0x8003)
    import time
    got = False
    for _ in range(10):
        if winutil.single_instance("Local\\PovtoritelMutex"):
            got = True
            break
        if winutil.post_to_running(winutil.MSG_SETTINGS):
            return
        time.sleep(0.5)
    if not got:
        return
    common.rotate(common.FF_LOG)
    for path, color in ((common.ICON_ACTIVE, (48, 180, 86)),
                        (common.ICON_REC, (224, 48, 48)),
                        (common.ICON_PAUSE, (140, 140, 140))):
        if not path.exists():
            winutil.write_ico(path, color)
    ffmpeg = common.find_ffmpeg()
    if not ffmpeg or not common.ffmpeg_works(ffmpeg):
        winutil.error_box("Povtoritel", "No working ffmpeg.exe found. Put a"
                          f" static build in:\n{common.BIN_DIR}")
        return
    cfg = common.load_cfg()
    Path(cfg["folder"]).mkdir(parents=True, exist_ok=True)
    if cfg["autostart"]:
        winutil.set_autostart(common.startup_cmd())
    log.info("povtoritel starting, ffmpeg=%s", ffmpeg)
    app = App(ffmpeg)
    try:
        app.tray.run()
    finally:
        app.recorder.stop()
    log.info("povtoritel exited")


def check():
    winutil.set_dpi_aware()
    print("python:", sys.version)
    print("ffmpeg:", common.find_ffmpeg())
    print("config:", common.load_cfg())
    print("autostart:", winutil.get_autostart())
    print("screens:")
    for o in winutil.list_outputs():
        print("  ", o)


def main():
    args = {a.lower() for a in sys.argv[1:]}
    if "--settings" in args:
        import settings_ui
        settings_ui.run("--selftest" in args)
    elif "--save" in args:
        print("posted" if winutil.post_to_running(winutil.MSG_SAVE)
              else "not running")
    elif "--reload" in args:
        print("posted" if winutil.post_to_running(winutil.MSG_RELOAD)
              else "not running")
    elif "--quit" in args:
        print("posted" if winutil.post_to_running(winutil.MSG_QUIT)
              else "not running")
    elif "--check" in args:
        check()
    else:
        run_app()


if __name__ == "__main__":
    main()
