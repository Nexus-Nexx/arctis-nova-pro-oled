"""Arctis OLED settings: pick the visualization, tweak options, watch a live preview.

The preview uses the real Arctis loopback audio (same as the base) and switches to a demo
signal when nothing is playing. "Применить" writes config.json; spectrum.py re-reads it
within ~2 s, no restart needed.
Run: .venv\\Scripts\\pythonw.exe settings.py
  --shot  save settings_shot.png after 3 s and exit (tests)    --demo  preview from the demo signal only
"""
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageGrab, ImageTk

import spectrum as s
from preview_styles import fake_audio

HERE = s.HERE
CFG_PATH = os.path.join(HERE, "config.json")
PYW = os.path.join(HERE, ".venv", "Scripts", "pythonw.exe")
SCALE = 4
NAMES = {
    "auto": "Авто: смена по трекам", "bars": "Столбики", "blocks": "LED-сегменты", "mirror": "Зеркало",
    "mountain": "Горы", "wave": "Осциллограф", "waterfall": "Водопад", "radial": "Лучи",
    "scope": "Стерео-гониометр", "rings": "Кольца от бочки",
}
IDLE = {"battery": "Заряд батарей", "clock": "Большие часы", "blank": "Пустой экран"}
BG, PANEL, FG, DIM, ACC = "#1b1c21", "#25272e", "#e8e8ee", "#8a8c96", "#f5b83d"
NO_WINDOW = 0x08000000


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return {**s.DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(s.DEFAULTS)


def service_running():
    """spectrum.py holds 127.0.0.1:47811 as its single-instance lock."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 47811))
        return False
    except OSError:
        return True
    finally:
        sock.close()


STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs",
                           "Startup", "Arctis OLED Spectrum.lnk")


def autostart_enabled():
    return os.path.exists(STARTUP_LNK)


def set_autostart(on):
    """Shortcut in the user's Startup folder -> pythonw spectrum.py at logon (no admin rights needed)."""
    if not on:
        try:
            os.remove(STARTUP_LNK)
        except OSError:
            pass
        return
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:PYW;$s.Arguments='\"'+$env:SPEC+'\"';$s.WorkingDirectory=$env:DIR;$s.Save()")
    env = {**os.environ, "LNK": STARTUP_LNK, "PYW": PYW, "SPEC": os.path.join(HERE, "spectrum.py"), "DIR": HERE}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=NO_WINDOW, check=False)


class FakeEv:
    battery, spare, connected, volume = 8, 8, True, None

    def overlay_active(self):
        return False


