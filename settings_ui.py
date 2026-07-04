import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import common
import winutil

MODKEYS = {"Shift_L": "shift", "Shift_R": "shift", "Control_L": "ctrl",
           "Control_R": "ctrl", "Alt_L": "alt", "Alt_R": "alt"}
ORDER = ("ctrl", "shift", "alt")
PRETTY = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt"}
QUAL_LABELS = {"low": "Low (8 Mbps cap)", "medium": "Medium (15 Mbps cap)",
               "high": "High (25 Mbps cap)"}


def keyname(keysym):
    if len(keysym) == 1:
        return keysym.upper()
    return {"space": "Space", "Prior": "PageUp", "Next": "PageDown",
            "Return": "Enter", "Caps_Lock": "CapsLock"}.get(keysym, keysym)


class SettingsWin:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.outputs = winutil.list_outputs()
        self.hotkey = dict(cfg["hotkey"])
        self.capturing = False
        self.held = set()

        root.title("Povtoritel Settings")
        root.resizable(False, False)
        frm = ttk.Frame(root, padding=14)
        frm.grid(sticky="nsew")

        labels = ["Screen:", "Keep last:", "Frame rate:", "Quality:",
                  "Save hotkey:", "Save folder:"]
        for i, text in enumerate(labels):
            ttk.Label(frm, text=text).grid(row=i, column=0, sticky="w",
                                           padx=(0, 10), pady=4)

        screen_names = []
        for i, o in enumerate(self.outputs):
            tag = " (primary)" if o["primary"] else ""
            screen_names.append(f"{i + 1}: {o['w']}x{o['h']}{tag}")
        if not screen_names:
            screen_names = ["1: default screen"]
        self.screen_box = ttk.Combobox(frm, values=screen_names,
                                       state="readonly", width=28)
        cur = 0
        for i, o in enumerate(self.outputs):
            if (o["adapter"] == cfg["screen"].get("adapter")
                    and o["output"] == cfg["screen"].get("output")):
                cur = i
        self.screen_box.current(cur)
        self.screen_box.grid(row=0, column=1, columnspan=2, sticky="w", pady=4)

        self.minutes = tk.IntVar(value=int(cfg["minutes"]))
        box = ttk.Frame(frm)
        box.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Spinbox(box, from_=1, to=10, textvariable=self.minutes,
                    width=4, state="readonly").pack(side="left")
        ttk.Label(box, text="minutes (1-10)").pack(side="left", padx=6)

        self.fps = tk.StringVar(value=str(cfg["fps"]))
        ttk.Combobox(frm, values=["30", "60", "120", "144"],
                     textvariable=self.fps, state="readonly",
                     width=6).grid(row=2, column=1, sticky="w", pady=4)

        self.quality = tk.StringVar(value=QUAL_LABELS.get(cfg["quality"],
                                                          QUAL_LABELS["medium"]))
        ttk.Combobox(frm, values=list(QUAL_LABELS.values()),
                     textvariable=self.quality, state="readonly",
                     width=22).grid(row=3, column=1, sticky="w", pady=4)

        self.hk_var = tk.StringVar(value=self.hotkey["label"])
        self.hk_entry = ttk.Entry(frm, textvariable=self.hk_var,
                                  state="readonly", width=22, cursor="hand2")
        self.hk_entry.grid(row=4, column=1, sticky="w", pady=4)
        self.hk_entry.bind("<Button-1>", self._hk_start)
        self.hk_entry.bind("<KeyPress>", self._hk_press)
        self.hk_entry.bind("<KeyRelease>", self._hk_release)
        self.hk_entry.bind("<FocusOut>", self._hk_cancel)
        self.hk_hint = ttk.Label(frm, text="click, then press keys",
                                 foreground="#777777")
        self.hk_hint.grid(row=4, column=2, sticky="w", padx=6)

        self.folder = tk.StringVar(value=cfg["folder"])
        ttk.Entry(frm, textvariable=self.folder, width=34).grid(
            row=5, column=1, sticky="w", pady=4)
        ttk.Button(frm, text="Browse", command=self._browse).grid(
            row=5, column=2, sticky="w", padx=6)

        self.audio = tk.BooleanVar(value=bool(cfg.get("audio", True)))
        ttk.Checkbutton(frm, text="Record desktop audio",
                        variable=self.audio).grid(row=6, column=1,
                                                  sticky="w", pady=(8, 0))

        self.priority = tk.BooleanVar(value=bool(cfg.get("capture_priority", True)))
        ttk.Checkbutton(frm, text="High capture priority (smoother under GPU load)",
                        variable=self.priority).grid(row=7, column=1,
                                                     columnspan=2, sticky="w")

        self.autostart = tk.BooleanVar(value=bool(cfg["autostart"]))
        ttk.Checkbutton(frm, text="Start with Windows",
                        variable=self.autostart).grid(row=8, column=1,
                                                      sticky="w", pady=(0, 2))

        ttk.Label(frm, text="Changes apply live. Capture restarts if screen,"
                            " FPS, quality or audio change.",
                  foreground="#777777").grid(row=9, column=0, columnspan=3,
                                             sticky="w", pady=(8, 2))

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=root.destroy).pack(side="left")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if d:
            self.folder.set(str(Path(d)))

    def _hk_start(self, _ev=None):
        self.capturing = True
        self.held.clear()
        self.hk_var.set("press keys...")
        self.hk_hint.config(text="modifiers wait for a key, Esc cancels")
        self.hk_entry.focus_set()
        return "break"

    def _hk_cancel(self, _ev=None):
        if self.capturing:
            self.capturing = False
            self.held.clear()
            self.hk_var.set(self.hotkey["label"])
            self.hk_hint.config(text="click, then press keys")

    def _hk_press(self, ev):
        if not self.capturing:
            return "break"
        if ev.keysym in MODKEYS:
            self.held.add(MODKEYS[ev.keysym])
            mods = [PRETTY[m] for m in ORDER if m in self.held]
            self.hk_var.set("+".join(mods) + "+...")
            return "break"
        if ev.keysym == "Escape":
            self._hk_cancel()
            return "break"
        vk = int(ev.keycode)
        if vk <= 0:
            return "break"
        mods = [m for m in ORDER if m in self.held]
        label = "+".join([PRETTY[m] for m in mods] + [keyname(ev.keysym)])
        self.hotkey = {"mods": mods, "vk": vk, "label": label}
        self.capturing = False
        self.held.clear()
        self.hk_var.set(label)
        self.hk_hint.config(text="click, then press keys")
        self.root.focus()
        return "break"

    def _hk_release(self, ev):
        if self.capturing and ev.keysym in MODKEYS:
            self.held.discard(MODKEYS[ev.keysym])
            if not self.held:
                self.hk_var.set("press keys...")
        return "break"

    def _save(self):
        folder = self.folder.get().strip()
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Povtoritel", f"Bad folder: {e}")
            return
        if self.outputs:
            o = self.outputs[self.screen_box.current()]
            self.cfg["screen"] = {"adapter": o["adapter"], "output": o["output"],
                                  "vendor": o["vendor"]}
        qual = {v: k for k, v in QUAL_LABELS.items()}[self.quality.get()]
        self.cfg["minutes"] = max(1, min(10, int(self.minutes.get())))
        self.cfg["fps"] = int(self.fps.get())
        self.cfg["quality"] = qual
        self.cfg["hotkey"] = dict(self.hotkey)
        self.cfg["folder"] = folder
        self.cfg["audio"] = bool(self.audio.get())
        self.cfg["capture_priority"] = bool(self.priority.get())
        self.cfg["autostart"] = bool(self.autostart.get())
        common.save_cfg(self.cfg)
        if self.cfg["autostart"]:
            winutil.set_autostart(common.startup_cmd())
        else:
            winutil.remove_autostart()
        if not winutil.post_to_running(winutil.MSG_RELOAD):
            subprocess.Popen([common.pythonw(), str(common.SCRIPT)])
        self.root.destroy()


def run(selftest=False):
    winutil.set_dpi_aware()
    root = tk.Tk()
    cfg = common.load_cfg()
    SettingsWin(root, cfg)
    if selftest:
        root.update()
        root.destroy()
        print("UI OK")
        return
    root.mainloop()
