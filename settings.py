"""Arctis OLED settings: pick the visualization, tweak options, watch a live preview.

The preview uses the real Arctis loopback audio (same as the base) and falls back to a demo
signal when nothing is playing. "Apply" writes config.json; spectrum.py re-reads it within ~2 s.
App preferences (language, tray) live in app.json. One instance only: a second launch shows the window.
Run: .venv\\Scripts\\pythonw.exe settings.py [--tray] [--demo] [--lang=en|ru] [--shot]
  --tray  start hidden in the tray        --demo  preview from the demo signal only
  --shot  save settings_shot.png after 3 s and exit (tests)
"""
import ctypes
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

import numpy as np
from PIL import Image, ImageDraw, ImageGrab, ImageTk

import spectrum as s
from i18n import LANGS, set_lang, t
from preview_styles import fake_audio

VERSION = "1.1.0"
REPO_URL = "https://github.com/Nexus-Nexx/arctis-nova-pro-oled"
SUPPORT_URL = ""  # donation page; the heart button stays hidden while this is empty

HERE = s.HERE
CFG_PATH = os.path.join(HERE, "config.json")
APP_PATH = os.path.join(HERE, "app.json")
PYW = os.path.join(HERE, ".venv", "Scripts", "pythonw.exe")
STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
SVC_LNK = os.path.join(STARTUP, "Arctis OLED Spectrum.lnk")
APP_LNK = os.path.join(STARTUP, "Arctis OLED Settings.lnk")
STYLE_KEYS = ("auto",) + s.Renderer.STYLES
IDLE_KEYS = ("battery", "clock", "blank")
APP_DEFAULTS = {"language": "auto", "tray": True}
SCALE = 4
IPC_PORT = 47812
NO_WINDOW = 0x08000000
BG, PANEL, FG, DIM, ACC, HEART = "#1b1c21", "#25272e", "#e8e8ee", "#8a8c96", "#f5b83d", "#ff6b81"


# ---------- files ----------
def read_json(path, defaults):
    try:
        with open(path, encoding="utf-8") as f:
            return {**defaults, **json.load(f)}
    except (OSError, ValueError):
        return dict(defaults)


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic: spectrum.py never reads a half-written file


def load_cfg():
    return read_json(CFG_PATH, s.DEFAULTS)


def set_shortcut(path, on, script, args=""):
    """Startup-folder shortcut -> pythonw <script> (no admin rights needed)."""
    if not on:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:PYW;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:DIR;$s.Save()")
    env = {**os.environ, "LNK": path, "PYW": PYW, "DIR": HERE,
           "ARGS": f'"{os.path.join(HERE, script)}" {args}'.strip()}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, creationflags=NO_WINDOW, check=False)


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


# ---------- single instance ----------
def ping_running_instance():
    try:
        with socket.create_connection(("127.0.0.1", IPC_PORT), timeout=0.5) as c:
            c.sendall(b"show")
        return True
    except OSError:
        return False


class IpcServer(threading.Thread):
    def __init__(self, on_show):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", IPC_PORT))
        self.sock.listen(2)
        self.on_show = on_show

    def run(self):
        while True:
            try:
                c, _ = self.sock.accept()
                with c:
                    if c.recv(16).startswith(b"show"):
                        self.on_show()
            except OSError:
                return


# ---------- preview ----------
class FakeEv:
    battery, spare, connected, volume = 8, 8, True, None

    def overlay_active(self):
        return False


class Source:
    """Live loopback audio when something plays, demo signal otherwise."""
    force_demo = "--demo" in sys.argv  # screenshots without your current track

    def __init__(self):
        self.audio = None
        try:
            self.audio = s.Loopback()
        except Exception:
            pass
        self.an = s.Analyzer(self.audio.rate if self.audio else 48000)
        self.rng = np.random.default_rng()
        self.t = 0

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


# ---------- tray ----------
def tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 61, 61], radius=12, fill=(27, 28, 33, 255))
    for i, h in enumerate((22, 38, 30, 46, 26)):
        x = 9 + i * 10
        d.rectangle([x, 54 - h, x + 6, 54], fill=(245, 184, 61, 255))
    return img


