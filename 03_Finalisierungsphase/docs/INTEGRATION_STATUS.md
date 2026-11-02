# BookBridge Phase 3 Integrationsstand

Stand der lokalen Anwendung: 21. Oktober 2026.

Die deutsche Oberfläche aus Phase 1 verwendet die echte PostgreSQL-Datenbank
und die kontrollierten Geschäftsabläufe aus Phase 2. Die sechs ursprünglichen
SQL-Dateien sind unverändert erhalten. Die zusätzlichen Migrationen 07 bis 09
ergänzen Sitzungen, die benötigten Dienstrechte und die aufgeschobene
Konsistenzprüfung. Die Webanwendung läuft unter http://127.0.0.1:8767.

## Ausgeführte Prüfungen

| Ebene | Erfolgreich geprüft | Nachweis |
| --- | --- | --- |
| Python | 48 Regressionstests zu HTTP, Rollen, Datenschutz, Terminen und Windows-Prozessen | `evidence/release-tests-20261021/python-tests.txt` |
| JavaScript | Vier kontrollierte Prüfungen zur Wiederherstellung abgelaufener Sitzungen und zu überholten Antworten | `frontend/tests/test_session_recovery.cjs` |
| PostgreSQL | Alle 23 ursprünglichen Phase-2-Tests, einschließlich zweier gleichzeitig annehmender Verbindungen | `evidence/release-verification-20261021/phase2/test-report.json` |
| Integrierte API | 26 Prüfgruppen mit echten Sitzungen und Transaktionen, echter PDF-Erzeugung sowie vollständiger Abholung und Postausleihe | `evidence/release-verification-20261021/integration-report.json` |
| Windows-Betrieb | Wiederholte Einrichtung und Start, sicherer Stopp, vollständiger Neustart und Erhalt des Dateninhalts | `evidence/runtime-*.json` |
| Browser | Registrierung, Anmeldung, Adressen, Angebote, vollständige persönliche Ausleihe, Verlängerung, Rückgabe, Bewertung und Kontomoderation | `evidence/browser-20261020/browser-report.json` |

Die Datenbankprüfung baut aus `template0` neu auf. Der Ausgangsbestand enthält
18 Fachtabellen und 1.431 fiktive Datensätze. Die Suite entfernt ihre eigenen
Prüfdatenbanken wieder. Auch der Browserlauf verwendet eine eigene temporäre
Datenbank auf einem separaten Webport; er legt keine Testmitglieder oder
Testausleihen in der Hauptanwendung an.

## Metadaten und Erhalt der Betriebsdaten

Die erneute Messung trennt die 18 Fachbasistabellen mit **142 Spalten und 32 Fremdschlüsseln** von der öffentlichen Sicht mit 15 projizierten Spalten. Das technische Schema besitzt zwei weitere Tabellen mit insgesamt **acht Spalten** (Sitzungen: fünf; Migrationen: drei). Die frühere Angabe von 157 Fachspalten enthielt die 15 Sichtspalten; die Integrationsabfrage zählt jetzt ausschließlich Spalten von `BASE TABLE`.

Die frische Prüfdatenbank enthält 1.431 fiktive Fachdatenzeilen. Die vorhandene Hauptinstallation besitzt zum Messzeitpunkt 1.436 Fachzeilen und 25 Mitglieder; dieser gewachsene Betriebsbestand wurde nicht durch eine Neusaat ersetzt. Ihre gemessenen 10.786.483 Bytes Gesamtdatenbankgröße enthalten auch PostgreSQL-Systemobjekte und technische Tabellen. Die Fachrelationen einschließlich eigener Indizes und TOAST belegen 1.540.096 Bytes; die technischen Tabellen einschließlich Indizes 98.304 Bytes. Die Größen hängen vom Betriebszustand ab.

