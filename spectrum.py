r"""Spectrum analyzer + clock + now playing + battery on the Arctis Nova Pro base OLED.

Audio: WASAPI loopback of the Arctis output (post-Sonar mix). Media info: Windows SMTC.
Settings: config.json next to this file, re-read on the fly.
  style: bars | blocks | mirror | mountain | wave | waterfall | radial | scope | rings | auto
  auto: next style on every track change (and every auto_minutes); auto_styles = [] means all.
Run: .venv\Scripts\python.exe spectrum.py   (Ctrl+C restores the stock base UI)
"""
import asyncio
import json
import os
import signal
import socket
import sys
import threading
import time
from collections import deque

import numpy as np
import pyaudiowpatch as pyaudio
from PIL import Image, ImageDraw, ImageFont

from oled import Oled, W, H, find_device, find_paths, list_steelseries

def _data_dir():
    """Where config.json / logs live: the project folder, or next to ArctisOLED.exe
    (falls back to %APPDATA%\\ArctisOLED when the exe folder is read-only, e.g. Program Files)."""
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    d = os.path.dirname(sys.executable)
    try:
        probe = os.path.join(d, ".write_test")
        open(probe, "w").close()
        os.remove(probe)
        return d
    except OSError:
        d = os.path.join(os.environ.get("APPDATA", d), "ArctisOLED")
        os.makedirs(d, exist_ok=True)
        return d


HERE = _data_dir()
FFT_N = 2048
BANDS = 32               # 32 bars x 4 px = 128 px
F_LO, F_HI = 40, 16000
TOP = 12                 # header height (track + battery + clock)
BAR_H = H - TOP - 1      # spectrum area height
DECAY = 0.82             # bar fall per frame (multiplier)
PEAK_HOLD = 18           # frames a peak dot stays before falling
SILENCE_S = 20           # after this much silence show the big clock
FONT_SMALL = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 10)
FONT_BIG = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 30)
FONT_STRIP = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 9)
# 5x7 pixel font for the bottom strip (each glyph: 7 rows, 5 bits, MSB = left)
PIX5x7 = {
    "A": "0E 11 11 1F 11 11 11", "B": "1E 11 11 1E 11 11 1E", "C": "0E 11 10 10 10 11 0E",
    "D": "1E 11 11 11 11 11 1E", "E": "1F 10 10 1E 10 10 1F", "F": "1F 10 10 1E 10 10 10",
    "G": "0E 11 10 17 11 11 0F", "H": "11 11 11 1F 11 11 11", "I": "0E 04 04 04 04 04 0E",
    "J": "07 02 02 02 02 12 0C", "K": "11 12 14 18 14 12 11", "L": "10 10 10 10 10 10 1F",
    "M": "11 1B 15 15 11 11 11", "N": "11 11 19 15 13 11 11", "O": "0E 11 11 11 11 11 0E",
    "P": "1E 11 11 1E 10 10 10", "Q": "0E 11 11 11 15 12 0D", "R": "1E 11 11 1E 14 12 11",
    "S": "0F 10 10 0E 01 01 1E", "T": "1F 04 04 04 04 04 04", "U": "11 11 11 11 11 11 0E",
    "V": "11 11 11 11 11 0A 04", "W": "11 11 11 15 15 15 0A", "X": "11 11 0A 04 0A 11 11",
    "Y": "11 11 0A 04 04 04 04", "Z": "1F 01 02 04 08 10 1F", "0": "0E 11 13 15 19 11 0E",
    "1": "04 0C 04 04 04 04 0E", "2": "0E 11 01 02 04 08 1F", "3": "1F 02 04 02 01 11 0E",
    "4": "02 06 0A 12 1F 02 02", "5": "1F 10 1E 01 01 11 0E", "6": "06 08 10 1E 11 11 0E",
    "7": "1F 01 02 04 08 08 08", "8": "0E 11 11 0E 11 11 0E", "9": "0E 11 11 0F 01 02 0C",
    "-": "00 00 00 0E 00 00 00", ".": "00 00 00 00 00 0C 0C", " ": "00 00 00 00 00 00 00",
}


def pix_text_width(text, spacing=2):
    return len(text) * (5 + spacing) - spacing if text else 0


