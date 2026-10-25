# Arctis Nova Pro OLED: create .venv, install dependencies, add shortcuts, start the display service.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$venvPy = Join-Path $dir '.venv\Scripts\python.exe'
$venvPyw = Join-Path $dir '.venv\Scripts\pythonw.exe'

if (-not (Test-Path $venvPy)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv (Join-Path $dir '.venv') }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv (Join-Path $dir '.venv') }
    else { throw 'Python 3.12 not found. Install it from python.org (tick "Add to PATH") and run again.' }
}
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $dir 'requirements.txt') --quiet

$ws = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $script) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $venvPyw
    $s.Arguments = "`"$(Join-Path $dir $script)`""
    $s.WorkingDirectory = $dir
    $s.Save()
}
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Arctis OLED.lnk') 'settings.py'
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Startup')) 'Arctis OLED Spectrum.lnk') 'spectrum.py'

Start-Process $venvPyw -ArgumentList "`"$(Join-Path $dir 'spectrum.py')`"" -WorkingDirectory $dir
Write-Host 'Installed. The base display is running; open "Arctis OLED" on the desktop for settings.'
