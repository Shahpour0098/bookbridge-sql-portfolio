param(
    [string]$PythonPath = 'python',
    [string]$Dsn = 'host=127.0.0.1 port=55432 dbname=bookbridge_phase2 user=bookbridge_admin',
    [string]$OutputDirectory = '',
    [switch]$UseExistingDatabase,
    [string]$ConcurrencyDsn = ''
)
$ErrorActionPreference = 'Stop'
$phaseRoot = Split-Path -Parent $PSScriptRoot
$libraryPath = Join-Path $phaseRoot '.runtime\python'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $runName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
    $resultPath = Join-Path (Join-Path $phaseRoot 'evidence\runs') $runName
} elseif ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $resultPath = [System.IO.Path]::GetFullPath($OutputDirectory)
} else {
    $resultPath = [System.IO.Path]::GetFullPath((Join-Path $phaseRoot $OutputDirectory))
}
if (-not $UseExistingDatabase -and -not [string]::IsNullOrWhiteSpace($ConcurrencyDsn)) {
    throw '-ConcurrencyDsn is supported only with -UseExistingDatabase. The default fresh-install verification creates its own isolated race database.'
}

& $PythonPath -c "import sys; sys.exit('Python 3.11 or newer is required.') if sys.version_info < (3, 11) else None; sys.path.insert(0, sys.argv[1]); import psycopg; print('Python ' + sys.version.split()[0] + ' / psycopg ' + psycopg.__version__)" $libraryPath
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies are unavailable. Run scripts/install_dependencies.ps1 with the same -PythonPath first.' }
New-Item -ItemType Directory -Path $resultPath -Force | Out-Null
$previousLibraryPath = $env:BOOKBRIDGE_PYTHON_LIB
try {
    $env:BOOKBRIDGE_PYTHON_LIB = $libraryPath
    if ($UseExistingDatabase) {
        $testPath = Join-Path $phaseRoot 'tests\run_tests.py'
        $pythonArguments = @($testPath, '--dsn', $Dsn, '--out', $resultPath)
        if (-not [string]::IsNullOrWhiteSpace($ConcurrencyDsn)) {
            $pythonArguments += @('--concurrency-dsn', $ConcurrencyDsn)
        }
        Write-Output 'Testing the existing database. Close other connections if an automatic race-test clone is needed.'
    } else {
        $testPath = Join-Path $phaseRoot 'tests\verify_install.py'
        $pythonArguments = @($testPath, '--project', $phaseRoot, '--dsn', $Dsn, '--out', $resultPath)
        Write-Output 'Verifying published SQL in a new UUID database from template0. Existing project databases are preserved.'
    }
    if (-not (Test-Path -LiteralPath $testPath -PathType Leaf)) { throw "Missing test program: $testPath" }
    & $PythonPath @pythonArguments
    if ($LASTEXITCODE -ne 0) { throw "BookBridge verification failed. Inspect $resultPath for executed-test evidence." }
} finally {
    if ($null -eq $previousLibraryPath) {
        Remove-Item Env:BOOKBRIDGE_PYTHON_LIB -ErrorAction SilentlyContinue
    } else {
        $env:BOOKBRIDGE_PYTHON_LIB = $previousLibraryPath
    }
}
Write-Output "Verification completed. Results: $resultPath"
Write-Output "Test report: $(Join-Path $resultPath 'test-report.json')"
if (-not $UseExistingDatabase) {
    Write-Output "Installation audit: $(Join-Path $resultPath 'schema_verification.json')"
    Write-Output 'The new verification database is retained for inspection; only its own temporary race-test clone is removed.'
}
