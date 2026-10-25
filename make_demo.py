"""Render a demo clip of every style (demo signal, no hardware needed): docs/demo.mp4 + docs/demo.gif."""
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import spectrum as s
from preview_styles import fake_audio

FPS, SECONDS_PER_STYLE, SCALE = 30, 2.5, 6
OUT = os.path.join(s.HERE, "docs")
FRAMES = os.path.join(s.HERE, "build", "demo_frames")


class FakeEv:
    battery, spare, connected, volume = 7, 8, True, None

    def overlay_active(self):
        return False


def oled(frame):
    big = np.kron(frame.astype(np.uint8), np.ones((SCALE, SCALE), dtype=np.uint8))
    big[SCALE - 1::SCALE, :] = 0
    big[:, SCALE - 1::SCALE] = 0
    rgb = np.full(big.shape + (3,), (6, 6, 10), dtype=np.uint8)
    rgb[big > 0] = (235, 240, 255)
    return Image.fromarray(rgb)


def main():
    os.makedirs(FRAMES, exist_ok=True)
    for f in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, f))
    font = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 22)
    rng = np.random.default_rng(3)
    an, r = s.Analyzer(48000), s.Renderer()
    r.vu = np.zeros(2)
    cfg = {**s.DEFAULTS, "strip_text": "NOVA PRO"}
    n, t = 0, 0
    for style in s.Renderer.STYLES:
        c = {**cfg, "style": style}
        for _ in range(int(SECONDS_PER_STYLE * FPS)):
            raw, lr, wave = fake_audio(t // 2, rng)
            t += 1
            an.norm = raw
            an.level = np.maximum(raw, an.level * s.DECAY)
            rise = an.level >= an.peak
            an.peak[rise] = an.level[rise]
            an.peak[~rise] = np.maximum(an.peak[~rise] - 0.03, an.level[~rise])
            r.label_t = 0  # no style popup, the caption below names the style
            frame = r.frame(c, "spectrum", an.level, an.peak, wave, "Artist - Track title", FakeEv(),
                            rms=(0.1, 0.07), lr=an.scope(lr), beat=an.beat(an.level))
            img = oled(frame)
            canvas = Image.new("RGB", (img.width, img.height + 40), (20, 21, 26))
            canvas.paste(img, (0, 0))
            ImageDraw.Draw(canvas).text((12, img.height + 8), style, font=font, fill=(245, 184, 61))
            canvas.save(os.path.join(FRAMES, f"f{n:05d}.png"))
            n += 1
    src = os.path.join(FRAMES, "f%05d.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", src, "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", os.path.join(OUT, "demo.mp4")],
                   check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", src, "-vf",
                    "fps=15,scale=512:-1:flags=neighbor,split[a][b];[a]palettegen=max_colors=16[p];[b][p]paletteuse",
                    os.path.join(OUT, "demo.gif")], check=True)
    for f in ("demo.mp4", "demo.gif"):
        p = os.path.join(OUT, f)
        print(f, round(os.path.getsize(p) / 1e6, 2), "MB")


if __name__ == "__main__":
    main()
