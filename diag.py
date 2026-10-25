"""ArctisOLED.exe --diag: write diag.txt with what the app can see (attach it to bug reports)."""
import os
import platform
import sys
import time


def main():
    lines = []

    def add(name, fn):
        try:
            lines.append(f"{name}: {fn()}")
        except Exception as e:
            lines.append(f"{name}: ERROR {e!r}")

    from version import VERSION
    import spectrum as s
    lines.append(f"Arctis OLED {VERSION}  frozen={getattr(sys, 'frozen', False)}  "
                 f"python={platform.python_version()}  windows={platform.version()}")
    lines.append(f"data dir: {s.HERE}")
    add("base HID (oled, info)", lambda: s.find_paths())
    add("service running", lambda: not bool(s.single_instance()))

    def loopback():
        a = s.Loopback()
        name = a.name
        a.close()
        return name
    add("audio loopback", loopback)

    def now_playing():
        n = s.NowPlaying()
        n.start()
        time.sleep(3)
        return repr(n.text) + (" (playing)" if n.playing else "")
    add("now playing", now_playing)

    out = os.path.join(s.HERE, "diag.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(out)
