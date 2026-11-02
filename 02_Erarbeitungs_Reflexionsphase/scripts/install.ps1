param([string]$PostgresBin = 'D:\PostgreSQL\17\bin', [string]$Database = 'bookbridge_phase2', [int]$Port = 55432)
$ErrorActionPreference = 'Stop'
$phaseRoot = Split-Path -Parent $PSScriptRoot
$psqlPath = Join-Path $PostgresBin 'psql.exe'
$existing = & $psqlPath -X -At -h 127.0.0.1 -p $Port -U bookbridge_admin -d $Database -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='bookbridge' AND table_type='BASE TABLE'"
if ($LASTEXITCODE -ne 0) { throw 'Cannot connect. Run start_database.ps1 first.' }
if ([int]$existing -ne 0) { throw 'The database already contains BookBridge tables. Use a new empty database; this installer never drops existing data.' }
foreach ($filename in @('01_schema.sql','02_integrity.sql','03_workflows.sql','04_seed.sql','06_access.sql')) {
    $source = Join-Path (Join-Path $phaseRoot 'sql') $filename
    & $psqlPath -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port -U bookbridge_admin -d $Database -f $source
    if ($LASTEXITCODE -ne 0) { throw "SQL installation stopped at $filename. The failing file's transaction is rolled back; inspect before retrying." }
}
Write-Output 'Installation completed. Run scripts/run_tests.ps1 for an independent fresh-database verification.'
Write-Output 'The wrapper prints the output folder containing test-report.json and schema_verification.json; supplied evidence is preserved by default.'
