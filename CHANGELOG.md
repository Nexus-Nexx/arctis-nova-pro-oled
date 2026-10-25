# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow [Semantic Versioning](https://semver.org/).

## [1.2.1] - 2026-10-25

### Added
- **♥ Support the project** button in the app (opens [Boosty](https://boosty.to/nexx106)) and a Sponsor button
  on the GitHub page.

## [1.2.0] - 2026-10-25

### Added
- **Standalone `ArctisOLED.exe`** — no Python needed. Download the zip from Releases, unzip, run.
- `ArctisOLED.exe --diag` writes `diag.txt` (base HID, audio device, now playing) for bug reports.
- `build.ps1` builds the exe and the release zip; `README.txt` with quick start inside the zip.
- The process shows up as **Arctis OLED** in Task Manager (version info + icon).

### Fixed
- Tray icon didn't appear, so closing the window left the app hidden with no way back.
- The app process could stay alive after **Exit**.
- Opening from the tray didn't bring the window to the front.

### Changed
- Stopping the base display is graceful (control port instead of killing the process); the stock base screen
  always comes back.
- Opening the app starts the base display if it isn't running.
- Settings are stored next to the exe (or in `%APPDATA%\ArctisOLED` if that folder is read-only).

## [1.1.0] - 2026-10-25

### Added
- English / Russian UI, follows the Windows language, switchable in ⚙ Settings.
- ⚙ Settings: language, minimize/close to tray, start in tray with Windows, start the base display with Windows.
- Tray icon with a quick visualization menu; single instance (a second launch opens the existing window).

## [1.0.0] - 2026-10-25

### Added
- First public version: 9 visualizations (bars, LED blocks, mirror, mountain, oscilloscope, waterfall, radial,
  stereo scope, kick rings) and Auto mode that switches style on every track.
- Settings app with a live preview from the real Arctis audio.
- Brightness, OLED care mode (pixel shift, dimmed idle screen), idle screens, now playing, battery, volume overlay.
- `install.ps1` for running from source.

[1.2.1]: https://github.com/Nexus-Nexx/arctis-nova-pro-oled/releases/tag/v1.2.1
[1.2.0]: https://github.com/Nexus-Nexx/arctis-nova-pro-oled/releases/tag/v1.2.0
[1.1.0]: https://github.com/Nexus-Nexx/arctis-nova-pro-oled/releases/tag/v1.1.0
[1.0.0]: https://github.com/Nexus-Nexx/arctis-nova-pro-oled/releases/tag/v1.0.0
