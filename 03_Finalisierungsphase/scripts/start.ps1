param([string]$PythonPath = '', [switch]$OpenBrowser)
. (Join-Path $PSScriptRoot 'common.ps1')
$pythonExe = Get-BookBridgePython $PythonPath
Assert-BookBridgePython $pythonExe
& $pythonExe (Join-Path $PSScriptRoot 'runtime.py') start
if ($LASTEXITCODE -ne 0) { throw 'Phase-3-Datenbank konnte nicht gestartet werden.' }
& $pythonExe (Join-Path $PSScriptRoot 'application.py') start
if ($LASTEXITCODE -ne 0) { throw 'BookBridge konnte nicht gestartet werden; .runtime/server.err.log pruefen.' }
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:8767' -WindowStyle Hidden | Out-Null }
