"""Render every style with simulated music into preview_styles.png (3x3 grid), base untouched."""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import spectrum as s

SCALE, FRAMES = 3, 60


class FakeEv:
    battery, connected, volume = 6, True, None

    def overlay_active(self):
        return False


def fake_audio(t, rng):
    """Spectrum sloping down with a kick every 8 frames, plus a stereo sample cloud."""
    kick = 1.0 if t % 8 == 0 else 0.0
    base = np.linspace(0.75, 0.2, s.BANDS) + 0.15 * np.sin(np.arange(s.BANDS) / 3 + t / 5)
    raw = np.clip(base + rng.normal(0, 0.07, s.BANDS), 0, 1)
    raw[:5] = np.clip(raw[:5] + kick * 0.35, 0, 1)
    ph = np.linspace(0, 40, 512) + t
    lr = np.stack([np.sin(ph) + rng.normal(0, 0.25, 512), np.sin(ph + 0.6) + rng.normal(0, 0.25, 512)], 1)
    wave = np.sin(np.linspace(0, 14, s.W) + t / 3) * (0.5 + 0.3 * kick)
    return raw, lr, wave


def render(style, cfg):
    rng = np.random.default_rng(7)
    an, r = s.Analyzer(48000), s.Renderer()
    r.vu = np.array([0.7, 0.55])
    c = {**cfg, "style": style}
    level = peak = np.zeros(s.BANDS)
    for t in range(FRAMES):
        raw, lr, wave = fake_audio(t, rng)
        an.norm = raw
        an.level = np.maximum(raw, an.level * s.DECAY)  # same smoothing as Analyzer.step
        rise = an.level >= an.peak
        an.peak[rise] = an.level[rise]
        an.peak[~rise] = np.maximum(an.peak[~rise] - 0.03, an.level[~rise])
        level, peak = an.level, an.peak
        beat = an.beat(level)
        if t == FRAMES - 1:
            r.label_t = 0  # hide the style-name popup on the shot
        frame = r.frame(c, "spectrum", level, peak, wave, "Artist - Track title", FakeEv(),
                        rms=(0.1, 0.07), lr=an.scope(lr), beat=beat)
    return frame


def oled_look(frame):
    """Upscale with a dark pixel grid so it looks like the real panel."""
    big = np.kron(frame.astype(np.uint8), np.ones((SCALE, SCALE), dtype=np.uint8))
    big[SCALE - 1::SCALE, :] = 0
    big[:, SCALE - 1::SCALE] = 0
    rgb = np.zeros(big.shape + (3,), dtype=np.uint8)
    rgb[big > 0] = (235, 240, 255)
    rgb[big == 0] = (8, 8, 12)
    return Image.fromarray(rgb)


def main():
    cfg = {**s.DEFAULTS, **json.load(open(os.path.join(s.HERE, "config.json"), encoding="utf-8"))}
    styles = s.Renderer.STYLES
    tw, th, pad, cap = s.W * SCALE, s.H * SCALE, 12, 22
    cols = 3
    rows = (len(styles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + cap + pad) + pad), (30, 30, 36))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 16)
    for i, st in enumerate(styles):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + cap + pad)
        d.text((x, y), st, font=font, fill=(255, 200, 60))
        sheet.paste(oled_look(render(st, cfg)), (x, y + cap))
    out = os.path.join(s.HERE, "preview_styles.png")
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main()