class Tray:
    """pystray runs in its own thread; every action is queued to the Tk thread."""

    def __init__(self, app):
        import pystray
        from pystray import Menu, MenuItem as Item

        def send(*msg):
            return lambda: app.q.put(msg)

        def style_item(k):
            return Item(lambda _i: t("style." + k), send("style", k),
                        checked=lambda _i: app.saved.get("style") == k, radio=True)

        menu = Menu(
            Item(lambda _i: t("tray.open"), send("show"), default=True),
            Item(lambda _i: t("tray.style"), Menu(*[style_item(k) for k in STYLE_KEYS])),
            Item(lambda _i: t("tray.svc_stop") if app.svc_on else t("tray.svc_start"), send("svc")),
            Menu.SEPARATOR,
            Item(lambda _i: t("tray.exit"), send("exit")),
        )
        self.icon = pystray.Icon("arctis_oled", tray_image(), "Arctis OLED", menu)
        self.icon.run_detached()

    def refresh(self):
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def notify(self, text):
        try:
            self.icon.notify(text, "Arctis OLED")
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass


# ---------- app ----------
class App:
    def __init__(self, root, opts):
        self.root, self.opts = root, opts
        self.prefs = read_json(APP_PATH, APP_DEFAULTS)
        set_lang(opts.lang or self.prefs["language"])
        self.saved = load_cfg()
        self.src = Source()
        self.rend = s.Renderer()
        self.rend.vu = np.zeros(2)
        self.now = s.NowPlaying()
        try:
            self.now.start()
        except Exception:
            pass
        self.q = queue.Queue()
        self.hidden, self.notified, self.tray, self.svc_on = False, opts.tray, None, service_running()
        self._theme()
        self._build()
        self._load_vars(self.saved)
        self._place_window()
        if self.prefs["tray"] or opts.tray:
            self._start_tray()
        if opts.tray:
            self.hidden = True
        else:
            root.deiconify()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Unmap>", self._on_unmap)
        self.tick()
        self.poll_service()
        self.pump()
        if opts.shot:
            root.after(3000, self.take_shot)

    # ---------- theme / layout ----------
    def _theme(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor="#383a43",
                     lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, focuscolor=ACC, font=("Segoe UI", 10))
        st.configure("TLabelframe", background=BG, bordercolor="#383a43")
        st.configure("TLabelframe.Label", background=BG, foreground=ACC, font=("Segoe UI Semibold", 10))
        st.configure("Dim.TLabel", foreground=DIM)
        st.configure("Status.TLabel", foreground=DIM, font=("Segoe UI", 9))
        st.configure("TSeparator", background="#383a43")
        for w in ("TRadiobutton", "TCheckbutton"):
            st.configure(w, background=BG, foreground=FG, indicatorbackground=PANEL, indicatorforeground=ACC)
            st.map(w, background=[("active", BG)], indicatorbackground=[("selected", PANEL)],
                   foreground=[("disabled", DIM)])
        st.configure("TButton", background=PANEL, foreground=FG, padding=(12, 5))
        st.map("TButton", background=[("active", "#323540"), ("disabled", BG)], foreground=[("disabled", "#555")])
        st.configure("Accent.TButton", background=ACC, foreground="#141414", font=("Segoe UI Semibold", 10))
        st.map("Accent.TButton", background=[("active", "#ffc95a"), ("disabled", "#3d3628")],
               foreground=[("disabled", "#6b6250")])
        st.configure("Heart.TButton", foreground=HEART)
        st.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        st.configure("TSpinbox", fieldbackground=PANEL, foreground=FG, arrowcolor=FG, insertcolor=FG)
        st.configure("TCombobox", fieldbackground=PANEL, foreground=FG, background=PANEL, arrowcolor=FG)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        st.configure("Horizontal.TScale", background=ACC, troughcolor="#3a3d47", bordercolor=BG,
                     lightcolor=ACC, darkcolor=ACC, sliderlength=12, gripcount=0)
        for k, v in (("background", PANEL), ("foreground", FG), ("selectBackground", ACC),
                     ("selectForeground", "#141414")):
            self.root.option_add(f"*TCombobox*Listbox.{k}", v)
        self.root.configure(bg=BG)
        try:
            self.root.iconphoto(True, ImageTk.PhotoImage(tray_image()))
        except Exception:
            pass

    def _build(self):
        r = self.root
        r.title(t("title"))
        self.scale = max(2, round(4 * r.winfo_fpixels("1i") / 96))
        self.outer = outer = ttk.Frame(r, padding=14)
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
        ttk.Checkbutton(info, text=t("pv.idle"), variable=self.idle_prev).pack(anchor="w", pady=(4, 0))
        svc = ttk.LabelFrame(left, text=t("svc.title"), padding=10)
        svc.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.svc_lbl = ttk.Label(svc)
        self.svc_lbl.pack(side="left")
        self.svc_btn = ttk.Button(svc, command=self.toggle_service)
        self.svc_btn.pack(side="right")
        tb = ttk.Frame(left)
        tb.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(tb, text="⚙  " + t("btn.settings"), command=self.open_prefs).pack(side="left")
        if SUPPORT_URL:
            ttk.Button(tb, text="♥  " + t("btn.support"), style="Heart.TButton",
                       command=lambda: webbrowser.open(SUPPORT_URL)).pack(side="left", padx=8)

        # right: settings column, scrolls when the screen is too short; buttons stay pinned below
        rcol = ttk.Frame(outer)
        rcol.grid(row=0, column=1, sticky="ns")
        rcol.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(rcol, bg=BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(rcol, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0, column=0, sticky="ns")
        self.vsb.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.right = right = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=right, anchor="nw")
        right.bind("<Configure>", self._sync_scroll)
        self.canvas.bind("<Configure>", self._sync_scroll)
        r.bind_all("<MouseWheel>", self._wheel)

        sf = ttk.LabelFrame(right, text=t("grp.style"), padding=10)
        sf.pack(fill="x")
        self.style = tk.StringVar()
        for i, key in enumerate(STYLE_KEYS):
            rb = ttk.Radiobutton(sf, text=t("style." + key), value=key, variable=self.style, command=self.changed)
            if key == "auto":
                rb.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
            else:
                j = i - 1
                rb.grid(row=1 + j // 2, column=j % 2, sticky="w", padx=(0, 18), pady=1)

        af = ttk.LabelFrame(right, text=t("grp.auto"), padding=10)
        af.pack(fill="x", pady=(10, 0))
        self.auto_vars = {}
        for j, key in enumerate(s.Renderer.STYLES):
            v = tk.BooleanVar()
            self.auto_vars[key] = v
            ttk.Checkbutton(af, text=t("style." + key), variable=v, command=self.changed).grid(
                row=j // 3, column=j % 3, sticky="w", padx=(0, 12), pady=1)
        row = ttk.Frame(af)
        row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(row, text=t("auto.every")).pack(side="left")
        self.auto_min = tk.IntVar()
        ttk.Spinbox(row, from_=0, to=60, width=4, textvariable=self.auto_min, command=self.changed).pack(side="left", padx=6)
        ttk.Label(row, text=t("auto.min_hint"), style="Dim.TLabel").pack(side="left")

        vf = ttk.LabelFrame(right, text=t("grp.look"), padding=10)
        vf.pack(fill="x", pady=(10, 0))
        ttk.Label(vf, text=t("look.sens")).grid(row=0, column=0, sticky="w")
        self.range_db = tk.IntVar()
        ttk.Scale(vf, from_=60, to=20, variable=self.range_db, length=170,
                  command=lambda _=None: (self.range_db.set(round(self.range_db.get())), self.changed())).grid(
            row=0, column=1, padx=8)
        self.range_lbl = ttk.Label(vf, width=14, style="Dim.TLabel")
        self.range_lbl.grid(row=0, column=2, sticky="w")
        self.strip = tk.BooleanVar()
        ttk.Checkbutton(vf, text=t("look.strip"), variable=self.strip, command=self.changed).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.strip_text = tk.StringVar()
        ttk.Entry(vf, textvariable=self.strip_text, width=11).grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.show_battery = tk.BooleanVar()
        ttk.Checkbutton(vf, text=t("look.battery"), variable=self.show_battery, command=self.changed).grid(
            row=2, column=0, sticky="w", pady=(2, 0))
        self.show_clock = tk.BooleanVar()
        ttk.Checkbutton(vf, text=t("look.clock"), variable=self.show_clock, command=self.changed).grid(
            row=2, column=1, sticky="w", pady=(2, 0))
        ttk.Label(vf, text=t("look.strip_hint"), style="Dim.TLabel").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(vf, text=t("look.bright")).grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.brightness = tk.IntVar()
        ttk.Scale(vf, from_=1, to=10, variable=self.brightness, length=170,
                  command=lambda _=None: (self.brightness.set(round(self.brightness.get())), self.changed())).grid(
            row=4, column=1, padx=8, pady=(8, 0))
        self.bright_lbl = ttk.Label(vf, width=14, style="Dim.TLabel")
        self.bright_lbl.grid(row=4, column=2, sticky="w", pady=(8, 0))
        self.care = tk.BooleanVar()
        ttk.Checkbutton(vf, text=t("look.care"), variable=self.care, command=self.changed).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(vf, text=t("look.care_hint"), style="Dim.TLabel").grid(row=6, column=0, columnspan=3, sticky="w")

        idf = ttk.LabelFrame(right, text=t("grp.idle"), padding=10)
        idf.pack(fill="x", pady=(10, 0))
        ttk.Label(idf, text=t("idle.after")).grid(row=0, column=0, sticky="w")
        self.idle = tk.StringVar()
        self.idle_cb = cb = ttk.Combobox(idf, state="readonly", width=18, values=[t("idle." + k) for k in IDLE_KEYS])
        cb.grid(row=0, column=1, sticky="w", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: (self.idle.set(IDLE_KEYS[cb.current()]), self.changed()))
        ttk.Label(idf, text=t("idle.off")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.blank = tk.IntVar()
        rowb = ttk.Frame(idf)
        rowb.grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))
        ttk.Spinbox(rowb, from_=1, to=120, width=4, textvariable=self.blank, command=self.changed).pack(side="left")
        ttk.Label(rowb, text=t("min"), style="Dim.TLabel").pack(side="left", padx=4)

        bf = ttk.Frame(rcol)
        bf.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.apply_btn = ttk.Button(bf, text=t("btn.apply"), style="Accent.TButton", command=self.apply)
        self.apply_btn.pack(side="right")
        self.revert_btn = ttk.Button(bf, text=t("btn.revert"), command=self.revert)
        self.revert_btn.pack(side="right", padx=8)
        self.state_lbl = ttk.Label(bf, style="Status.TLabel")
        self.state_lbl.pack(side="left")

        for v in (self.auto_min, self.blank, self.strip_text):
            v.trace_add("write", lambda *_: self.changed())
        self._paint_service()

    def _place_window(self):
        """First size: everything visible if the screen allows, otherwise fit the screen."""
        r = self.root
        r.update_idletasks()
        self.canvas.configure(width=self.right.winfo_reqwidth(), height=self.right.winfo_reqheight())
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w = min(r.winfo_reqwidth(), int(sw * 0.95))
        h = min(r.winfo_reqheight(), int(sh * 0.88))
        r.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        r.minsize(min(w, self.right.winfo_reqwidth() + s.W * 2 + 80), min(h, 360))

    def rebuild(self):
        """Language switch: redraw every widget, keep unsaved values."""
        c = self.form()
        self.outer.destroy()
        self._build()
        self._load_vars(c)
        if self.tray:
            self.tray.refresh()

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

    # ---------- config ----------
    def _load_vars(self, c):
        self.style.set(c.get("style", "bars"))
        pool = c.get("auto_styles") or list(s.Renderer.STYLES)
        for k, v in self.auto_vars.items():
            v.set(k in pool)
        self.auto_min.set(int(c.get("auto_minutes", 3) or 0))
        self.range_db.set(int(c.get("range_db", 35)))
        self.strip.set(bool(c.get("strip", True)))
        self.strip_text.set(str(c.get("strip_text", "")))
        self.show_battery.set(bool(c.get("show_battery", True)))
        self.show_clock.set(bool(c.get("show_clock", False)))
        idle = c.get("idle", "battery")
        self.idle.set(idle if idle in IDLE_KEYS else "battery")
        self.idle_cb.current(IDLE_KEYS.index(self.idle.get()))
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
        if not hasattr(self, "apply_btn"):
            return
        rd = self._int(self.range_db, 35, 20, 60)
        note = t("look.punchy") if rd < 30 else t("look.flat") if rd > 45 else ""
        self.range_lbl.config(text=f"{t('look.db', db=rd)}  {note}")
        self.bright_lbl.config(text=t("look.bright_val", v=self._int(self.brightness, 7, 1, 10)))
        dirty = self.form() != self.saved
        self.apply_btn.state(["!disabled"] if dirty else ["disabled"])
        self.revert_btn.state(["!disabled"] if dirty else ["disabled"])
        self.state_lbl.config(text=t("st.dirty") if dirty else t("st.saved"), foreground=ACC if dirty else DIM)

    def apply(self):
        c = self.form()
        write_json(CFG_PATH, c)
        self.saved = c
        self.changed()
        self.state_lbl.config(text=t("st.applied"), foreground=ACC)
        if self.tray:
            self.tray.refresh()

    def revert(self):
        self.saved = load_cfg()
        self._load_vars(self.saved)

    def quick_style(self, key):
        """Tray menu: switch style on the base right away, keep other unsaved edits in the window."""
        disk = load_cfg()
        disk["style"] = key
        write_json(CFG_PATH, disk)
        self.saved = disk
        self.style.set(key)
        self.changed()
        if self.tray:
            self.tray.refresh()

    # ---------- preferences dialog ----------
    def open_prefs(self):
        d = tk.Toplevel(self.root)
        d.withdraw()
        d.title(t("dlg.title"))
        d.configure(bg=BG)
        d.resizable(False, False)
        d.transient(self.root)
        f = ttk.Frame(d, padding=16)
        f.pack(fill="both", expand=True)
        codes = ["auto"] + list(LANGS)
        ttk.Label(f, text=t("dlg.lang")).grid(row=0, column=0, sticky="w")
        lang = ttk.Combobox(f, state="readonly", width=18, values=[t("dlg.lang_auto")] + list(LANGS.values()))
        lang.current(codes.index(self.prefs["language"]) if self.prefs["language"] in codes else 0)
        lang.grid(row=0, column=1, sticky="w", padx=(10, 0))
        tray = tk.BooleanVar(value=bool(self.prefs["tray"]))
        app_start = tk.BooleanVar(value=os.path.exists(APP_LNK))
        svc_start = tk.BooleanVar(value=os.path.exists(SVC_LNK))
        for i, (var, key) in enumerate(((tray, "dlg.tray"), (app_start, "dlg.app_start"),
                                        (svc_start, "dlg.svc_start")), 1):
            ttk.Checkbutton(f, text=t(key), variable=var).grid(
                row=i, column=0, columnspan=2, sticky="w", pady=(12 if i == 1 else 4, 0))
        ttk.Separator(f).grid(row=4, column=0, columnspan=2, sticky="ew", pady=14)
        about = ttk.Frame(f)
        about.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(about, text=t("dlg.about", v=VERSION), style="Dim.TLabel").pack(side="left")
        ttk.Button(about, text=t("dlg.github"), command=lambda: webbrowser.open(REPO_URL)).pack(side="right")
        bf = ttk.Frame(f)
        bf.grid(row=6, column=0, columnspan=2, sticky="e", pady=(16, 0))

        def ok():
            new_lang = codes[lang.current()]
            lang_changed = new_lang != self.prefs["language"]
            self.prefs.update(language=new_lang, tray=tray.get())
            write_json(APP_PATH, self.prefs)
            set_shortcut(APP_LNK, app_start.get(), "settings.py", "--tray")
            set_shortcut(SVC_LNK, svc_start.get(), "spectrum.py")
            if tray.get() and not self.tray:
                self._start_tray()
            elif not tray.get() and self.tray:
                self.tray.stop()
                self.tray = None
            d.destroy()
            if lang_changed:
                set_lang(new_lang)
                self.rebuild()

        ttk.Button(bf, text=t("dlg.cancel"), command=d.destroy).pack(side="right")
        ttk.Button(bf, text=t("dlg.ok"), style="Accent.TButton", command=ok).pack(side="right", padx=(0, 8))
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_reqheight()) // 3
        d.geometry(f"+{max(0, x)}+{max(0, y)}")
        d.deiconify()
        d.grab_set()
        d.focus_force()

    # ---------- tray / window ----------
    def _start_tray(self):
        try:
            self.tray = Tray(self)
        except Exception:
            self.tray = None

    def pump(self):
        """Handle tray / second-instance requests on the Tk thread."""
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "show":
                    self.show()
                elif msg[0] == "style":
                    self.quick_style(msg[1])
                elif msg[0] == "svc":
                    self.toggle_service()
                elif msg[0] == "exit":
                    self.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def on_close(self):
        if self.tray and self.prefs["tray"]:
            self.hide()
        else:
            self.quit()

    def _on_unmap(self, e):
        if e.widget is self.root and self.tray and self.prefs["tray"] and self.root.state() == "iconic":
            self.root.after(10, self.hide)

    def hide(self):
        self.root.withdraw()
        self.hidden = True
        if self.tray and not self.notified:
            self.tray.notify(t("tray.hint"))
            self.notified = True

    def show(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()
        self.hidden = False

    def quit(self):
        if self.tray:
            self.tray.stop()
        self.src.close()
        self.root.destroy()

    # ---------- service ----------
    def _paint_service(self):
        self.svc_lbl.config(text=t("svc.on") if self.svc_on else t("svc.off"),
                            foreground="#6fdc8c" if self.svc_on else DIM)
        self.svc_btn.config(text=t("svc.stop") if self.svc_on else t("svc.start"))

    def poll_service(self):
        on = service_running()
        if on != self.svc_on:
            self.svc_on = on
            if self.tray:
                self.tray.refresh()
        self._paint_service()
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
        if self.hidden:  # nothing to draw in the tray, keep CPU idle
            self.root.after(300, self.tick)
            return
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
        self.src_lbl.config(text=t("pv.live") if live else t("pv.demo"))
        self.root.after(max(1, int(33 - (time.perf_counter() - t0) * 1000)), self.tick)

    def take_shot(self):
        r = self.root
        r.update()
        x, y = r.winfo_rootx(), r.winfo_rooty()
        ImageGrab.grab((x, y, x + r.winfo_width(), y + r.winfo_height())).save(self.opts.shot)
        self.quit()


class Opts:
    def __init__(self, argv):
        self.tray = "--tray" in argv
        self.shot = os.path.join(HERE, "settings_shot.png") if "--shot" in argv else None
        self.lang = next((a.split("=", 1)[1] for a in argv if a.startswith("--lang=")), None)


def main():
    opts = Opts(sys.argv[1:])
    if not opts.shot and ping_running_instance():
        return  # already running: the other instance shows its window
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    app = App(root, opts)
    if not opts.shot:
        try:
            IpcServer(lambda: app.q.put(("show",))).start()
        except OSError:
            pass
    if opts.shot:
        root.attributes("-topmost", True)
    root.mainloop()


if __name__ == "__main__":
    main()
