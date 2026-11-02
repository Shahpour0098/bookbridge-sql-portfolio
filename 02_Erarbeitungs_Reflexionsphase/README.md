# BookBridge – Phase 2: SQL-Implementierung und Nachweis

Der Entwurf aus Phase 1 ist in PostgreSQL 17 umgesetzt: **18 Tabellen, 142 Spalten, 32 Fremdschlüssel und 1.431 fiktive Testdatensätze**. Die unabhängige Neuinstallation und **23 Integrationstests** sind erfolgreich dokumentiert. Acht Ergebnisabfragen und 21 Aufnahmen aus dem tatsächlich verwendeten pgAdmin ergänzen die Nachweise. Phase 1 bleibt unverändert.

Die Umsetzung steht in [BookBridge_Phase2_Umsetzung.pdf](docs/BookBridge_Phase2_Umsetzung.pdf); die Präsentation liegt als [PowerPoint](docs/BookBridge_Phase2_Praesentation.pptx) und [PDF](docs/BookBridge_Phase2_Praesentation.pdf) vor. SQL, reproduzierbare Prüfungen, CSV-Ergebnisse und Originalaufnahmen sind getrennt in `sql/`, `tests/`, `evidence/` und `screenshots/` abgelegt. `design/bookbridge-model-v2.json` hält den verbindlichen Entwurf fest. Die SQL-Dateien sind die maßgebliche Quelle für eine neue Datenbank; ein optionaler Datenbankexport ersetzt die Neuinstallationsprüfung nicht.

Die Abschlussprüfung vom 19. Oktober 2026 steht in `evidence/recheck-20261019/`: erneuter Aufbau aus `template0`, alle sechs SQL-Dateien und erneut 23 erfolgreiche Tests. Dafür wurde ein separater lokaler Prüfcluster auf Port 55433 verwendet; die unten beschriebenen Standardeinstellungen bleiben Port 55432. `evidence/installer_verification.json` belegt zusätzlich die erfolgreiche PowerShell-Installation sowie die Ablehnung einer zweiten Installation ohne Änderung bestehender Daten oder Sequenzstände. `evidence/artifact_review.json` hält die geprüften Dokumentversionen fest. `SHA256SUMS.txt` und `BookBridge_Phase2.zip.sha256` ermöglichen den Vergleich der gelieferten Dateien und des ZIP-Archivs. Im gemeinsamen Abgabepaket aller drei Phasen gelten die Prüfsummen und das MANIFEST im übergeordneten Hauptordner; das frühere Einzelarchiv wird dort nicht zusätzlich eingebettet.

Die Entitätsfolien zeigen gekennzeichnete SQL-Auszüge und die jeweilige Testabfrage mit Originalaufnahme. Die vollständigen `CREATE TABLE`-Anweisungen stehen in `sql/01_schema.sql` und zusätzlich in den Notizen der entsprechenden PowerPoint-Folien. Der Umsetzungsbericht liegt in dieser Lieferung als PDF vor; seine bearbeitbare Wordfassung bleibt im lokalen Arbeitsprojekt.

## Aus einem frisch entpackten Ordner starten

Voraussetzungen: Windows PowerShell, **PostgreSQL 17** und **Python 3.11 oder neuer mit pip**. PostgreSQL und Python werden nicht durch diese Skripte installiert. Alle Befehle im entpackten Ordner `Phase 2` ausführen; Pfade mit Leerzeichen in Anführungszeichen setzen. `-PostgresBin` bezeichnet den eigenen PostgreSQL-Ordner mit `initdb.exe`, `pg_ctl.exe` und `psql.exe`. Für Python kann statt `python` der vollständige Pfad zu `python.exe` angegeben werden.

```powershell
Set-Location 'D:\Pfad\zum\entpackten\Phase 2'

# 1. Separaten Projektcluster und leere Hauptdatenbank starten.
.\scripts\start_database.ps1 -PostgresBin 'D:\PostgreSQL\17\bin'

# 2. Ausschließlich projektlokale Python-Abhängigkeiten installieren.
.\scripts\install_dependencies.ps1 -PythonPath 'python'

# 3. Schema, Integritätsregeln, Workflows, Testdaten und Rechte installieren.
.\scripts\install.ps1 -PostgresBin 'D:\PostgreSQL\17\bin'

# 4. Erneut aus den SQL-Quellen in einer NEUEN Datenbank prüfen.
.\scripts\run_tests.ps1 -PythonPath 'python' -OutputDirectory 'evidence\recheck'
```

`start_database.ps1` verwendet ausschließlich `.runtime/pgdata` dieses Projekts und standardmäßig `127.0.0.1:55432`, Datenbank `bookbridge_phase2`, Benutzer `bookbridge_admin`. `-Port` kann beim Start und bei der Installation geändert werden; beim Prüfen dann den passenden `-Dsn` übergeben. Der Installer verweigert vorhandene BookBridge-Tabellen und löscht keine Daten. `install_dependencies.ps1` installiert die festgelegte Version aus `scripts/requirements.txt` nach `.runtime/python`; eine systemweite Paketinstallation ist nicht erforderlich. Python-Bibliotheken aus einem anderen Betriebssystem oder einer anderen Python-Version vor einer frischen Installation nicht übernehmen.

Die Standardprüfung erstellt aus `template0` eine Datenbank namens `bookbridge_phase2_verify_<UUID>`, führt alle sechs SQL-Dateien einschließlich der acht Abfragen aus und startet die 23 Tests. Diese neue Datenbank **bleibt zur Kontrolle erhalten**; vorhandene Hauptdatenbanken werden weder überschrieben noch als Vorlage benötigt. Eine offene pgAdmin-Verbindung zur Hauptdatenbank behindert diese Prüfung deshalb nicht. Der Benutzer benötigt `CREATEDB`. Die Testverbindungen zur neuen Prüfungsdatenbank verwaltet das Programm selbst.

