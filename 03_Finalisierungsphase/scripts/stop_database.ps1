param([string]$PythonPath = '')
. (Join-Path $PSScriptRoot 'common.ps1')
$pythonExe = Get-BookBridgePython $PythonPath
Assert-BookBridgePython $pythonExe
& $pythonExe (Join-Path $PSScriptRoot 'runtime.py') stop
if ($LASTEXITCODE -ne 0) { throw 'Phase-3-Datenbank konnte nicht beendet werden.' }
