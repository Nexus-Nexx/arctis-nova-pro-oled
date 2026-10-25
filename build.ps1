# Build the standalone app: dist\ArctisOLED\ArctisOLED.exe (no Python needed on the target PC)
# and release\ArctisOLED-v<version>-win64.zip. Needs the dev .venv (install.ps1).
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$py = Join-Path $dir '.venv\Scripts\python.exe'
Set-Location $dir

& $py -m pip install pyinstaller --quiet --disable-pip-version-check
$ver = (& $py build_assets.py).Trim()

& $py -m PyInstaller --noconfirm --clean --log-level WARN `
    --windowed --name ArctisOLED `
    --icon "$dir\build\icon.ico" --version-file "$dir\build\version_info.txt" `
    --hidden-import pystray._win32 `
    --collect-submodules winsdk.windows.media.control `
    --collect-submodules winsdk.windows.foundation `
    --collect-submodules winsdk.windows.storage.streams `
    --distpath "$dir\dist" --workpath "$dir\build\pyi" --specpath "$dir\build" `
    "$dir\app.py"
if ($LASTEXITCODE) { throw "PyInstaller failed ($LASTEXITCODE)" }

$app = Join-Path $dir 'dist\ArctisOLED'
Copy-Item (Join-Path $dir 'README_release.txt') (Join-Path $app 'README.txt') -Force
Copy-Item (Join-Path $dir 'LICENSE') (Join-Path $app 'LICENSE.txt') -Force

New-Item -ItemType Directory (Join-Path $dir 'release') -Force | Out-Null
$zip = Join-Path $dir "release\ArctisOLED-v$ver-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
"{0}  {1:n1} MB" -f $zip, ((Get-Item $zip).Length / 1MB)
