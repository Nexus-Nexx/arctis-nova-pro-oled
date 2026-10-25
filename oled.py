"""Minimal driver for SteelSeries base-station / GameDAC OLEDs (128x64).

Nova Pro protocol per JerwuQu/ggoled (GPL-3.0). Nova Elite / Nova Pro Omni differences per ggoled
issues #26/#33 and PR #35 — EXPERIMENTAL, untested by the author (no hardware).
"""
import time
from dataclasses import dataclass

import hid
import numpy as np

VID = 0x1038
W, H = 128, 64
SPLIT = 64  # columns per draw report
OLED_USAGE_PAGE = 0xFFC0
INFO_USAGE_PAGE = 0xFF00


@dataclass(frozen=True)
class Profile:
    name: str
    pids: tuple
    interface: int | None      # None: match by usage page only
    oled_id: int               # HID report id for draw / brightness / return-to-UI
    info_id: int               # HID report id for the 0xB0 status query and its reply
    report_size: int           # bytes per draw report incl. report id
    header: int                # bytes before the bitmap
    has_info: bool = True      # battery / volume events available
    has_ui_cmds: bool = True   # brightness + return-to-stock-UI known
    query_on_info: bool = False
    spare_battery: bool = True  # 0xB7 byte 3 = spare battery (Nova Pro) vs charging flag
    experimental: bool = False


PROFILES = (
    Profile("Arctis Nova Pro", (0x12CB, 0x12CD, 0x12E0, 0x12E5, 0x225D), 4,
            oled_id=0x06, info_id=0x06, report_size=1024, header=6),
    Profile("Arctis Nova Elite", (0x2244,), 3,
            oled_id=0x01, info_id=0x07, report_size=1024, header=6,
            query_on_info=True, spare_battery=False, experimental=True),
    Profile("Arctis Nova Pro Omni", (0x2290,), None,
            oled_id=0x01, info_id=0x01, report_size=1036, header=8,
            has_info=False, has_ui_cmds=False, experimental=True),
)


def find_device():
    """-> (profile, oled_path, info_path) for the first supported device, or (None, None, None)."""
    devs = list(hid.enumerate(VID))
    for prof in PROFILES:
        oled = info = None
        for d in devs:
            if d["product_id"] not in prof.pids:
                continue
            if prof.interface is not None and d["interface_number"] != prof.interface:
                continue
            if d["usage_page"] == OLED_USAGE_PAGE and oled is None:
                oled = d["path"]
            elif d["usage_page"] == INFO_USAGE_PAGE and info is None:
                info = d["path"]
        if oled:
            return prof, oled, info if prof.has_info else None
    return None, None, None


def find_paths():
    """Backward-compatible: (oled_path, info_path)."""
    _, oled, info = find_device()
    return oled, info


def list_steelseries():
    """Every SteelSeries HID collection: for --diag / adding new devices."""
    return [f"pid=0x{d['product_id']:04X} iface={d['interface_number']} usage_page=0x{d['usage_page']:04X} "
            f"usage=0x{d['usage']:02X} product={d.get('product_string') or '?'}" for d in hid.enumerate(VID)]


class Oled:
    def __init__(self):
        self.profile, oled, self.info_path = find_device()
        if not oled:
            raise RuntimeError("No supported SteelSeries base station OLED found")
        self.dev = hid.device()
        self.dev.open_path(oled)

    def _send(self, buf):
        for i in range(10):  # same retry policy as ggoled
            try:
                self.dev.send_feature_report(buf)
                return
            except OSError:
                time.sleep((i * i) / 1000)
        raise RuntimeError("draw report failed")

    def draw(self, frame: np.ndarray):
        """frame: bool/uint8 array shape (64, 128), nonzero = pixel on."""
        p = self.profile
        f = (np.asarray(frame) != 0).astype(np.uint8)
        for x0 in range(0, W, SPLIT):
            chunk = f[:, x0:x0 + SPLIT]                     # (64, 64)
            # column-major, 8-row blocks LSB-first: byte = x*8 + y//8, bit = y%8
            packed = np.packbits(chunk.T.reshape(SPLIT, H // 8, 8), axis=2, bitorder="little").reshape(-1)
            buf = bytearray(p.report_size)
            buf[0:6] = bytes([p.oled_id, 0x93, x0, 0, SPLIT, H])  # Omni: bytes 6-7 = 0 (exclusive mode)
            buf[p.header:p.header + packed.size] = packed.tobytes()
            self._send(bytes(buf))

    def brightness(self, level: int):
        if not self.profile.has_ui_cmds:
            return
        level = max(1, min(10, level))
        self.dev.write(bytes([self.profile.oled_id, 0x85, level]) + bytes(61))

    def return_to_ui(self):
        if not self.profile.has_ui_cmds:
            return
        self.dev.write(bytes([self.profile.oled_id, 0x95]) + bytes(62))

    def close(self):
        try:
            self.return_to_ui()
        finally:
            self.dev.close()


if __name__ == "__main__":
    from PIL import Image, ImageDraw, ImageFont

    print("\n".join(list_steelseries()))
    img = Image.new("1", (W, H), 0)
    g = ImageDraw.Draw(img)
    g.rectangle([0, 0, W - 1, H - 1], outline=1)
    font = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 14)
    g.text((10, 14), "HELLO OLED", font=font, fill=1)
    g.text((10, 34), "oled test", font=font, fill=1)
    o = Oled()
    print("device:", o.profile.name)
    o.draw(np.array(img))
    print("drawn, holding 4s")
    time.sleep(4)
    o.close()
    print("returned to UI")