```powershell
# Beispiel für einen anderen Anschluss und einen frei gewählten Ergebnisordner:
.\scripts\run_tests.ps1 -PythonPath 'C:\Python313\python.exe' `
  -Dsn 'host=127.0.0.1 port=55433 dbname=bookbridge_phase2 user=bookbridge_admin' `
  -OutputDirectory 'evidence\eigene-pruefung'

# Projektcluster nach der Arbeit geordnet stoppen:
.\scripts\stop_database.ps1 -PostgresBin 'D:\PostgreSQL\17\bin'
```

Relative Ergebnisordner beziehen sich auf den Projektordner. Ohne `-OutputDirectory` entsteht ein neuer Unterordner in `evidence/runs/`; die mitgelieferten Belege bleiben erhalten. Ein Fehler führt zu einem Fehlerstatus des PowerShell-Skripts. SQL-Installation, Versionsstand, Dateiprüfsummen, Tabellenzahlen und Testausgang stehen in `schema_verification.json`; Einzeltests und die echte Konkurrenzprüfung stehen in `test-report.json`. Die Programme exportieren außerdem alle 18 Tabellen ohne Passwort-Hashes sowie die drei JOIN-Ergebnislisten. `evidence/` enthält die bereits ausgeführten Originalnachweise.

## Was geprüft wird und wie die Rechte wirken

Die Tests decken R01–R20 ab: Eigentum und Teilnehmer, Standorte, Autorenbeteiligung, Abholfenster, Verfügbarkeit, Gegenangebote, Kalenderfristen über beide Berliner Zeitumstellungen, Verlängerungen, Porto, Hin-/Rückversand, Rückgabe, Bewertungen, Kommunikation und unveränderliche Momentaufnahmen. Reguläre Testdaten werden zurückgerollt; T21 vergleicht danach Zeilenanzahl **und Inhalt** mit dem Ausgangszustand. Lücken in Identity-Sequenzen sind normal, weil PostgreSQL Sequenzschritte nicht zurückrollt.

Für T22 wird nur eine selbst angelegte UUID-Kopie der Prüfungsdatenbank verwendet. Zwei echte Verbindungen versuchen gleichzeitig die Annahme desselben Exemplars; genau eine muss erfolgreich sein. Ausschließlich diese eigene temporäre Kopie wird anschließend entfernt. T23 prüft die sichere öffentliche Katalogsicht, gesperrte Basistabellen und die Trennung von Geschäfts- und Hilfsfunktionen.

`bookbridge_reader` darf nur den öffentlichen Katalog ohne private Anschriften oder genaue Koordinaten lesen. `bookbridge_backend` darf die 20 kontrollierten Geschäftsfunktionen ausführen, erhält jedoch keine direkten Tabellenzugriffe. Die `actor_id` wird von einem **vertrauenswürdigen, zuvor authentifizierenden Backend** übergeben; sie ist selbst kein Anmeldenachweis. Rollen sind als `NOLOGIN` angelegt. Der lokale Demonstrationscluster nutzt `trust` und lauscht nur auf Loopback; seine Verwaltungsverbindung ist keine produktive Zugriffskontrolle und gehört nicht in einen öffentlichen Betrieb.

Benachrichtigungen bleiben `queued`, Dokumente `planned`; reale E-Mails, Zahlungen, Versandaufträge oder private Dokumentdateien werden nicht ausgelöst oder behauptet. Alle Prozesspersonen, Kontaktadressen, Testsendungen und Bewertungen sind fiktiv; drei bibliografische Referenzen entsprechen den dokumentierten Buchcovern.

Optional kann mit `-UseExistingDatabase` nur die Suite auf einer bereits installierten Datenbank ausgeführt werden. Für deren automatisch erzeugte Konkurrenzkopie müssen zuvor alle anderen Verbindungen zu **dieser** Datenbank geschlossen werden. Eine ausdrücklich bereitgestellte, verwerfbare andere Datenbank kann über `-ConcurrencyDsn` verwendet werden; sie erhält die festgeschriebenen Konkurrenz-Testdaten und wird nicht automatisch gelöscht. Weitere Einzelheiten stehen in [tests/README.md](tests/README.md).

## In pgAdmin ansehen

Im vorhandenen pgAdmin einen Server mit Host `127.0.0.1`, Port `55432`, Wartungsdatenbank `bookbridge_phase2` und Benutzer `bookbridge_admin` registrieren. Für diesen eigenen lokalen Testcluster ist kein Passwort erforderlich. Danach die Datenbank öffnen und im Query Tool `sql/05_queries.sql` ausführen. Die Originalaufnahmen unter `screenshots/` zeigen denselben Server und die Hauptdatenbank; `screenshots/manifest.json` enthält die tatsächlich aufgenommenen SQL-Abfragen und Aufnahmezeitpunkte.

Die drei realen Referenzcover liegen mit Editionsnachweisen unter [pictures/](pictures/README.md). Sie sind unveränderte Bilddateien und werden in der Datenbank nicht als BLOB gespeichert. Die 21 weiteren Titel sind fiktiv.

Die persönlichen Abgabedaten und der endgültige PebblePad-Dateiname werden vor der Einreichung ergänzt. Die PowerPoint-Quelldatei und die Präsentations-PDF sind enthalten. Der Umsetzungsbericht ist als PDF beigefügt; die bearbeitbare Wordfassung bleibt im lokalen Arbeitsprojekt.
