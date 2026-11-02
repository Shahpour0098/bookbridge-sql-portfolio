# Ausgeführte PostgreSQL-Integrationstests

`run_tests.py` verbindet sich mit einer echten PostgreSQL-Datenbank. Das Programm
erzeugt Ergebnisse ausschließlich aus ausgeführten SQL-Befehlen. Es benötigt
Python 3.11+ und `psycopg` 3 (`requirements.txt`). Alternativ kann
`BOOKBRIDGE_PYTHON_LIB` auf die gebündelten Python-Bibliotheken verweisen.

```powershell
python tests/run_tests.py --dsn "host=127.0.0.1 port=55432 dbname=bookbridge_phase2 user=bookbridge_admin" --out reports/tests
```

Für eine unabhängige Neuinstallation aus den gespeicherten SQL-Dateien:

```powershell
python tests/verify_install.py --project "." --out evidence
```

Dieses zweite Programm legt eine **neue** Datenbank aus `template0` an,
führt die Installationsskripte und alle acht Ergebnisabfragen aus und startet
anschließend die vollständige Testsuite. `schema_verification.json` protokolliert
Dateiprüfsummen, Umgebung, Tabellen-/Spalten-/Fremdschlüsselzahlen und den
Testausgang. Die geprüfte Datenbank bleibt zur eigenen Kontrolle erhalten;
vorhandene Projektdatenbanken werden nicht überschrieben.

Vorher müssen die SQL-Dateien 01 bis 04 und 06 in einer eigenen Projektdatenbank
ausgeführt worden sein. Der Datenbankbenutzer benötigt für den automatisch
isolierten Paralleltest `CREATEDB`. Ohne dieses Recht kann eine zuvor angelegte,
verwerfbare Kopie per `--concurrency-dsn` angegeben werden. Die Hauptdatenbank
und die Paralleltest-Datenbank müssen unterschiedliche Namen besitzen.

Die regulären Tests verwenden Transaktionen mit erzwungenem Rollback. Nachher
vergleicht T21 Anzahl **und Inhalte** aller 18 Tabellen mit dem Ausgangszustand.
PostgreSQL rollt Identity-Sequenzschritte nicht zurück; Lücken in technischen IDs
sind deshalb erwartbar und verändern keine gespeicherten Testdaten.

T22 schließt zuerst die Hauptverbindung und erzeugt eine separate Datenbank aus
der Hauptdatenbank. Zwei unabhängige Verbindungen versuchen gleichzeitig, zwei
Anfragen desselben Exemplars anzunehmen. Exakt eine Annahme muss verbindlich
gespeichert und die andere fachlich abgewiesen werden. Die automatisch angelegte
Kopie trägt einen zufälligen Namen `bookbridge_phase2_test_<UUID>` und wird in
`finally` entfernt. Vorhandene fremde Datenbanken werden nicht gelöscht. Während
des Klonens dürfen keine anderen Verbindungen die Hauptdatenbank offen halten.

Die Suite prüft positive Abläufe und unerlaubte Aktionen für R01 bis R20,
einschließlich beider Berliner Zeitumstellungen, Höchstdauer, Gegenangebot,
genau einmaliger Anwendung jeder genehmigten Fristverlängerung, früher/später Rückgabe, Porto, Versandrollen,
Adressmomentaufnahmen, Bewertungen und Dokumentzuordnung. Fachlich erwartete
Ablehnungen zählen nur mit passenden SQLSTATE-Klassen als Erfolg. Fehlende
Funktionen, SQL-Syntaxfehler und Verbindungsfehler führen zu fehlgeschlagenen Tests.
T23 prüft zusätzlich die öffentliche Lesesicht ohne private Daten, die fehlenden
Tabellenrechte des Backend-Kontos und die getrennten Rechte für öffentliche
Geschäftsfunktionen beziehungsweise interne Helfer.

Ausgaben unter dem gewählten Ergebnisordner:

- `test-report.json`: DBMS-Version, Zeitpunkt, echte Testergebnisse, Regelzuordnung
  und Ergebnis des Paralleltests.
- `tables/*.csv`: Abfrage aller 18 Tabellen; Passwort-Hashes werden ausgelassen.
- `Q01_*.csv` bis `Q03_*.csv`: drei JOIN-Ergebnislisten mit jeweils drei Tabellen.

Die Prozessdaten sind fiktiv. `.test`-E-Mail-Adressen, nicht funktionsfähige
Demo-Hashwerte, geplante Dokumente, Test-Sendungsnummern und Portobestätigungen
lösen keinerlei externe Zustellung oder reale Zahlungsabwicklung aus. Drei
bibliografische Referenzen stimmen mit den bereits belegten Frontend-Covern
überein; weitere Titel und Personen sind ausdrücklich erfundene Testdatensätze.

## PowerShell-Installer separat prüfen

`verify_powershell_installer.py` installiert die gelieferten SQL-Dateien über
`scripts/install.ps1` in einer neuen UUID-Datenbank aus `template0`. Danach
muss ein zweiter Aufruf bestehende Tabellen ausdrücklich ablehnen. Ein Vergleich
aller Tabelleninhalte, Strukturzahlen und Sequenzstände bestätigt, dass die
Ablehnung keine Daten verändert. Die neue Datenbank bleibt zur Kontrolle erhalten.
Die SQL-Prüfsummen werden mit dem mitgelieferten unabhängigen Nachweis unter
`evidence/wrapper-verification-utf8/` verglichen.

```powershell
python tests/verify_powershell_installer.py --project . `
  --powershell (Join-Path $PSHOME 'powershell.exe') `
  --postgres-bin 'D:\PostgreSQL\17\bin' --port 55432
```

Bei PowerShell 7 heißt das Programm in `$PSHOME` `pwsh.exe`. Die Prüfung benötigt
dieselben Python-Abhängigkeiten wie die Testsuite, Verwaltungsrechte in der
lokalen Projektdatenbank und einen laufenden Projektcluster. Sie schreibt
`evidence/installer_verification.json` und `evidence/installer-console.txt` neu.
Den bestehenden Nachweis bei Bedarf vorher kopieren.
