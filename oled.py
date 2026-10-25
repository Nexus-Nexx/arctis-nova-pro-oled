"""Minimal driver for the Arctis Nova Pro base station OLED (128x64), protocol per JerwuQu/ggoled (GPL-3.0)."""
import time

import hid
import numpy as np

VID = 0x1038
PIDS = (0x12CB, 0x12CD, 0x12E0, 0x12E5, 0x225D)  # Nova Pro wired/wireless variants
IFACE = 4
OLED_USAGE_PAGE = 0xFFC0  # report descriptor starts 06 C0 FF
INFO_USAGE_PAGE = 0xFF00
REPORT_ID = 0x06
W, H = 128, 64
REPORT_SIZE = 1024
SPLIT = 64  # columns per draw report


def find_paths():
    oled = info = None
    for d in hid.enumerate(VID):
        if d["product_id"] in PIDS and d["interface_number"] == IFACE:
            if d["usage_page"] == OLED_USAGE_PAGE:
                oled = d["path"]
            elif d["usage_page"] == INFO_USAGE_PAGE:
                info = d["path"]
    return oled, info


class Oled:
    def __init__(self):
        oled, self.info_path = find_paths()
        if not oled:
            raise RuntimeError("Arctis Nova Pro base OLED interface not found")
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
        f = (np.asarray(frame) != 0).astype(np.uint8)
        for x0 in range(0, W, SPLIT):
            chunk = f[:, x0:x0 + SPLIT]                     # (64, 64)
            # column-major, 8-row blocks LSB-first: byte = x*8 + y//8, bit = y%8
            packed = np.packbits(chunk.T.reshape(SPLIT, H // 8, 8), axis=2, bitorder="little").reshape(-1)
            buf = bytearray(REPORT_SIZE)
            buf[0:6] = bytes([REPORT_ID, 0x93, x0, 0, SPLIT, H])
            buf[6:6 + packed.size] = packed.tobytes()
            self._send(bytes(buf))

    def brightness(self, level: int):
        level = max(1, min(10, level))
        self.dev.write(bytes([REPORT_ID, 0x85, level]) + bytes(61))

    def return_to_ui(self):
        self.dev.write(bytes([REPORT_ID, 0x95]) + bytes(62))

    def close(self):
        try:
            self.return_to_ui()
        finally:
            self.dev.close()


if __name__ == "__main__":
    from PIL import Image, ImageDraw, ImageFont

    for d in hid.enumerate(VID):
        if d["product_id"] in PIDS:
            print(f"iface={d['interface_number']} usage_page=0x{d['usage_page']:04X} usage=0x{d['usage']:02X}")
    img = Image.new("1", (W, H), 0)
    g = ImageDraw.Draw(img)
    g.rectangle([0, 0, W - 1, H - 1], outline=1)
    font = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 14)
    g.text((10, 14), "HELLO OLED", font=font, fill=1)
    g.text((10, 34), "oled test", font=font, fill=1)
    o = Oled()
    o.draw(np.array(img))
    print("drawn, holding 4s")
    time.sleep(4)
    o.close()
    print("returned to UI")
