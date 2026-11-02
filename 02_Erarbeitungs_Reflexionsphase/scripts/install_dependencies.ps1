param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$phaseRoot = Split-Path -Parent $PSScriptRoot
$libraryPath = Join-Path $phaseRoot '.runtime\python'
$requirementsPath = Join-Path $PSScriptRoot 'requirements.txt'

if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw "Missing dependency file: $requirementsPath"
}
& $PythonPath -c "import sys; sys.exit('Python 3.11 or newer is required.') if sys.version_info < (3, 11) else None; print('Python ' + sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.11+ executable is required. Set -PythonPath to python.exe.' }
& $PythonPath -m pip --version
if ($LASTEXITCODE -ne 0) { throw 'pip is required for the selected Python interpreter.' }

New-Item -ItemType Directory -Path $libraryPath -Force | Out-Null
& $PythonPath -m pip install --disable-pip-version-check --no-cache-dir --no-warn-script-location --upgrade --target $libraryPath --requirement $requirementsPath
if ($LASTEXITCODE -ne 0) { throw 'Project-local dependency installation failed. Check the pip output and network connection.' }
& $PythonPath -c "import sys; sys.path.insert(0, sys.argv[1]); import psycopg; print('psycopg ' + psycopg.__version__ + ' installed in ' + sys.argv[1])" $libraryPath
if ($LASTEXITCODE -ne 0) { throw 'Installed psycopg could not be imported by the selected Python interpreter.' }
Write-Output 'Dependencies are ready. No system-wide Python packages were installed.'