def pix_text(g, x, y, text, spacing=2):
    for ch in text:
        rows = PIX5x7.get(ch, PIX5x7[" "]).split()
        for ry, hx in enumerate(rows):
            v = int(hx, 16)
            for rx in range(5):
                if v & (0x10 >> rx):
                    g.point([x + rx, y + ry], fill=1)
        x += 5 + spacing


DEFAULTS = {"style": "bars", "range_db": 35, "fps": 30, "shift_minutes": 3,
            "blank_after_minutes": 10, "show_battery": True, "strip": True, "strip_text": "NOVA PRO",
            "show_clock": False, "idle": "battery", "auto_styles": [], "auto_minutes": 3,
            "brightness": 7, "oled_care": True}


def target_brightness(cfg, mode):
    """1..10. OLED care: idle screens (battery / clock) run at a third of the brightness."""
    b = max(1, min(10, int(cfg.get("brightness", 7))))
    return max(1, round(b / 3)) if cfg.get("oled_care") and mode != "spectrum" else b


class Config:
    def __init__(self):
        self.path = os.path.join(HERE, "config.json")
        self.data, self.mtime, self.checked = dict(DEFAULTS), 0, 0

    def get(self):
        if time.time() - self.checked > 2:
            self.checked = time.time()
            if not os.path.exists(self.path):  # fresh install: defaults until the settings app saves
                return self.data
            try:
                m = os.path.getmtime(self.path)
                if m != self.mtime:
                    with open(self.path, encoding="utf-8") as f:
                        self.data = {**DEFAULTS, **json.load(f)}
                    self.mtime = m
                    log(f"config: {self.data}")
            except (OSError, ValueError) as e:
                log(f"config error: {e!r} (keeping previous)")
                self.mtime = os.path.getmtime(self.path) if os.path.exists(self.path) else 0
        return self.data


# ---------------- audio ----------------
class Loopback:
    def __init__(self, match="Arctis"):
        self.pa = pyaudio.PyAudio()
        dev = None
        for lb in self.pa.get_loopback_device_info_generator():
            if match.lower() in lb["name"].lower():
                dev = lb
                break
        if dev is None:  # fall back to the default output's loopback
            dev = self.pa.get_default_wasapi_loopback()
        self.name = dev["name"]
        self.rate = int(dev["defaultSampleRate"])
        self.ch = dev["maxInputChannels"]
        self.buf = deque(maxlen=FFT_N * 2)
        self.last_audio = 0.0
        self.rms = np.zeros(2)
        self.lr = np.zeros((4096, 2), dtype=np.float32)  # stereo ring buffer for the scope style
        self.lr_pos = 0
        self.stream = self.pa.open(format=pyaudio.paFloat32, channels=self.ch, rate=self.rate, input=True,
                                   input_device_index=dev["index"], frames_per_buffer=512,
                                   stream_callback=self._cb)

    def _cb(self, data, frames, info, status):
        raw = np.frombuffer(data, dtype=np.float32).reshape(-1, self.ch)
        lr = raw[:, :2] if self.ch >= 2 else np.repeat(raw, 2, axis=1)
        self.rms = np.sqrt((lr ** 2).mean(axis=0))
        n, size = len(lr), len(self.lr)
        if n >= size:
            self.lr[:], self.lr_pos = lr[-size:], 0
        else:
            end = self.lr_pos + n
            if end <= size:
                self.lr[self.lr_pos:end] = lr
            else:
                k = size - self.lr_pos
                self.lr[self.lr_pos:], self.lr[:n - k] = lr[:k], lr[k:]
            self.lr_pos = end % size
        a = raw.mean(axis=1)
        if np.abs(a).max() > 1e-4:
            self.last_audio = time.time()
        self.buf.extend(a)
        return None, pyaudio.paContinue

    def samples(self, n=FFT_N):
        if len(self.buf) < n:
            return np.zeros(n, dtype=np.float32)
        return np.fromiter(self.buf, dtype=np.float32, count=len(self.buf))[-n:]

    def stereo(self, n=512):
        """Last n (L, R) sample pairs in time order."""
        return np.roll(self.lr, -self.lr_pos, axis=0)[-n:]

    def close(self):
        self.stream.stop_stream()
        self.stream.close()
        self.pa.terminate()


