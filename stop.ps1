# Stop the OLED spectrum and give the base its stock UI back
$p = $PSScriptRoot
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'spectrum\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 1
& (Join-Path $p '.venv\Scripts\python.exe') -c "import sys; sys.path.insert(0, r'$p'); from oled import Oled; Oled().close()"
'stopped, base UI restored'
