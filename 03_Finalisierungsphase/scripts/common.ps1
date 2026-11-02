$ErrorActionPreference = 'Stop'
$script:PhaseRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$script:RuntimeRoot = Join-Path $script:PhaseRoot '.runtime'

function Get-BookBridgePython([string]$RequestedPath = '') {
    if ($RequestedPath) { return $RequestedPath }
    $infoPath = Join-Path $script:RuntimeRoot 'python-info.json'
    if (Test-Path -LiteralPath $infoPath -PathType Leaf) {
        $info = Get-Content -LiteralPath $infoPath -Raw | ConvertFrom-Json
        if ($info.python_executable -and (Test-Path -LiteralPath $info.python_executable -PathType Leaf)) {
            return [string]$info.python_executable
        }
    }
    return 'python'
}

function Assert-BookBridgePython([string]$Executable) {
    & $Executable -c "import sys; sys.exit('Python 3.11 oder neuer erforderlich.') if sys.version_info < (3,11) else None"
    if ($LASTEXITCODE -ne 0) { throw 'Gueltiges Python 3.11+ erforderlich; -PythonPath auf python.exe setzen.' }
}