class Analyzer:
    def __init__(self, rate):
        self.win = np.hanning(FFT_N).astype(np.float32)
        freqs = np.fft.rfftfreq(FFT_N, 1 / rate)
        edges = np.geomspace(F_LO, F_HI, BANDS + 1)
        self.bins = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in zip(edges[:-1], edges[1:])]
        # bands narrower than one FFT bin borrow the nearest bin
        self.bins = [b if b.size else np.array([np.argmin(np.abs(freqs - lo))]) for b, lo in zip(self.bins, edges)]
        self.level = np.zeros(BANDS)
        self.peak = np.zeros(BANDS)
        self.peak_t = np.zeros(BANDS, dtype=int)
        self.ref_db = -20.0  # auto-gain reference
        self.wave_gain = 1.0
        self.scope_gain = 1e-3
        self.bass_avg, self.beat_cd = 0.0, 0
        self.norm = np.zeros(BANDS)

    def step(self, x, range_db):
        spec = np.abs(np.fft.rfft(x * self.win)) / FFT_N
        bands = np.array([spec[b].max() for b in self.bins])
        db = 20 * np.log10(bands + 1e-9)
        # slow auto-gain: follow the loudest band, never below -45 dB
        self.ref_db = max(-45.0, max(db.max(), self.ref_db - 0.15))
        norm = np.clip((db - (self.ref_db - range_db)) / range_db, 0, 1)
        self.norm = norm  # unsmoothed, for onset (kick) detection
        self.level = np.maximum(norm, self.level * DECAY)
        rise = self.level >= self.peak
        self.peak[rise] = self.level[rise]
        self.peak_t[rise] = PEAK_HOLD
        self.peak_t[~rise] -= 1
        fall = (~rise) & (self.peak_t <= 0)
        self.peak[fall] = np.maximum(self.peak[fall] - 0.03, self.level[fall])
        return self.level, self.peak

    def wave(self, x):
        """Oscilloscope: 128 points from the last ~20 ms, auto-gained to the area height."""
        seg = x[-1024:]
        pts = seg.reshape(W, -1).mean(axis=1)
        amp = np.abs(pts).max()
        self.wave_gain = max(amp, self.wave_gain * 0.97, 1e-3)
        return np.clip(pts / self.wave_gain, -1, 1)

    def beat(self, level):
        """Kick detector -> (smoothed bass 0..1, hit this frame). Onset = jump of the raw
        low-band level above its short average, so a constantly loud bass still triggers."""
        e = float(self.norm[:4].mean())
        hit = self.beat_cd <= 0 and e > 0.35 and e - self.bass_avg > 0.12
        self.bass_avg = self.bass_avg * 0.8 + e * 0.2
        self.beat_cd = 6 if hit else self.beat_cd - 1
        return float(level[:4].mean()), hit

    def scope(self, lr):
        """Stereo samples auto-gained to -1..1 for the goniometer."""
        amp = float(np.abs(lr).max()) if len(lr) else 0.0
        self.scope_gain = max(amp, self.scope_gain * 0.97, 1e-3)
        return np.clip(lr / self.scope_gain, -1, 1)