class Source:
    """Live loopback audio when something plays, demo signal otherwise."""

    def __init__(self):
        self.audio = None
        try:
            self.audio = s.Loopback()
        except Exception:
            pass
        self.an = s.Analyzer(self.audio.rate if self.audio else 48000)
        self.rng = np.random.default_rng()
        self.t = 0

    force_demo = "--demo" in sys.argv  # screenshots without your current track

    def live(self):
        return not self.force_demo and bool(self.audio) and time.time() - self.audio.last_audio < 1.0

    def step(self, range_db):
        an = self.an
        if self.live():
            x = self.audio.samples()
            level, peak = an.step(x, range_db)
            wave, lr, rms = an.wave(x), an.scope(self.audio.stereo()), self.audio.rms
        else:
            raw, lr0, wave = fake_audio(self.t // 2, self.rng)  # ~120 BPM demo kick at 30 fps
            self.t += 1
            an.norm = raw
            an.level = np.maximum(raw, an.level * s.DECAY)
            rise = an.level >= an.peak
            an.peak[rise] = an.level[rise]
            an.peak[~rise] = np.maximum(an.peak[~rise] - 0.03, an.level[~rise])
            level, peak, lr, rms = an.level, an.peak, an.scope(lr0), (0.1, 0.07)
        return level, peak, wave, lr, an.beat(level), rms

    def close(self):
        if self.audio:
            try:
                self.audio.close()
            except Exception:
                pass


def oled_look(frame, bright=10, scale=SCALE):
    """Upscale with a pixel grid; on-pixel intensity follows the base brightness (1..10)."""
    big = np.kron(frame.astype(np.uint8), np.ones((scale, scale), dtype=np.uint8))
    if scale >= 3:
        big[scale - 1::scale, :] = 0
        big[:, scale - 1::scale] = 0
    rgb = np.empty(big.shape + (3,), dtype=np.uint8)
    rgb[:] = (6, 6, 10)
    k = 0.3 + 0.7 * (bright / 10)
    rgb[big > 0] = (int(235 * k), int(240 * k), int(255 * k))
    return Image.fromarray(rgb)


class App:
    def __init__(self, root, shot=None):
        self.root, self.shot = root, shot
        self.saved = load_cfg()
        self.src = Source()
        self.rend = s.Renderer()
        self.rend.vu = np.zeros(2)
        self.now = s.NowPlaying()
        try:
            self.now.start()
        except Exception:
            pass
        self._theme()
        self._build()
        self._load_vars(self.saved)
        self.tick()
        self.poll_service()
        root.protocol("WM_DELETE_WINDOW", self.close)
        if shot:
            root.after(3000, self.take_shot)

    # ---------- ui ----------
    def _theme(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        base = ("Segoe UI", 10)
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor="#383a43",
                     lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, focuscolor=ACC, font=base)
        st.configure("TLabelframe", background=BG, bordercolor="#383a43")
        st.configure("TLabelframe.Label", background=BG, foreground=ACC, font=("Segoe UI Semibold", 10))
        st.configure("Dim.TLabel", foreground=DIM)
        st.configure("Status.TLabel", foreground=DIM, font=("Segoe UI", 9))
        for w in ("TRadiobutton", "TCheckbutton"):
            st.configure(w, background=BG, foreground=FG, indicatorbackground=PANEL, indicatorforeground=ACC)
            st.map(w, background=[("active", BG)], indicatorbackground=[("selected", PANEL)],
                   foreground=[("disabled", DIM)])
        st.configure("TButton", background=PANEL, foreground=FG, padding=(12, 5))
        st.map("TButton", background=[("active", "#323540"), ("disabled", BG)], foreground=[("disabled", "#555")])
        st.configure("Accent.TButton", background=ACC, foreground="#141414", font=("Segoe UI Semibold", 10))
        st.map("Accent.TButton", background=[("active", "#ffc95a"), ("disabled", "#3d3628")],
               foreground=[("disabled", "#6b6250")])
        st.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        st.configure("TSpinbox", fieldbackground=PANEL, foreground=FG, arrowcolor=FG, insertcolor=FG)
        st.configure("TCombobox", fieldbackground=PANEL, foreground=FG, background=PANEL, arrowcolor=FG)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        st.configure("Horizontal.TScale", background=ACC, troughcolor="#3a3d47", bordercolor=BG,
                     lightcolor=ACC, darkcolor=ACC, sliderlength=12, gripcount=0)
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACC)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#141414")
        self.root.configure(bg=BG)

    def _build(self):
        r = self.root
        r.title("Arctis OLED — визуализация")
        dpi = r.winfo_fpixels("1i") / 96
        self.scale = max(2, round(4 * dpi))
        outer = ttk.Frame(r, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        # left: preview grows with the window (integer pixel scale, always centred)
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.pv_box = tk.Frame(left, bg="#000000", highlightthickness=2, highlightbackground="#383a43",
                               width=s.W * self.scale + 20, height=s.H * self.scale + 20)
        self.pv_box.grid(row=0, column=0, sticky="nsew")
        self.preview = tk.Label(self.pv_box, bg="#000000", bd=0)
        self.preview.place(relx=0.5, rely=0.5, anchor="center")
        self.pv_box.bind("<Configure>", self._fit_preview)
        info = ttk.Frame(left)
        info.grid(row=1, column=0, sticky="ew")
        self.src_lbl = ttk.Label(info, style="Status.TLabel")
        self.src_lbl.pack(anchor="w", pady=(6, 0))
        self.idle_prev = tk.BooleanVar(value=False)
        ttk.Checkbutton(info, text="Показать экран простоя", variable=self.idle_prev).pack(anchor="w", pady=(4, 0))
        svc = ttk.LabelFrame(left, text="Служба на базе", padding=10)
        svc.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.svc_lbl = ttk.Label(svc)
        self.svc_lbl.pack(side="left")
        self.svc_btn = ttk.Button(svc, command=self.toggle_service)
        self.svc_btn.pack(side="right")
        self.autostart = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(svc, text="Запускать с Windows", variable=self.autostart,
                        command=lambda: set_autostart(self.autostart.get())).pack(side="right", padx=12)

        # right: settings column, scrolls when the screen is too short; buttons stay pinned below
        rcol = ttk.Frame(outer)
        rcol.grid(row=0, column=1, sticky="ns")
        rcol.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(rcol, bg=BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(rcol, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0, column=0, sticky="ns")
        self.vsb.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        right = ttk.Frame(self.canvas)
        self.right = right
        self.canvas.create_window((0, 0), window=right, anchor="nw")
        right.bind("<Configure>", self._sync_scroll)
        self.canvas.bind("<Configure>", self._sync_scroll)
        r.bind_all("<MouseWheel>", self._wheel)

        sf = ttk.LabelFrame(right, text="Визуализация", padding=10)
        sf.pack(fill="x")
        self.style = tk.StringVar()
        order = ("auto",) + s.Renderer.STYLES
        for i, key in enumerate(order):
            rb = ttk.Radiobutton(sf, text=NAMES[key], value=key, variable=self.style, command=self.changed)
            if key == "auto":
                rb.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
            else:
                j = i - 1
                rb.grid(row=1 + j // 2, column=j % 2, sticky="w", padx=(0, 18), pady=1)

        af = ttk.LabelFrame(right, text="Авто-режим: что крутить", padding=10)
        af.pack(fill="x", pady=(10, 0))
        self.auto_vars = {}
        for j, key in enumerate(s.Renderer.STYLES):
            v = tk.BooleanVar()
            self.auto_vars[key] = v
            ttk.Checkbutton(af, text=NAMES[key], variable=v, command=self.changed).grid(
                row=j // 3, column=j % 3, sticky="w", padx=(0, 12), pady=1)
        row = ttk.Frame(af)
        row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(row, text="и ещё каждые").pack(side="left")
        self.auto_min = tk.IntVar()
        ttk.Spinbox(row, from_=0, to=60, width=4, textvariable=self.auto_min, command=self.changed).pack(side="left", padx=6)
        ttk.Label(row, text="мин (0 = только по трекам)", style="Dim.TLabel").pack(side="left")

        vf = ttk.LabelFrame(right, text="Вид", padding=10)
        vf.pack(fill="x", pady=(10, 0))
        ttk.Label(vf, text="Чувствительность").grid(row=0, column=0, sticky="w")
        self.range_db = tk.IntVar()
        ttk.Scale(vf, from_=60, to=20, variable=self.range_db, length=170,
                  command=lambda _=None: (self.range_db.set(round(self.range_db.get())), self.changed())).grid(
            row=0, column=1, padx=8)
        self.range_lbl = ttk.Label(vf, width=12, style="Dim.TLabel")
        self.range_lbl.grid(row=0, column=2, sticky="w")
        self.strip = tk.BooleanVar()
        ttk.Checkbutton(vf, text="Нижняя полоса с ником и VU", variable=self.strip, command=self.changed).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.strip_text = tk.StringVar()
        self.strip_text.trace_add("write", lambda *_: self.changed())
        ttk.Entry(vf, textvariable=self.strip_text, width=11).grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.show_battery = tk.BooleanVar()
        ttk.Checkbutton(vf, text="Батарея в шапке", variable=self.show_battery, command=self.changed).grid(
            row=2, column=0, sticky="w", pady=(2, 0))
        self.show_clock = tk.BooleanVar()
        ttk.Checkbutton(vf, text="Часы в шапке", variable=self.show_clock, command=self.changed).grid(
            row=2, column=1, sticky="w", pady=(2, 0))
        ttk.Label(vf, text="Ник: латиница, цифры, до 10 знаков", style="Dim.TLabel").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(vf, text="Яркость").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.brightness = tk.IntVar()
        ttk.Scale(vf, from_=1, to=10, variable=self.brightness, length=170,
                  command=lambda _=None: (self.brightness.set(round(self.brightness.get())), self.changed())).grid(
            row=4, column=1, padx=8, pady=(8, 0))
        self.bright_lbl = ttk.Label(vf, width=12, style="Dim.TLabel")
        self.bright_lbl.grid(row=4, column=2, sticky="w", pady=(8, 0))
        self.care = tk.BooleanVar()
        ttk.Checkbutton(vf, text="Бережный режим OLED", variable=self.care, command=self.changed).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(vf, text="сдвиг картинки раз в минуту, экран простоя в 3 раза тусклее",
                  style="Dim.TLabel").grid(row=6, column=0, columnspan=3, sticky="w")

        idf = ttk.LabelFrame(right, text="Когда тихо", padding=10)
        idf.pack(fill="x", pady=(10, 0))
        ttk.Label(idf, text="Через 20 с показать").grid(row=0, column=0, sticky="w")
        self.idle = tk.StringVar()
        cb = ttk.Combobox(idf, state="readonly", width=16, values=list(IDLE.values()))
        cb.grid(row=0, column=1, sticky="w", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: (self.idle.set(self._idle_key(cb.get())), self.changed()))
        self.idle_cb = cb
        ttk.Label(idf, text="Гасить экран через").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.blank = tk.IntVar()
        rowb = ttk.Frame(idf)
        rowb.grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))
        ttk.Spinbox(rowb, from_=1, to=120, width=4, textvariable=self.blank, command=self.changed).pack(side="left")
        ttk.Label(rowb, text="мин", style="Dim.TLabel").pack(side="left", padx=4)

        bf = ttk.Frame(rcol)
        bf.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.apply_btn = ttk.Button(bf, text="Применить на базу", style="Accent.TButton", command=self.apply)
        self.apply_btn.pack(side="right")
        self.revert_btn = ttk.Button(bf, text="Отменить", command=self.revert)
        self.revert_btn.pack(side="right", padx=8)
        self.state_lbl = ttk.Label(bf, style="Status.TLabel")
        self.state_lbl.pack(side="left")

        for v in (self.auto_min, self.blank):
            v.trace_add("write", lambda *_: self.changed())

        # first size: everything visible if the screen allows, otherwise fit the screen
        r.update_idletasks()
        self.canvas.configure(width=right.winfo_reqwidth(), height=right.winfo_reqheight())
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w = min(r.winfo_reqwidth(), int(sw * 0.95))
        h = min(r.winfo_reqheight(), int(sh * 0.88))
        r.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        r.minsize(min(w, right.winfo_reqwidth() + s.W * 2 + 80), min(h, 360))

    # ---------- layout helpers ----------
    def _fit_preview(self, e):
        self.scale = max(1, min((e.width - 20) // s.W, (e.height - 20) // s.H))

    def _sync_scroll(self, _=None):
        rq_w, rq_h = self.right.winfo_reqwidth(), self.right.winfo_reqheight()
        self.canvas.configure(width=rq_w, scrollregion=(0, 0, rq_w, rq_h))
        if rq_h > self.canvas.winfo_height() + 1:
            self.vsb.grid()
        else:
            self.vsb.grid_remove()
            self.canvas.yview_moveto(0)

    def _wheel(self, e):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        if w is not None and str(w).startswith(str(self.canvas)) and self.vsb.winfo_ismapped():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    @staticmethod
    def _idle_key(label):
        return next((k for k, v in IDLE.items() if v == label), "battery")

    # ---------- config ----------
    def _load_vars(self, c):
        self.style.set(c.get("style", "bars"))
        pool = c.get("auto_styles") or list(s.Renderer.STYLES)
        for k, v in self.auto_vars.items():
            v.set(k in pool)
        self.auto_min.set(int(c.get("auto_minutes", 3) or 0))
        self.range_db.set(int(c.get("range_db", 35)))
        self.strip.set(bool(c.get("strip", True)))
        self.strip_text.set(str(c.get("strip_text", "NEXX")))
        self.show_battery.set(bool(c.get("show_battery", True)))
        self.show_clock.set(bool(c.get("show_clock", False)))
        self.idle.set(c.get("idle", "battery"))
        self.idle_cb.set(IDLE.get(self.idle.get(), IDLE["battery"]))
        self.blank.set(int(c.get("blank_after_minutes", 10)))
        self.brightness.set(int(c.get("brightness", 7)))
        self.care.set(bool(c.get("oled_care", True)))
        self.changed()

    @staticmethod
    def _int(var, default, lo, hi):
        try:
            return max(lo, min(hi, int(var.get())))
        except (tk.TclError, ValueError):
            return default

    def form(self):
        c = dict(self.saved)
        pool = [k for k, v in self.auto_vars.items() if v.get()]
        c.update({
            "style": self.style.get() or "bars",
            "auto_styles": [] if len(pool) in (0, len(self.auto_vars)) else pool,
            "auto_minutes": self._int(self.auto_min, 3, 0, 60),
            "range_db": self._int(self.range_db, 35, 20, 60),
            "strip": self.strip.get(),
            "strip_text": "".join(ch for ch in self.strip_text.get().upper() if ch in s.PIX5x7)[:10],
            "show_battery": self.show_battery.get(),
            "show_clock": self.show_clock.get(),
            "idle": self.idle.get() or "battery",
            "blank_after_minutes": self._int(self.blank, 10, 1, 120),
            "brightness": self._int(self.brightness, 7, 1, 10),
            "oled_care": self.care.get(),
        })
        return c

    def changed(self):
        rd = self._int(self.range_db, 35, 20, 60)
        self.range_lbl.config(text=f"{rd} дБ  {'ярче' if rd < 30 else 'ровнее' if rd > 45 else ''}")
        self.bright_lbl.config(text=f"{self._int(self.brightness, 7, 1, 10)} из 10")
        dirty = self.form() != self.saved
        self.apply_btn.state(["!disabled"] if dirty else ["disabled"])
        self.revert_btn.state(["!disabled"] if dirty else ["disabled"])
        self.state_lbl.config(text="есть изменения" if dirty else "сохранено", foreground=ACC if dirty else DIM)

    def apply(self):
        c = self.form()
        tmp = CFG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CFG_PATH)  # atomic: spectrum.py never reads a half-written file
        self.saved = c
        self.changed()
        self.state_lbl.config(text="применено, база обновится за ~2 с", foreground=ACC)

    def revert(self):
        self.saved = load_cfg()
        self._load_vars(self.saved)

    # ---------- service ----------
    def poll_service(self):
        on = service_running()
        self.svc_lbl.config(text="● работает" if on else "○ остановлена", foreground="#6fdc8c" if on else DIM)
        self.svc_btn.config(text="Остановить" if on else "Запустить")
        self.root.after(2000, self.poll_service)

    def toggle_service(self):
        if service_running():
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              os.path.join(HERE, "stop.ps1")], creationflags=NO_WINDOW)
        else:
            subprocess.Popen([PYW, os.path.join(HERE, "spectrum.py")], cwd=HERE,
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        self.svc_btn.state(["disabled"])
        self.root.after(2500, lambda: self.svc_btn.state(["!disabled"]))

    # ---------- preview loop ----------
    def tick(self):
        t0 = time.perf_counter()
        c = self.form()
        if c["style"] == "auto":
            c["auto_minutes"] = 4 / 60  # preview cycles every 4 s so the rotation is visible
        level, peak, wave, lr, beat, rms = self.src.step(float(c["range_db"]))
        live = self.src.live()
        text = (self.now.text if live else "") or "Artist - Track title"
        mode = "clock" if self.idle_prev.get() else "spectrum"
        if mode == "clock" and c["idle"] == "blank":
            mode = "blank"
        frame = self.rend.frame(c, mode, level, peak, wave, text, FakeEv(), rms, lr=lr, beat=beat)
        self.img = ImageTk.PhotoImage(oled_look(frame, s.target_brightness(c, mode), self.scale))
        self.preview.config(image=self.img)
        self.src_lbl.config(text="Источник: звук с Arctis (живой)" if live else
                            "Источник: демо-сигнал (музыка не играет)")
        self.root.after(max(1, int(33 - (time.perf_counter() - t0) * 1000)), self.tick)

    def take_shot(self):
        r = self.root
        r.update()
        x, y = r.winfo_rootx(), r.winfo_rooty()
        ImageGrab.grab((x, y, x + r.winfo_width(), y + r.winfo_height())).save(self.shot)
        self.close()

    def close(self):
        self.src.close()
        self.root.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    shot = None
    if "--shot" in sys.argv:
        shot = os.path.join(HERE, "settings_shot.png")
    root = tk.Tk()
    App(root, shot)
    if shot:
        root.attributes("-topmost", True)
    root.mainloop()


if __name__ == "__main__":
    main()
