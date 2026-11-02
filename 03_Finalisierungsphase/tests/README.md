# BookBridge Phase 3 prüfen

Die Prüfungen trennen Python-Grenzfälle, die unveränderten SQL-Geschäftsregeln
und die tatsächlich integrierte Anwendung. Python-Tests verwenden die durch
`scripts/setup.ps1` installierten projektlokalen Bibliotheken.

## Schnelle Regressionen

Im Phase-3-Ordner ausführen:

```powershell
C:\Python313\python.exe -m unittest discover -s tests -v
```

Diese Tests benötigen keine laufende Datenbank. Sie prüfen unter anderem
Sitzungsgrenzen, CSRF, geschützte Dokumente, erlaubte Eingabefelder,
Abholtermine bei beiden Berliner Zeitumstellungen und die sichere Zuordnung
des gestarteten Windows-Prozesses. Den Python-Pfad an die eigene Installation
anpassen.

## Echte PostgreSQL-Integration

Zuerst `scripts/setup.ps1` ausführen; die eigene Phase-3-Datenbank muss laufen.
Anschließend im Phase-3-Ordner:

```powershell
C:\Python313\python.exe .\tests\run_integration.py --output .\evidence\eigene-pruefung
```

Die Suite kontrolliert den registrierten Datenordner und erzeugt eine neue
UUID-Datenbank aus `template0`. Darin installiert sie die gelieferten
Migrationen, prüft den Phase-2-Ausgangsbestand und führt die ursprünglichen
SQL-Tests erneut aus. `phase2_regression.py` ist die unveränderte Testsuite aus
Phase 2. Deren Konkurrenzprüfung verwendet nochmals eine eigene UUID-Kopie.

Danach laufen echte Flask-Anfragen mit getrennten Cookies und echten
PostgreSQL-Transaktionen für Registrierung, Anmeldung, Angebote, Orts- und
Umkreissuche, Rechte, Gegenangebote, Abholung, Verlängerung, Hin- und
Rückversand, Portobestätigung, Rückgabe, Bewertungen, Mitteilungen und
PDF-Downloads. HTTP-Zeitpunkte für Geschäftsereignisse werden nicht simuliert.
Die Testkonten und Anschriften sind ausdrücklich fiktiv; es erfolgt kein
E-Mail-Versand und keine reale Zahlung.

Die Hauptdatenbank erhält dadurch keine Testdatensätze. Die ausschließlich
für diesen Aufruf erzeugten Datenbanken werden auch nach einem Fehler
entfernt. `integration-report.json` hält den Ausgang, die einzelnen Prüfungen
und das Entfernen der Prüfungsdatenbank fest; `phase2/test-report.json`
dokumentiert die SQL-Prüfungen. Eine synthetische PDF-Bestätigung erlaubt die
Kontrolle der tatsächlichen Dokumenterzeugung. Zugangsdaten und
Passwort-Hashes werden nicht exportiert.

Ein vorhandener Ergebnisordner wird beschrieben. Für getrennte Nachweise
jeweils einen neuen Ordnernamen verwenden oder `--output` weglassen; dann
wird ein Ordner mit Zeitstempel angelegt.
