param([string]$PostgresBin = 'D:\PostgreSQL\17\bin', [int]$Port = 55432)
$ErrorActionPreference = 'Stop'
$phaseRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $phaseRoot '.runtime'
$dataPath = Join-Path $runtimeRoot 'pgdata'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $PostgresBin 'pg_ctl.exe'))) { throw 'Set -PostgresBin to the PostgreSQL 17 bin directory.' }
if (-not (Test-Path -LiteralPath (Join-Path $dataPath 'PG_VERSION'))) {
    & (Join-Path $PostgresBin 'initdb.exe') -D $dataPath -U bookbridge_admin -E UTF8 --locale=C --auth=trust
    if ($LASTEXITCODE -ne 0) { throw 'initdb failed.' }
}
& (Join-Path $PostgresBin 'pg_ctl.exe') -D $dataPath status
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $PostgresBin 'pg_ctl.exe') -D $dataPath -l (Join-Path $runtimeRoot 'postgres.log') -o "-p $Port -h 127.0.0.1" -w start
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not start.' }
}
$exists = & (Join-Path $PostgresBin 'psql.exe') -X -At -h 127.0.0.1 -p $Port -U bookbridge_admin -d postgres -c "SELECT 1 FROM pg_database WHERE datname='bookbridge_phase2'"
if ($LASTEXITCODE -ne 0) { throw 'Cannot connect to the project cluster.' }
if ($exists -ne '1') {
    & (Join-Path $PostgresBin 'createdb.exe') -h 127.0.0.1 -p $Port -U bookbridge_admin bookbridge_phase2
    if ($LASTEXITCODE -ne 0) { throw 'Database creation failed.' }
}
Write-Output "BookBridge PostgreSQL ready at 127.0.0.1:$Port / bookbridge_phase2. Local test cluster uses trust authentication and binds only to loopback."
