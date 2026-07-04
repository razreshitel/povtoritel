import json
import logging
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SCRIPT = BASE / "povtoritel.pyw"
CONFIG_PATH = BASE / "config.json"
LOG_PATH = BASE / "povtoritel.log"
FF_LOG = BASE / "ffmpeg.log"
BIN_DIR = BASE / "bin"
ICON_REC = BASE / "icon_rec.ico"
ICON_PAUSE = BASE / "icon_pause.ico"
APP_NAME = "Povtoritel"

OVERWOLF_DIR = (Path.home() / "AppData" / "Local" / "Overwolf" / "Extensions"
                / "ncfplpkmiejjaklknfnkgcpapnhkggmlcppckhcb")

DEFAULTS = {
    "screen": {"adapter": 0, "output": 0, "vendor": "0x10de"},
    "minutes": 5,
    "fps": 30,
    "quality": "medium",
    "hotkey": {"mods": ["ctrl", "alt"], "vk": 0x52, "label": "Ctrl+Alt+R"},
    "folder": str(Path.home() / "Videos" / "Replays"),
    "audio": True,
    "mic": False,
    "mic_device": "",
    "app_auto": True,
    "app_slots": 6,
    "audio_offset_ms": 0,
    "capture_priority": False,
    "autostart": True,
}


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        data = json.loads(CONFIG_PATH.read_text("utf-8"))
        for k, v in data.items():
            if k in cfg:
                cfg[k] = v
    except (OSError, ValueError):
        pass
    return cfg


def save_cfg(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1), "utf-8")


def pythonw():
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p if p.exists() else sys.executable)


def startup_cmd():
    return f'"{pythonw()}" "{SCRIPT}"'


def find_ffmpeg():
    local = BIN_DIR / "ffmpeg.exe"
    if local.exists():
        return local
    found = sorted(OVERWOLF_DIR.glob("*/obs/bin/64bit/ffmpeg.exe"), reverse=True)
    return found[0] if found else None


def ffmpeg_works(path):
    import subprocess
    try:
        rc = subprocess.run([str(path), "-version"], capture_output=True,
                            timeout=15, creationflags=0x08000000).returncode
        return rc == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def rotate(path, limit=1_000_000):
    try:
        if path.exists() and path.stat().st_size > limit:
            old = path.with_name(path.name + ".old")
            if old.exists():
                old.unlink()
            path.replace(old)
    except OSError:
        pass


def setup_logging():
    rotate(LOG_PATH)
    logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
