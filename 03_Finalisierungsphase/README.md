# BookBridge – Phase 3

Phase 3 verbindet die deutsche Oberflaeche aus Phase 1 mit der PostgreSQL-Datenbank und den geprueften Ausleihablaeufen aus Phase 2. Die Anwendung laeuft lokal unter Windows im Browser: **http://127.0.0.1:8767**. Die Quelldateien aus Phase 2 bleiben in `database/phase2/` erhalten. Drei neue Migrationen ergaenzen die Anwendung: `07_application.sql` richtet Sitzungen und eingeschraenkte Webrechte ein; `08_application_editing.sql` erlaubt die benoetigten Adress- und Angebotsaenderungen; `09_deferred_validation.sql` gibt dem abschliessenden Ausleih-Trigger den erforderlichen Eigentuemer-Kontext mit festem, sicherem Suchpfad. Der Webdienst erhaelt dadurch keine allgemeinen Verwaltungsrechte.

## Einrichtung unter Windows

Voraussetzungen: Windows PowerShell, **Python 3.11 oder neuer mit pip** sowie **PostgreSQL 17**. Der PostgreSQL-Ordner muss `initdb.exe` und `pg_ctl.exe` enthalten. Ein vorhandener PostgreSQL-Systemdienst wird nicht verwendet. Python und PostgreSQL werden nicht systemweit durch dieses Projekt installiert.

PowerShell im entpackten Phase-3-Ordner oeffnen. Bei abweichenden Installationsorten die beiden Pfade anpassen:

```powershell
# Einmalig oder nach einer geprueften neuen Migration:
.\scripts\setup.ps1 -PythonPath 'C:\Python313\python.exe' -PostgresBin 'D:\PostgreSQL\17\bin'

# Starten; -OpenBrowser ist optional:
.\scripts\start.ps1 -OpenBrowser

# Anwendung und ausschliesslich deren eigene Datenbank beenden:
.\scripts\stop.ps1
```

Nach der Ersteinrichtung startet auch ein Doppelklick auf **BookBridge starten.cmd** die Anwendung und oeffnet den Browser. Start und Stopp verwenden den gespeicherten Python-Pfad. Bei einer wiederholten Einrichtung bleiben gespeicherte PostgreSQL-Pfade und der eigene Datenbankport erhalten, solange keine abweichenden Werte angegeben werden.