Die Laufzeit wurde mit konsistenten privaten Sicherungen und einer geprüften Kopie des gestoppten Clusters in den maßgeblichen Projektordner verlagert. Alle 20 Basistabellen behielten Zeilenanzahl und Inhalt; ursprünglicher und zuvor kopierter Datenordner bleiben erhalten. Der Hauptdienst läuft am neuen Ort auf 127.0.0.1:8767. Erneuter Start und sicherer Webneustart wurden dort geprüft. Eine neue Schutzprüfung verhindert, dass die PID-Datei einer laufend kopierten Datenbank den Prozess des ursprünglichen Ordners steuert.

Die aktuellen Zahlen, Geltungsbereiche, Installationsbefehle und Nachweisdateien stehen maschinenlesbar in `evidence/verified-metadata-20261021.json`. Frühere Nachweise vom 20. Oktober bleiben unverändert erhalten; die Browseraufnahmen beziehen sich weiterhin auf den dort dokumentierten Desktoplauf.

## Im Browser nachvollzogen

Ein neu registriertes Mitglied speicherte und bearbeitete eine synthetische
Adresse. Eine unvollständige Koordinatenpaarung wurde mit einer Rückmeldung
abgewiesen. Ein Angebot mit Abholung und Versand wurde angelegt; Adresse,
Wochenzeitfenster und Höchstdauer erschienen bei der Bearbeitung wieder und
wurden aktualisiert.

Ein zweites Konto fragte das Exemplar an. Die verleihende Person nahm mit
einem konkreten Berliner Abholfenster an. Nach der Empfangsbestätigung
erschien die kalendarische Rückgabefrist. Eine Verlängerung um drei Tage wurde
angefragt und genehmigt. Die Rückgabe wurde begonnen und vom Eigentümer
bestätigt; der Vorgang war abgeschlossen, das Buch wieder verfügbar und eine
Bewertung sowie die geschützte Rückgabebestätigung zugänglich.

Der Sprung aus einer Mitteilung zeigte auch eine durch den Rollenfilter
ausgeblendete Ausleihe wieder an und setzte den Fokus auf die richtige Karte.
Eine eigens für den Prüflauf berechtigte Administration konnte ein fiktives
Mitglied deaktivieren und wieder aktivieren. Der finale Hauptdienst wurde
mit den letzten Quellen neu gestartet; die Startseite und der öffentliche
Katalog wurden anschließend erneut im Browser geöffnet.

## Behobene Integrationsfehler

Der JavaScript-Einstieg wird ausdrücklich ausgeliefert. Die aufgeschobene
SQL-Prüfung läuft mit den benötigten, auf den Trigger begrenzten Rechten.
Native PDF-Abhängigkeiten werden mit der ausgewählten Python-Version geprüft.
Öffentliche Kataloganfragen erzeugen keine konkurrierenden Sitzungscookies.
Nach einem Sitzungsablauf erhält das Anmeldeformular einen frischen CSRF-Token;
schreibende Aktionen werden dabei nicht automatisch wiederholt.

Abgeschlossene Postausleihen zeigen keine später hinzugefügten privaten
Adressen. Vereinbarte Anschriften, Termine und Fristen bleiben bei Änderungen
am aktuellen Profil oder Wochenplan erhalten. Deaktivierte Mitglieder können
bestehende Vorgänge weiterhin abschließen; neue Angebote und Anfragen sind
gesperrt. Die Administration erhält keine Rechte für fremde Übergaben oder
Portobestätigungen.

## Einsatzumfang

Freigegeben ist der lokale Studien-Demonstrator. Die dokumentierten Prüfungen
sind kein Nachweis eines öffentlichen Produktionsbetriebs. Echte Zahlungen,
E-Mail-Zustellung, Versandaufträge und externes Geocoding sind weiterhin nicht
angebunden. Die responsive Gestaltung wurde im Quelltext geprüft; die
Browseraufnahmen dokumentieren die tatsächlich verwendete Desktopansicht.
Veröffentlichungsstand vom 2. November 2026: Code, PDF-Berichte und README sind im öffentlichen Repository bereitgestellt: https://github.com/Shahpour0098/bookbridge-sql-portfolio. Die oben dokumentierten Anwendungstests behalten ihren ursprünglichen Prüfzeitpunkt.
