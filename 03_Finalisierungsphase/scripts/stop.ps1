param([string]$PythonPath = '', [switch]$KeepDatabase)
. (Join-Path $PSScriptRoot 'common.ps1')
$pythonExe = Get-BookBridgePython $PythonPath
Assert-BookBridgePython $pythonExe
& $pythonExe (Join-Path $PSScriptRoot 'application.py') stop
if ($LASTEXITCODE -ne 0) { throw 'Anwendung konnte nicht sicher beendet werden; Datenbank bleibt aktiv.' }
if (-not $KeepDatabase) {
    & $pythonExe (Join-Path $PSScriptRoot 'runtime.py') stop
    if ($LASTEXITCODE -ne 0) { throw 'Eigene Phase-3-Datenbank konnte nicht beendet werden.' }
}
