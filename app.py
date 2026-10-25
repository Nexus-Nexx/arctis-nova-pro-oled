"""Entry point of ArctisOLED.exe.

  ArctisOLED.exe            settings app (starts the base display if it isn't running)
  ArctisOLED.exe --tray     settings app hidden in the tray (Windows startup)
  ArctisOLED.exe --service  base display only, no window (what actually drives the OLED)
  ArctisOLED.exe --diag     write diag.txt (devices, audio, now playing) for bug reports
"""
import os
import sys

if __name__ == "__main__":
    if "--service" in sys.argv:
        import spectrum
        spectrum.main()
        os._exit(0)
    elif "--diag" in sys.argv:
        import diag
        diag.main()
        os._exit(0)
    else:
        import settings
        settings.main()
