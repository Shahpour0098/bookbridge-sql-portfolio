param([string]$PythonPath = '')
. (Join-Path $PSScriptRoot 'common.ps1')
$PythonPath = Get-BookBridgePython $PythonPath
Assert-BookBridgePython $PythonPath
$libraryPath = Join-Path $script:RuntimeRoot 'python'
$requirementsPath = Join-Path $script:PhaseRoot 'requirements.txt'
New-Item -ItemType Directory -Path $script:RuntimeRoot -Force | Out-Null
& $PythonPath -c "import sys; sys.path.insert(0,sys.argv[1]); from runtime import private_runtime; private_runtime()" $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Privater Laufzeitordner konnte nicht eingerichtet werden.' }
& $PythonPath -m pip --version
if ($LASTEXITCODE -ne 0) { throw 'pip fehlt beim ausgewaehlten Python.' }
New-Item -ItemType Directory -Path $libraryPath -Force | Out-Null
& $PythonPath -m pip install --disable-pip-version-check --no-cache-dir --no-warn-script-location --upgrade --target $libraryPath --requirement $requirementsPath
if ($LASTEXITCODE -ne 0) { throw 'Projektlokale Abhaengigkeiten konnten nicht installiert werden.' }
& $PythonPath -c "import sys,json; from pathlib import Path; from io import BytesIO; sys.path.insert(0,sys.argv[1]); import flask,psycopg,waitress; from PIL import Image; from reportlab.pdfgen.canvas import Canvas; image=Image.new('RGB',(1,1)); stream=BytesIO(); pdf=Canvas(stream); pdf.drawString(36,36,'BookBridge'); pdf.save(); assert stream.getvalue().startswith(b'%PDF-'); Path(sys.argv[2]).write_text(json.dumps({'python_executable':sys.executable,'python_version':sys.version.split()[0]},indent=2)+'\n',encoding='utf-8'); print('Projektlokale Python-Pakete, native Bildbibliothek und PDF-Erzeugung erfolgreich geprueft.')" $libraryPath (Join-Path $script:RuntimeRoot 'python-info.json')
if ($LASTEXITCODE -ne 0) { throw 'Installierte Bibliotheken konnten nicht importiert werden.' }
Write-Output 'Abhaengigkeiten liegen ausschliesslich in .runtime/python.'