Wenn die lokale PowerShell-Ausfuehrungsrichtlinie Skripte blockiert, kann ein einzelner Aufruf ohne dauerhafte Aenderung der Richtlinie so gestartet werden:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PythonPath 'C:\Python313\python.exe' -PostgresBin 'D:\PostgreSQL\17\bin'
```

Der Installer speichert Python-Pakete in `.runtime/python` und erzeugt einen eigenen Datenbankcluster in `.runtime/pgdata` auf **127.0.0.1:55434**, Datenbank **bookbridge_phase3**. Phase 1, Phase 2, vorhandene Systemdatenbanken und deren Dienste werden nicht veraendert. Falls Port 55434 belegt ist, bei der ersten Einrichtung zum Beispiel `-Port 55435` ergaenzen; Start und Stopp verwenden anschliessend die gespeicherte Einstellung. Der Webport bleibt 8767.

Jede SQL-Migration wird zusammen mit ihrem SHA-256-Nachweis in einer Transaktion installiert. Wiederholte Einrichtung ueberspringt unveraenderte Migrationen und behaelt Mitglieder, Angebote, Ausleihen und Sitzungen bei. Eine nachtraeglich geaenderte, bereits installierte SQL-Datei fuehrt zu einem ausdruecklichen Abbruch; der Installer fuehrt keine Neusaat und kein Loeschen vorhandener Daten durch. SQL-Aenderungen nach Auslieferung benoetigen eine neue versionierte Migration.

Insgesamt werden acht Migrationen installiert: die fuenf benoetigten Phase-2-Dateien und die drei Anwendungsergaenzungen. `05_queries.sql` bleibt als Sammlung von Auswertungen enthalten. Sind die passenden Python-Pakete bereits eingerichtet, genuegt fuer eine neue SQL-Migration `scripts/setup.ps1 -SkipDependencies`. Nach einem Wechsel der Python-Version die Anwendung zuerst beenden und `setup.ps1` ohne diesen Schalter aufrufen; der Installer prueft auch die native Bildbibliothek und erzeugt ein echtes Probe-PDF.

## Erste Nutzung

1. Im Browser die lokale Adresse oeffnen und ein eigenes Mitgliedskonto registrieren. Es gibt kein gemeinsames Standardpasswort. Die fiktiven Phase-2-Mitglieder sind reine Testdaten und besitzen absichtlich keine gueltigen Anmeldepasswoerter.
2. Im Profil eine Adresse hinterlegen. Fuer aktive Angebote verlangt das Datenmodell gemeinsam gesetzte Breiten- und Laengengrade. Koordinaten koennen manuell eingetragen werden; ein externer Geokodierungsdienst ist nicht angebunden.
3. Ein Buch mit Autor, Genre, Sprache, Ausleihdauer und Uebergabeart anbieten. Abholung benoetigt mindestens ein gueltiges woechentliches Zeitfenster.
4. Fuer einen vollstaendigen Test ein zweites eigenes Konto in einem zweiten Browserprofil verwenden. Eine Anfrage an ein selbst angebotenes Buch ist fachlich gesperrt. Mit den beiden Konten lassen sich Anfrage, Annahme, Empfang, Verlaengerung, Rueckgabe und Bewertung nachvollziehen.

Der Katalog zeigt nur oeffentliche Ortsangaben. Private Abhol- und Versandanschriften sowie PDF-Bestaetigungen sind den berechtigten Teilnehmern vorbehalten. Die SQL-Workflows pruefen Rollen, Statuswechsel, Terminfenster und historische Momentaufnahmen weiterhin verbindlich. Die Webanwendung authentifiziert die handelnde Person und uebernimmt deren Identitaet aus der serverseitigen Sitzung.

## Profil, Angebote und Kontostatus

Im Profil lassen sich Name, Passwort und eigene Adressen bearbeiten. Unter den eigenen Angeboten koennen Zustand, Ausleihdauer, Notizen, Standort, Uebergabearten und woechentliche Abholfenster angepasst sowie Angebote pausiert werden. Bereits vereinbarte Abholtermine und gespeicherte Versandanschriften bleiben als historische Momentaufnahmen erhalten. Die gemeinsam verwendeten bibliografischen Buchdaten werden durch eine Angebotsaenderung nicht ueberschrieben.

Die Kontodeaktivierung im Profil pausiert zugleich die eigenen Angebote. Bestehende Ausleihen, Rueckgaben und Mitteilungen bleiben zugaenglich; neue Angebote und neue Ausleihvorgaenge sind gesperrt. Eine spaetere Reaktivierung erfolgt durch einen aktiven Administrator. Angebote werden dabei nicht automatisch wieder freigeschaltet.

## Lokale Administration

Zuerst ein eigenes Konto im Browser registrieren. Danach kann der lokale Betreiber genau dieses aktive Konto mit dem eingerichteten Python zu einem Administrator machen:

```powershell
C:\Python313\python.exe .\scripts\promote_admin.py --email 'mein-konto@example.org'
```

Python-Pfad und Adresse an das eigene Konto anpassen; die Beispieladresse erzeugt kein Konto. Das Werkzeug prueft den eigenen Cluster und Datenordner und aendert ausschliesslich die Rolle eines vorhandenen aktiven Mitglieds. Es verarbeitet kein Passwort. Nach dem Neuladen erscheint die Verwaltung fuer Mitgliedsaktivierung und Angebotspausierung. Administratoren erhalten dadurch keinen Zugriff auf fremde Ausleihaktionen oder private Dokumente. Die Registrierung im Browser kann keine Administratorrolle vergeben.

## Daten und Betrieb

`.runtime/config.json` enthaelt die Zugangsdaten des eingeschraenkten Web-Datenbankkontos; `.runtime/owner.json` enthaelt die separat erzeugten Verwaltungsdaten des eigenen Clusters. Diese Dateien und der gesamte Laufzeitordner sind vertraulich, werden unter Windows auf das aktuelle Benutzerkonto und SYSTEM beschraenkt und gehoeren nicht in eine oeffentliche Abgabe oder ein Git-Repository. Passwoerter werden zufaellig erzeugt und nicht als Kommandozeilenargument ausgegeben. Der Webdienst verwendet keine Superuser-Anmeldung. Kontopasswoerter werden als gesalzene scrypt-Hashes gespeichert; Sitzungen liegen mit gehashtem Cookie-Token in der Datenbank. Schreibende Browseranfragen benoetigen einen CSRF-Token.

Zum regulaeren Beenden `scripts/stop.ps1` verwenden. Mit `-KeepDatabase` bleibt die eigene Datenbank fuer weitere lokale Pruefungen aktiv. `scripts/start_database.ps1` und `scripts/stop_database.ps1` steuern ausschliesslich den registrierten Cluster dieses Projektordners. Der Server wird im Hintergrund ohne zusaetzliches Fenster gestartet; Prozesskennung, Skriptpfad, Python-Pfad und Prozessstartzeit werden vor dem Beenden geprueft.

Bei einem Startproblem zuerst `.runtime/server.err.log`, `.runtime/postgres.log` und gegebenenfalls `.runtime/pg-control.log` pruefen. `.runtime/installation.json` enthaelt eine Zusammenfassung ohne Passwoerter. Den Laufzeitordner nicht waehrend laufender Prozesse verschieben. Fuer eine quelloffene Weitergabe den Projektordner **ohne `.runtime/` und ohne `__pycache__/`** kopieren und am Ziel neu einrichten. Eine Datensicherung mit eigenen Nutzerdaten erfordert dagegen auch eine gesicherte PostgreSQL-Sicherung und die geschuetzten Dokumentdateien.

## Pruefungen und Lieferumfang

Die Befehle und Grenzen der Pruefungen stehen in `tests/README.md`. Schnelle Regressionen laufen mit `C:\Python313\python.exe -m unittest discover -s tests -v`; fuer die echte Datenbankintegration nach der Einrichtung `C:\Python313\python.exe .\tests\run_integration.py` ausfuehren. Die Integrationssuite erstellt eigene temporaere Datenbanken, verwendet ausschliesslich fiktive Konten und entfernt ihre Datenbanken wieder. Sie veraendert keine Mitgliedsdaten der Hauptanwendung. Die vier JavaScript-Pruefungen zur Wiederherstellung abgelaufener Sitzungen laufen mit `node .\frontend\tests\test_session_recovery.cjs`; Node.js wird nur fuer diese Entwicklerpruefung benoetigt.

Der aktuelle Nachweis vom 21. Oktober 2026 in `evidence/release-verification-20261021/` enthaelt 26 erfolgreiche Pruefgruppen der integrierten Anwendung und alle 23 urspruenglichen SQL-Tests. `evidence/release-tests-20261021/` dokumentiert zusaetzlich 48 erfolgreiche Python-Tests und die vier JavaScript-Pruefungen. Die Laufzeitnachweise dokumentieren wiederholbare Migrationen, den sicheren Windows-Prozessstopp, vollstaendigen Neustart ohne Datenverlust und die native PDF-Erzeugung. Browseraufnahmen und das zugehoerige Protokoll liegen unter `evidence/browser-20261020/`. Fruehere Fehlerdiagnosen und private Laufzeitdateien gehoeren nicht zum Lieferpaket.

Das gemeinsame GitHub-Abgabearchiv enthaelt alle drei Phasen mit Quellcode, Datenmodell, Migrationen, Oberflaeche, Startskripten, Tests und ausgewaehlten synthetischen Nachweisen. Im Hauptordner des entpackten Pakets prueft `SHA256SUMS.txt` die enthaltenen Dateien; `MANIFEST.json` ordnet sie den Quellen zu. Die separate Datei mit der Endung `.zip.sha256` prueft das gesamte Archiv. Hinweise zum Neubau nach eigenen Ergaenzungen stehen in der uebergeordneten README und in `tools/package_delivery.py`. Am Ziel wird nach dem Entpacken eine neue lokale Laufzeit eingerichtet.

## Gepruefte Struktur und Datenmenge

Das Fachschema umfasst **18 Basistabellen mit 142 Spalten und 32 Fremdschluesseln**. Die oeffentliche Katalogsicht projiziert 15 Spalten; diese Sichtspalten sind keine weiteren Fachattribute. Das technische Schema `bookbridge_app` ergaenzt zwei Tabellen mit insgesamt **acht Spalten**: fuenf fuer Sitzungen und drei fuer das Migrationsprotokoll.

Eine frische Installation enthaelt 1.431 fiktive Fachdatenzeilen. Bereits genutzte Installationen koennen weitere Mitglieder, Adressen oder Angebote enthalten; solche Nutzerdaten bleiben bei Start, Migration und den isolierten Pruefungen erhalten. `evidence/verified-metadata-20261021.json` trennt den reproduzierbaren Saatbestand von den gemessenen Betriebszahlen. Die dortige Gesamtdatenbankgroesse umfasst auch PostgreSQL-Systemkataloge, Indizes und technische Tabellen und ist deshalb kein Mass fuer reine Fachdaten.

Bei der geprueften Verlagerung in den neuen Projektordner wurden die eigenen alten Prozesse eindeutig identifiziert, konsistente private Sicherungen erstellt und der gestoppte Datenordner bytegenau kopiert. Alte und zuvor kopierte Datenordner blieben erhalten. Alle 20 Fach- und Technikbasistabellen behielten Inhalt und Zeilenanzahl. `evidence/runtime-relocation-20261021.json` dokumentiert den Vorgang ohne Zugangsdaten. Ein kopierter `postmaster.pid`, der noch auf einen anderen Datenordner verweist, fuehrt jetzt zum sicheren Abbruch der Prozesssteuerung; solche Dateien werden nicht automatisch entfernt.

## Umfang und Grenzen

Die Anwendung ist ein lokaler Studien-Demonstrator. Porto wird vereinbart und manuell als gezahlt beziehungsweise empfangen bestaetigt. Es gibt keine Zahlungsschnittstelle, keinen Versanddienst und keinen realen E-Mail-Versand. Versandunternehmen und Sendungsnummern werden dokumentiert; PDF-Bestaetigungen werden lokal erzeugt und geschuetzt heruntergeladen. Fiktive Test-E-Mail-Datensaetze aus Phase 2 loesen keine Nachrichten aus. Die Bindung an 127.0.0.1 ist fuer den lokalen Einsatz vorgesehen; ein oeffentlicher Hostingbetrieb gehoert nicht zu dieser Lieferung.

API-Schnittstellen stehen in `docs/API_CONTRACT.md`; Bedienoberflaeche und Pruefungen sind in `docs/` und `tests/` beschrieben. Die Abschlussberichte unter `docs/` liegen in dieser Lieferung als PDF vor. Oeffentliches Repository: https://github.com/Shahpour0098/bookbridge-sql-portfolio . Der gleiche Link steht in der uebergeordneten README und in den Abschlussunterlagen.