# ---------------- now playing (Windows SMTC) ----------------
class NowPlaying(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.text = ""
        self.playing = False

    async def _poll(self):
        from winsdk.windows.media.control import \
            GlobalSystemMediaTransportControlsSessionManager as Manager
        mgr = await Manager.request_async()
        while True:
            try:
                s = mgr.get_current_session()
                if s:
                    p = await s.try_get_media_properties_async()
                    self.playing = s.get_playback_info().playback_status == 4  # Playing
                    self.text = " - ".join(t for t in (p.artist, p.title) if t)
                else:
                    self.text, self.playing = "", False
            except Exception:
                pass
            await asyncio.sleep(2)

    def run(self):
        asyncio.run(self._poll())


# ---------------- base events: volume wheel, battery, connection ----------------
class BaseEvents(threading.Thread):
    """Info HID interface. Per ggoled: volume (0x07,0x25) = 0x38-buf[2]; battery levels 0..8:
    event (0x07,0xb7) buf[2]=headset buf[3]=spare; reply (0x06,0xb0) buf[6]/buf[7], wireless buf[15]==8;
    connection event (0x07,0xb5) wireless buf[4]==8."""
    VOL_MAX = 0x38

    def __init__(self, info_path, oled_path, profile=None):
        super().__init__(daemon=True)
        # Nova Pro on Windows: report 0x06 (query + 0xB0 reply) lives on the 0xFFC0 collection,
        # report 0x07 events (volume, battery, connection) on the 0xFF00 collection.
        # Nova Elite: query/reply use report 0x07 on the info collection (ggoled PR #35).
        self.paths = (info_path, oled_path)
        self.INFO_ID = profile.info_id if profile else 0x06
        self.query_on_info = bool(profile and profile.query_on_info)
        self.spare_battery = profile.spare_battery if profile else True
        self.volume, self.vol_t = None, 0.0
        self.battery = self.spare = None
        self.connected = None
        self.alive = True
        self._q = None

    def _query(self):
        self._q.write(bytes([self.INFO_ID, 0xB0]) + bytes(62))

    def run(self):
        import hid
        while self.alive:
            devs = []
            try:
                for p in self.paths:
                    d = hid.device()
                    d.open_path(p)
                    d.set_nonblocking(1)
                    devs.append(d)
                self._q = devs[0] if self.query_on_info else devs[1]
                last_q = 0
                while self.alive:
                    if time.time() - last_q > 60:
                        self._query()
                        last_q = time.time()
                    buf = devs[0].read(64) or devs[1].read(64)
                    if len(buf) < 3:
                        time.sleep(0.02)
                        continue
                    key = (buf[0], buf[1])
                    if key == (0x07, 0x25):
                        self.volume = max(0, min(self.VOL_MAX, self.VOL_MAX - buf[2])) / self.VOL_MAX
                        self.vol_t = time.time()
                    elif key == (0x07, 0xB7):
                        self.battery = buf[2]
                        if self.spare_battery:  # Nova Elite: byte 3 is a charging flag, not a spare
                            self.spare = buf[3]
                    elif key == (0x07, 0xB5):
                        self.connected = buf[4] == 8
                        self._query()
                    elif key == (self.INFO_ID, 0xB0) and len(buf) > 15:
                        self.connected = buf[15] == 8
                        self.battery = buf[6]
                        if self.spare_battery:
                            self.spare = buf[7]
                        log(f"base info: connected={self.connected} headset={self.battery}/8 spare={self.spare}/8 raw={bytes(buf[:16]).hex()}")
            except Exception:
                time.sleep(2)  # base unplugged / busy: retry
            finally:
                for d in devs:
                    d.close()

    def overlay_active(self):
        return self.volume is not None and time.time() - self.vol_t < 1.5


# ---------------- render ----------------
class Renderer:
    STYLES = ("bars", "blocks", "mirror", "mountain", "wave", "waterfall", "radial", "scope", "rings")
    BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16 + 1 / 32

    def __init__(self):
        self.scroll = 0
        self.last_text = ""
        self.wf, self.wf_t = None, 0          # waterfall history
        self.ring_r, self.flash = [], 0       # rings style, beat flash frames
        self.auto_i, self.auto_t, self.auto_track = 0, time.time(), None
        self.prev_style, self.label, self.label_t = None, "", 0.0

    @staticmethod
    def battery_icon(g, x, level, connected):
        """11x7 battery at (x,1); 4 segments from a 0..8 level; X when headset is off."""
        g.rectangle([x, 1, x + 9, 7], outline=1)
        g.rectangle([x + 10, 3, x + 10, 5], fill=1)
        if connected is False or level is None:
            g.line([x + 2, 2, x + 7, 6], fill=1)
            g.line([x + 2, 6, x + 7, 2], fill=1)
            return
        segs = min(4, (max(0, level) + 1) // 2)
        for s in range(segs):
            g.rectangle([x + 2 + s * 2, 3, x + 2 + s * 2, 5], fill=1)

    def header(self, g, text, ev, show_batt, show_clock=False):
        clock = time.strftime("%H:%M") if show_clock else ""
        cw = g.textlength(clock, font=FONT_SMALL) if clock else 0
        right = int(W - cw - 2) if clock else W - 1
        bx = right - 14 if show_batt else right
        area = bx - 2
        if text != self.last_text:
            self.last_text, self.scroll = text, 0
        tw = g.textlength(text, font=FONT_SMALL)
        if tw > area:  # marquee
            gap = 24
            off = self.scroll % (tw + gap)
            g.text((-off, 0), text, font=FONT_SMALL, fill=1)
            g.text((-off + tw + gap, 0), text, font=FONT_SMALL, fill=1)
            self.scroll += 1
        else:
            g.text((0, 0), text, font=FONT_SMALL, fill=1)
        g.rectangle([area, 0, W - 1, TOP - 2], fill=0)  # clean box for battery + clock
        if show_batt:
            self.battery_icon(g, bx, ev.battery, ev.connected)
        if clock:
            g.text((W - cw, 0), clock, font=FONT_SMALL, fill=1)
        g.line([0, TOP - 1, W - 1, TOP - 1], fill=1)

    @staticmethod
    def big_battery(g, x, y, level, label):
        """34x16 battery with 8 segments (level 0..8) and a caption under it."""
        g.rectangle([x, y, x + 31, y + 15], outline=1)
        g.rectangle([x + 32, y + 5, x + 33, y + 10], fill=1)
        if level is None:
            g.line([x + 6, y + 3, x + 25, y + 12], fill=1)
            g.line([x + 6, y + 12, x + 25, y + 3], fill=1)
        else:
            for s in range(max(0, min(8, level))):
                g.rectangle([x + 2 + s * 4, y + 2, x + 4 + s * 4, y + 13], fill=1)
        pix_text(g, x + (34 - pix_text_width(label, 1)) // 2, y + 20, label, spacing=1)

    def idle(self, g, ev):
        hs = ev.battery if ev.connected is not False else None
        self.big_battery(g, 14, 18, hs, "HEADSET")
        self.big_battery(g, 80, 18, ev.spare, "SPARE")

    @staticmethod
    def bars(g, level, peak, bottom):
        area = bottom - TOP
        for i in range(BANDS):
            x = i * 4
            h = int(round(level[i] * area))
            if h > 0:
                g.rectangle([x, bottom - h + 1, x + 2, bottom], fill=1)
            if peak[i] > 0.02:
                py = bottom - int(round(peak[i] * area))
                g.line([x, py, x + 2, py], fill=1)

    @staticmethod
    def mirror(g, level, peak, bottom):
        mid = (TOP + bottom) // 2 + 1
        half = (bottom - TOP) // 2
        for i in range(BANDS):
            x = i * 4
            h = int(round(level[i] * half))
            if h > 0:
                g.rectangle([x, mid - h, x + 2, mid + h], fill=1)
            if peak[i] > 0.02:
                p = int(round(peak[i] * half))
                g.line([x, mid - p, x + 2, mid - p], fill=1)
                g.line([x, mid + p, x + 2, mid + p], fill=1)

    @staticmethod
    def wave(g, pts, bottom):
        mid = (TOP + bottom) // 2 + 1
        half = (bottom - TOP) // 2 - 1
        ys = [int(mid - v * half) for v in pts]
        g.line(list(zip(range(W), ys)), fill=1)

    @staticmethod
    def blocks(g, level, peak, bottom):
        """Hi-fi LED columns: 3 px segments with 1 px gaps, peak = hollow segment."""
        seg = 4
        n = (bottom - TOP + 1) // seg
        for i in range(BANDS):
            x = i * 4
            lit = int(round(level[i] * n))
            for s in range(lit):
                y1 = bottom - s * seg
                g.rectangle([x, y1 - 2, x + 2, y1], fill=1)
            p = int(round(peak[i] * n))
            if p > lit:
                y1 = bottom - (p - 1) * seg
                g.rectangle([x, y1 - 2, x + 2, y1], outline=1)

    @staticmethod
    def mountain(g, level, peak, bottom):
        """Smooth spectrum curve with a dotted fill under it."""
        area = bottom - TOP
        cx = np.arange(BANDS) * 4 + 1.5
        xs = np.arange(W)
        y = np.interp(xs, cx, level)
        y = np.convolve(np.pad(y, 2, mode="edge"), np.ones(5) / 5, mode="valid")
        ys = (bottom - np.round(y * area)).astype(int)
        pts = [(x, yy) for x in range(W) for yy in range(ys[x] + 2, bottom + 1) if (x + yy) % 2 == 0]
        if pts:
            g.point(pts, fill=1)
        g.line(list(zip(xs.tolist(), ys.tolist())), fill=1)

    def waterfall(self, img, level, bottom):
        """Scrolling spectrogram: newest row on top, ordered dither shows loudness."""
        h = bottom - TOP + 1
        if self.wf is None or self.wf.shape[0] != h:
            self.wf = np.zeros((h, W), dtype=bool)
        row = np.repeat(level, W // BANDS) ** 1.3
        thr = self.BAYER4[self.wf_t % 4][np.arange(W) % 4]
        self.wf[1:] = self.wf[:-1].copy()
        self.wf[0] = row > thr
        self.wf_t += 1
        img.paste(Image.fromarray(self.wf), (0, TOP))

    def radial(self, g, level, bottom, bass):
        """Spokes around a core that pulses with the bass; left half mirrors the right."""
        cx, cy = W // 2, (TOP + bottom) // 2 + 1
        half = (bottom - TOP) // 2
        sx = 1.9                       # stretch horizontally to use the wide screen
        r0 = 4 + bass * 4
        span = half - r0 - 1
        for i in range(BANDS):
            ln = level[i] * span
            if ln < 0.5:
                continue
            a = -np.pi / 2 + np.pi * (i + 0.5) / BANDS   # bass on top, highs at the bottom
            c, s = np.cos(a), np.sin(a)
            for sgn in (1, -1):
                g.line([cx + sgn * c * r0 * sx, cy + s * r0,
                        cx + sgn * c * (r0 + ln) * sx, cy + s * (r0 + ln)], fill=1)
        rr = r0 - 1
        g.ellipse([cx - rr * sx, cy - rr, cx + rr * sx, cy + rr], outline=1, fill=1 if self.flash else 0)

    @staticmethod
    def scope(g, lr, bottom):
        """Stereo goniometer: mono = vertical line, wide stereo = round cloud."""
        cx, cy = W // 2, (TOP + bottom) // 2 + 1
        half = (bottom - TOP) // 2
        for k in range(-half, half + 1, 3):  # dotted L / R axes
            g.point([(cx + k, cy - k), (cx + k, cy + k)], fill=1)
        if lr is None or not len(lr):
            return
        m = (lr[:, 0] + lr[:, 1]) / 2
        s = (lr[:, 0] - lr[:, 1]) / 2
        xs = np.clip(np.round(cx + s * half), 0, W - 1).astype(int)
        ys = np.clip(np.round(cy - m * half), TOP, bottom).astype(int)
        g.point(list(zip(xs.tolist(), ys.tolist())), fill=1)

    def rings(self, g, bottom, bass, hit):
        """Rings fired by kicks fly outwards; the core follows the bass."""
        cx, cy = W // 2, (TOP + bottom) // 2 + 1
        half = (bottom - TOP) // 2
        if hit:
            self.ring_r.append(3.0)
        speed = 1.2 + bass * 2.5
        self.ring_r = [r + speed for r in self.ring_r if r < 42][-8:]
        for r in self.ring_r:
            g.ellipse([cx - r * 1.6, cy - r, cx + r * 1.6, cy + r], outline=1)
        core = 2 + bass * 5 + (2 if self.flash else 0)
        g.ellipse([cx - core * 1.6, cy - core, cx + core * 1.6, cy + core], fill=1)

    def pick_style(self, cfg, text):
        style = cfg.get("style", "bars")
        if style != "auto":
            return style if style in self.STYLES else "bars"
        pool = [s for s in (cfg.get("auto_styles") or self.STYLES) if s in self.STYLES] or list(self.STYLES)
        mins = float(cfg.get("auto_minutes") or 0)
        if self.auto_track is None:
            self.auto_track = text
        elif (text and text != self.auto_track) or (mins and time.time() - self.auto_t > mins * 60):
            self.auto_track, self.auto_t = text or self.auto_track, time.time()
            self.auto_i += 1
        return pool[self.auto_i % len(pool)]

    def draw_style(self, img, g, style, level, peak, wave, lr, bass, hit, bottom):
        if hit:
            self.flash = 3
        if style == "mirror":
            self.mirror(g, level, peak, bottom)
        elif style == "wave":
            self.wave(g, wave, bottom)
        elif style == "blocks":
            self.blocks(g, level, peak, bottom)
        elif style == "mountain":
            self.mountain(g, level, peak, bottom)
        elif style == "waterfall":
            self.waterfall(img, level, bottom)
        elif style == "radial":
            self.radial(g, level, bottom, bass)
        elif style == "scope":
            self.scope(g, lr, bottom)
        elif style == "rings":
            self.rings(g, bottom, bass, hit)
        else:
            self.bars(g, level, peak, bottom)
        self.flash = max(0, self.flash - 1)

    def style_label(self, g, bottom):
        """Style name for 1.5 s after a switch."""
        if time.time() - self.label_t > 1.5:
            return
        t = self.label.upper()
        tw = pix_text_width(t, 1)
        cy = (TOP + bottom) // 2 + 1
        x0 = (W - tw) // 2 - 4
        g.rectangle([x0, cy - 6, x0 + tw + 7, cy + 6], fill=0, outline=1)
        pix_text(g, x0 + 4, cy - 3, t, spacing=1)

    STRIP_H = 10

    def strip(self, g, text, rms):
        """Bottom strip: spaced nickname in the middle, stereo VU segments growing outwards (L left, R right)."""
        y0 = H - self.STRIP_H
        g.line([0, y0, W - 1, y0], fill=1)
        label = text.upper()
        tw = pix_text_width(label, spacing=3)
        tx = (W - tw) // 2
        pix_text(g, tx, y0 + 2, label, spacing=3)
        # VU: dB -> 0..1 with fast attack, slow release
        db = 20 * np.log10(np.asarray(rms) + 1e-6)
        target = np.clip((db + 48) / 42, 0, 1)
        self.vu = np.maximum(target, getattr(self, "vu", np.zeros(2)) * 0.9)
        seg_w, gap = 3, 1
        left_room = int(tx) - 4
        right_start = int(tx + tw) + 4
        n = max(0, min(left_room, W - right_start) // (seg_w + gap))
        cy0, cy1 = y0 + 3, H - 2
        for s in range(n):
            lit_l = s < round(self.vu[0] * n)
            lit_r = s < round(self.vu[1] * n)
            xl = left_room - (s + 1) * (seg_w + gap) + gap
            xr = right_start + s * (seg_w + gap)
            for x, lit in ((xl, lit_l), (xr, lit_r)):
                if lit:
                    g.rectangle([x, cy0, x + seg_w - 1, cy1], fill=1)
                else:
                    g.point([x + 1, (cy0 + cy1) // 2], fill=1)  # dim dot for unlit segment

    def volume(self, g, vol):
        g.rectangle([8, 20, W - 9, 52], fill=0, outline=1)
        label = f"VOL {round(vol * 100)}%"
        g.text(((W - g.textlength(label, font=FONT_SMALL)) / 2, 23), label, font=FONT_SMALL, fill=1)
        g.rectangle([14, 37, W - 15, 46], outline=1)
        fill = int((W - 32) * vol)
        if fill > 0:
            g.rectangle([16, 39, 16 + fill, 44], fill=1)

    def frame(self, cfg, mode, level, peak, wave, text, ev, rms=(0, 0), lr=None, beat=(0.0, False)):
        img = Image.new("1", (W, H), 0)
        g = ImageDraw.Draw(img)
        if mode == "clock":  # idle screen
            if cfg.get("idle") == "clock":
                clock = time.strftime("%H:%M")
                tw = g.textlength(clock, font=FONT_BIG)
                g.text(((W - tw) / 2, 14), clock, font=FONT_BIG, fill=1)
            elif cfg.get("idle") == "battery":
                self.idle(g, ev)
            # idle == "blank": nothing
        elif mode == "spectrum":
            bottom = H - self.STRIP_H - 2 if cfg.get("strip") else H - 1
            style = self.pick_style(cfg, text)
            if style != self.prev_style:
                self.prev_style, self.label, self.label_t = style, style, time.time()
            self.draw_style(img, g, style, level, peak, wave, lr, beat[0], beat[1], bottom)
            # styles may overflow (rings, radial): clear header / strip areas before drawing them
            g.rectangle([0, 0, W - 1, TOP - 1], fill=0)
            if cfg.get("strip"):
                g.rectangle([0, bottom + 1, W - 1, H - 1], fill=0)
                self.strip(g, str(cfg.get("strip_text", "NEXX"))[:10], rms)
            self.header(g, text, ev, cfg["show_battery"], cfg.get("show_clock", False))
            self.style_label(g, bottom)
        # mode == "blank": leave it black (OLED burn-in protection)
        if ev.overlay_active():
            self.volume(g, ev.volume)
        return np.array(img)


def pixel_shift(frame, minutes):
    """Burn-in protection: move the whole picture by 0/1 px, cycling every `minutes`."""
    if not minutes:
        return frame
    step = int(time.time() // (minutes * 60)) % 4
    dx, dy = ((0, 0), (1, 0), (1, 1), (0, 1))[step]
    if not (dx or dy):
        return frame
    out = np.zeros_like(frame)
    out[dy:, dx:] = frame[:H - dy, :W - dx]
    return out


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(HERE, "spectrum.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


CONTROL_PORT = 47811


def single_instance():
    """Hold a localhost port as a cross-process lock; returns None if another copy runs."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", CONTROL_PORT))
        s.listen(2)
        return s
    except OSError:
        return None


def control_server(sock, stop):
    """The lock port doubles as a control port: b"stop" ends cleanly and restores the base UI."""
    def run():
        while not stop.is_set():
            try:
                c, _ = sock.accept()
                with c:
                    if c.recv(16).startswith(b"stop"):
                        log("stop requested")
                        stop.set()
            except OSError:
                return
    threading.Thread(target=run, daemon=True).start()


def request_stop():
    """Ask a running service to stop. True if one was reached."""
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=1) as c:
            c.sendall(b"stop")
        return True
    except OSError:
        return False


def run_session(stop, np_thread, cfg, dur, start):
    """One device session; returns when stopped or raises on device/audio failure."""
    oled = Oled()
    audio = Loopback()
    prof = oled.profile
    log(f"session: {prof.name}{' (experimental)' if prof.experimental else ''}, "
        f"capturing {audio.name} @ {audio.rate} Hz")
    _, oled_path, info_path = find_device()
    ev = BaseEvents(info_path, oled_path, prof)
    if info_path:  # Omni: no info collection known yet -> no battery / volume
        ev.start()
    an, rend = Analyzer(audio.rate), Renderer()
    bright = None  # last brightness sent to the base
    try:
        while not stop.is_set() and not (dur and time.time() - start > dur):
            t0 = time.perf_counter()
            c = cfg.get()
            quiet = time.time() - audio.last_audio
            x = audio.samples()
            level, peak = an.step(x, float(c["range_db"]))
            wave = an.wave(x)
            if quiet > c["blank_after_minutes"] * 60 and not np_thread.playing:
                mode = "blank"
            elif quiet > SILENCE_S and not np_thread.playing:
                mode = "clock"
            else:
                mode = "spectrum"
            text = np_thread.text if mode == "spectrum" else ""
            beat = an.beat(level)
            lr = an.scope(audio.stereo())
            frame = rend.frame(c, mode, level, peak, wave, text, ev, audio.rms, lr=lr, beat=beat)
            want = target_brightness(c, mode)
            if want != bright and mode != "blank":
                try:
                    oled.brightness(want)
                    bright = want
                except Exception as e:
                    log(f"brightness {want} failed: {e!r}")
                    bright = want  # don't retry every frame
            oled.draw(pixel_shift(frame, 1 if c.get("oled_care") else c["shift_minutes"]))
            time.sleep(max(0, 1 / max(5, int(c["fps"])) - (time.perf_counter() - t0)))
    finally:
        ev.alive = False
        try:
            audio.close()
        finally:
            oled.close()  # returns the base to its stock UI


def main():
    lock = single_instance()
    if not lock:
        log("already running, exiting")
        return
    stop = threading.Event()
    control_server(lock, stop)
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    np_thread = NowPlaying()
    np_thread.start()
    cfg = Config()
    dur = float(os.environ.get("OLED_SECONDS", "0"))  # test runs: stop after N seconds
    start = time.time()
    while not stop.is_set() and not (dur and time.time() - start > dur):
        try:
            run_session(stop, np_thread, cfg, dur, start)
        except Exception as e:  # base unplugged, GG restarted, audio device changed...
            log(f"session error: {e!r}; retry in 5s")
            stop.wait(5)
    log("stopped, base UI restored")


if __name__ == "__main__":
    main()
