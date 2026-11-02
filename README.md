# BookBridge

BookBridge ist ein lokaler Studien-Demonstrator für **DLBDSPBDM01_D**. Eine deutsche Browseroberfläche verbindet Registrierung, Katalog, eigene Angebote und Ausleihen mit einer relationalen PostgreSQL-Datenbank. Fachliche Regeln werden in SQL abgesichert; die Webanwendung übernimmt Anmeldung, Teilnehmerrechte und geschützte PDF-Bestätigungen.

## Repository und Lieferung

Repository: [Shahpour0098/bookbridge-sql-portfolio](https://github.com/Shahpour0098/bookbridge-sql-portfolio). Das öffentliche Repository wurde für diese Abgabe eingerichtet; die vollständigen Projektdateien werden mit dem dokumentierten Veröffentlichungsstand bereitgestellt.

Der veröffentlichbare Umfang enthält die Ergebnisse aller drei Phasen, Quellcode, kommentierte SQL-Dateien, PDF-Berichte, Präsentation und ausgewählte synthetische Prüfnachweise. Die Aufgabenstellung der Hochschule und private Laufzeitdateien gehören nicht zum Repository.

## Projektstruktur

| Ordner | Inhalt |
| --- | --- |
| `01_Konzeptionsphase/` | Anforderungen, Vorgehen, Datenwörterbuch, ER-Modell und Diagramme |
| `02_Erarbeitungs_Reflexionsphase/` | SQL-Implementierung, Präsentation, DBMS-Aufnahmen, Ergebnislisten und synthetischer Datenbankexport |
| `03_Finalisierungsphase/` | Integrierte Anwendung, acht Migrationen, Startskripte, Tests und Abschlussberichte |
| `tools/` | Prüfung und erneute Erstellung der Lieferdateien und Prüfsummen |

## Anwendung unter Windows einrichten

Voraussetzungen sind **Python ab 3.11 mit pip**, **PostgreSQL 17** und Windows PowerShell. PostgreSQL und Python werden separat bereitgestellt. PowerShell im Ordner `03_Finalisierungsphase/` öffnen und die beiden Installationspfade bei Bedarf anpassen:

```powershell
.\scripts\setup.ps1 -PythonPath 'C:\Python313\python.exe' -PostgresBin 'D:\PostgreSQL\17\bin'
.\scripts\start.ps1 -OpenBrowser
# Nach der Arbeit:
.\scripts\stop.ps1
```

Die lokale Adresse lautet **http://127.0.0.1:8767**. Der eigene PostgreSQL-Cluster verwendet standardmäßig **127.0.0.1:55434**. Der Installer erzeugt die private Laufzeit am Ziel neu. Nach der Einrichtung startet auch `BookBridge starten.cmd`. Die ausführliche [Anwendungsanleitung](03_Finalisierungsphase/README.md) erläutert erste Nutzung, andere Ports und lokale Administration.

Es gibt kein gemeinsames Administratorpasswort. Zuerst ein eigenes Konto im Browser registrieren; danach kann der lokale Betreiber dieses Konto mit `scripts/promote_admin.py --email 'eigene-adresse@example.org'` und dem eingerichteten Python zur Administration berechtigen. Die fiktiven Seedkonten besitzen keine verwendbaren Anmeldepasswörter.

## Modell und Prüfung

Das Fachmodell umfasst **18 Basistabellen, 142 Spalten und 32 Fremdschlüssel**. Der synthetische Ausgangsbestand enthält **1.431 Zeilen**, mindestens zwölf je Fachtabelle. Zwei technische Tabellen ergänzen Sitzungen und Migrationserfassung; die öffentliche Sicht projiziert 15 Spalten und zählt nicht als zusätzliche Fachtabelle.

Die ausgeführten Nachweise vom 21. Oktober 2026 dokumentieren **48 Python-Tests, vier JavaScript-Prüfungen, 23 SQL-Tests und 26 Integrationsgruppen**. Die Integrationssuite baut temporäre UUID-Datenbanken aus den gelieferten Quellen neu auf und entfernt ausschließlich ihre eigenen Testdatenbanken. Befehle und Grenzen stehen in [tests/README.md](03_Finalisierungsphase/tests/README.md). Historische Nachweise behalten ihren ursprünglichen Prüfzeitpunkt; eine neue ZIP-Datei behauptet keinen neuen Anwendungstest.

Die SQL-Quellen liegen unter `03_Finalisierungsphase/database/`. `BookBridge_Gesamt.sql` ist ein bewachter psql-Einstieg für einen getrennten Referenzaufbau. Für die vollständige Anwendung ist `scripts/setup.ps1` einschließlich Rollen, Zugangsdaten und Migrationsprotokoll maßgeblich.

## PDF Unterlagen

- [Dreiseitiger Abschlussbericht](03_Finalisierungsphase/docs/BookBridge_Phase3_Abschlussbericht.pdf)
- [Abstract](03_Finalisierungsphase/docs/BookBridge_Abstract.pdf)
- [Gesamtdokumentation aller drei Phasen](03_Finalisierungsphase/docs/BookBridge_Gesamtdokumentation.pdf)
- [Repository und Abgabe](03_Finalisierungsphase/docs/BookBridge_Repository_und_Abgabe.pdf)
- [Präsentation der Phase 2](02_Erarbeitungs_Reflexionsphase/docs/BookBridge_Phase2_Praesentation.pdf)
- [Implementierung und Reflexion der Phase 2](02_Erarbeitungs_Reflexionsphase/docs/BookBridge_Phase2_Umsetzung.pdf)

Die Berichte liegen für die Einreichung als PDF vor. Bearbeitbare Wordfassungen bleiben außerhalb dieser PDF-Lieferung im lokalen Arbeitsprojekt. Persönliche Abgabedaten und die Dateibenennung können vor der Einreichung ergänzt werden. Die elektronische eidesstattliche Erklärung in myCampus wurde nach Angabe des Projektverantwortlichen bereits erledigt.

## Prüfsummen und erneute Paketierung

`MANIFEST.json` verzeichnet die tatsächlich gelieferten Quelldateien einschließlich der PDFs mit SHA-256. `SHA256SUMS.txt` prüft diese Dateien sowie `MANIFEST.json` und `PACKAGE_CHECK.json`; seine eigene Prüfsumme ist nicht enthalten. Die separate `.zip.sha256`-Datei prüft das ganze Archiv. Der Ordner `.git` gehört nicht zum Lieferarchiv.

Das [Paketierungswerkzeug](tools/package_delivery.py) unterstützt sowohl den Arbeitsordner mit `Phase 1/`, `Phase 2/` und `phase3/` als auch diese nummerierte Ordnerstruktur. Es setzt die vier finalen PDFs voraus; Worddateien sind optional.

```powershell
# Auswahl ohne Änderungen prüfen
python .\tools\package_delivery.py --root '.'
# Dateiliste und Prüfsummen nach freigegebenen Änderungen im aktuellen Ordner erneuern
python .\tools\refresh_publication.py --root '.' --write
# Neues Archiv zusätzlich erzeugen; vorhandene Archive werden nicht überschrieben
python .\tools\refresh_publication.py --root '.' --write --zip 'D:\Pfad\Abgabe_BookBridge_neu.zip'
```

Für `--zip` einen neuen Zielpfad direkt im Projektordner oder in dessen übergeordnetem Ordner angeben. Nach jeder Änderung an Berichten, Links oder README werden Dateiliste und Prüfsummen erneut erzeugt. Das Archiv vor der formalen Einreichung nach dem persönlichen Muster `Nachname_Vorname_Matrikelnummer_Kurskürzel.zip` benennen.

## Umfang und private Laufzeit

`.runtime/`, Datenbankzugänge, eigene Benutzerdateien, installierte Abhängigkeiten, Office-Sicherungskopien und Caches sind ausgeschlossen. Der mitgelieferte Datenbankexport enthält ausschließlich den synthetischen Phase-2-Ausgangsstand. Der HTTP-Dienst bindet an Loopback und ist für lokale Demonstration vorgesehen. Porto wird manuell bestätigt; reale Zahlungen, E-Mails und Versandaufträge werden nicht ausgelöst.
