param([string]$PostgresBin = 'D:\PostgreSQL\17\bin')
$ErrorActionPreference = 'Stop'
$phaseRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PostgresBin 'pg_ctl.exe') -D (Join-Path $phaseRoot '.runtime\pgdata') -m fast -w stop
if ($LASTEXITCODE -ne 0) { throw 'The project database did not stop cleanly.' }
