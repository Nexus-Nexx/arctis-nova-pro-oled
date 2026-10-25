"""Generate build/icon.ico and build/version_info.txt for PyInstaller (called by build.ps1)."""
import os

from PIL import Image, ImageDraw

from version import VERSION

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build")


def icon():
    n = 256
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, n - 9, n - 9], radius=48, fill=(27, 28, 33, 255))
    for i, h in enumerate((88, 152, 120, 184, 104)):  # same five bars as the tray icon
        x = 36 + i * 40
        d.rectangle([x, 216 - h, x + 24, 216], fill=(245, 184, 61, 255))
    img.save(os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                     (128, 128), (256, 256)])


def version_file():
    nums = tuple(int(x) for x in VERSION.split(".")) + (0,)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Nexus-Nexx'),
      StringStruct('FileDescription', 'Arctis OLED'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'ArctisOLED'),
      StringStruct('LegalCopyright', 'GPL-3.0'),
      StringStruct('OriginalFilename', 'ArctisOLED.exe'),
      StringStruct('ProductName', 'Arctis OLED'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(os.path.join(OUT, "version_info.txt"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    icon()
    version_file()
    print(VERSION)
