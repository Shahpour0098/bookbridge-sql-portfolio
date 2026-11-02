param(
    [string]$PythonPath = '',
    [string]$PostgresBin = '',
    [ValidateRange(1024,65535)][Nullable[int]]$Port = $null,
    [switch]$SkipDependencies
)
. (Join-Path $PSScriptRoot 'common.ps1')
$pythonExe = Get-BookBridgePython $PythonPath
Assert-BookBridgePython $pythonExe
if (-not $SkipDependencies) {
    & (Join-Path $PSScriptRoot 'install_dependencies.ps1') -PythonPath $pythonExe
}
$runtimeArguments = @((Join-Path $PSScriptRoot 'runtime.py'), 'init')
if ($PostgresBin) { $runtimeArguments += @('--postgres-bin', $PostgresBin) }
elseif (-not (Test-Path -LiteralPath (Join-Path $script:RuntimeRoot 'owner.json') -PathType Leaf)) {
    $runtimeArguments += @('--postgres-bin', 'D:\PostgreSQL\17\bin')
}
if ($null -ne $Port) { $runtimeArguments += @('--port', [string]$Port) }
& $pythonExe @runtimeArguments
if ($LASTEXITCODE -ne 0) { throw 'Eigene Phase-3-Datenbank konnte nicht gestartet werden.' }
& $pythonExe (Join-Path $PSScriptRoot 'install_database.py')
if ($LASTEXITCODE -ne 0) { throw 'Installation gestoppt. Bestehende Daten bleiben erhalten.' }
Write-Output 'BookBridge Phase 3 ist eingerichtet. Jetzt scripts/start.ps1 ausfuehren.'
