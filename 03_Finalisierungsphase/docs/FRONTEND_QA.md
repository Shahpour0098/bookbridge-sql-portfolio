# Frontend-Prüfnotizen

Stand: 20.10.2026. Die Gestaltung, lokalen Bilddateien und Basistokens aus Phase 1 bleiben erhalten. Phase 3 ergänzt die angebundenen Konto-, Angebots-, Ausleih- und Administrationsansichten.

## Ausgeführte Quellprüfungen

- `node --check frontend/app.js`: erfolgreich.
- Gezielte Node-Prüfung mit den unveränderten Funktionen `api`/`loadSession` und kontrollierten Antworten: Nach 401 wird der anonyme CSRF-Token vor erneuter Anmeldung synchronisiert; die ursprüngliche Änderung wird nicht wiederholt; fehlgeschlagene Synchronisierung erzeugt keine Rekursion; überholte 401-/Synchronisierungsantworten überschreiben keine neuere Anmeldung.
- Wiederholbar mit Node.js aus dem Ordner `phase3`: `node frontend/tests/test_session_recovery.cjs`. Die vier Prüfungen benötigen keine Zusatzpakete und führen die Produktionsfunktionen direkt in einer VM aus; sie ersetzen keine Browserprüfung.
- HTML-Prüfung: 67 eindeutige statische IDs, 22 korrekt zugeordnete Beschriftungen, vier vorhandene lokale Ressourcen; die 32 direkt verwendeten ID-Selektoren sind statisch oder durch die Anwendung angelegt.
- Keine Interpretation von Servertext als HTML. Buchcover bleiben auf lokale Dateien beschränkt.
- `admin-content` wird als CSS-Klasse angelegt und mit derselben Klasse gelesen.
- Quellprüfung der Layouts für 375 und 768 Pixel: einspaltige Formulare und Karten auf schmalen Ansichten, gestapelte Adress-/Administrationszeilen, umgebrochene Aktionen und lange Texte. Eine Sichtprüfung im Browser ist zusätzlich erforderlich.

## Gezielte Browserprüfungen für die Integration

1. Adresse bearbeiten: bestehende Werte erscheinen; Änderung wird in Konto, Angebotsauswahl und neu vorbereiteten Sendungen übernommen. Nur eine Koordinate wird abgewiesen. Beide Koordinaten lassen sich bei einer reinen Lieferadresse entfernen; aktive Buchangebote müssen ihren Standort behalten.
2. Angebot bearbeiten: aktuelle Adresse, Übergabearten und aktive Wochenfenster erscheinen. Abholung ohne Zeitfenster, rückwärts laufende Zeiten und fehlende Übergabearten werden abgewiesen. Nach Änderung bleiben bereits angenommene Abholtermine und Anschriften unverändert.
3. Gegenvorschlag als verleihende Person und offene Verlängerung als ausleihende Person zurückziehen; ursprüngliche Anfrage beziehungsweise bestehende Frist bleibt erhalten.
4. Konto deaktivieren, erneut anmelden und eine laufende Ausleihe abschließen. Neue Angebote, Anfragen, Annahmen und Gegenvorschläge sind gesperrt. Eine aktive Administration kann Mitglieder reaktivieren und Angebote separat freigeben.
5. Aktive Administration: Mitglieder und Angebote laden, deaktivieren und reaktivieren; eigene Deaktivierung entfernt sofort die Administrationsansicht.
6. Während einer verzögerten Buchdetailantwort den Dialog schließen und einen anderen Dialog öffnen: die alte Antwort darf ihn nicht überschreiben. Dasselbe mit einer fehlgeschlagenen Antwort prüfen.
7. Fehlgeschlagenes Abmelden: Schaltfläche wird wieder bedienbar. Überholte Antworten paralleler Aktualisierungen ersetzen keine jüngeren Daten.
8. Bei gesetztem Rollenfilter aus einer Mitteilung zu einer ausgeblendeten Ausleihe springen: Ansicht wechselt auf „Alle“ und der betroffene Eintrag erhält den Tastaturfokus.
9. Umkreissuche ohne Koordinaten: Standortbereich öffnet sich, Rückmeldung erscheint und der Katalog bleibt bedienbar. Ungültige Zahlen in einem geschlossenen Standortbereich machen diesen sichtbar.
10. Tastatur und schmale Ansicht: Dialog schließen, Wochenfenster entfernen, Pflichtfelder und Fehlerrückmeldungen prüfen; keine horizontale Überbreite bei 375/768 Pixeln und langen Titeln/Namen/Adressen.

Diese Notizen behaupten keine bereits ausgeführte Browserprüfung; deren Ergebnisse werden in der zentralen Integrationsprüfung festgehalten.
