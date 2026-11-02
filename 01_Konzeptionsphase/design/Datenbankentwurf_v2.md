# BookBridge Datenbankentwurf Version 2

Vollständiger Entwurf; kein Nachweis einer ausgeführten SQL-Implementierung.

18 Entitäten · 142 Attribute · 32 Fremdschlüsselbeziehungen

## users

Registrierte Mitglieder und Administratoren; Gäste sind keine gespeicherten Benutzer.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| user_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| first_name | VARCHAR(80) | nein |  | Vorname. |
| last_name | VARCHAR(80) | nein |  | Nachname. |
| email | VARCHAR(254) | nein |  | Kontakt- und Anmeldeadresse. UNIQUE über lower(email); nicht leer |
| password_hash | TEXT | nein |  | Mit einem geeigneten Passwortverfahren erzeugter Hash; niemals Klartext. |
| role | VARCHAR(10) | nein |  | Mitglied oder Administrator. member  /  admin |
| is_active | BOOLEAN | nein |  | Anmeldung und neue Aktionen zugelassen. |
| created_at | TIMESTAMPTZ | nein |  | Zeitpunkt der Registrierung. |

- Pflichttexte sind nach trim nicht leer; E-Mail wird für den Vergleich kleingeschrieben.

## addresses

Aktuelle private Anschriften eines Benutzers; eine Anschrift kann mehrere Exemplare verorten.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| address_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| user_id | BIGINT | nein | FK → users.user_id | Eigentümer der Anschrift. |
| street | VARCHAR(200) | nein |  | Straße und Hausnummer. |
| postal_code | VARCHAR(20) | nein |  | Postleitzahl als Text. |
| city | VARCHAR(100) | nein |  | Ort. |
| country_code | CHAR(2) | nein |  | ISO-Ländercode in Großbuchstaben. zwei Buchstaben |
| latitude | NUMERIC(9,6) | ja |  | WGS84-Breitengrad. -90 bis 90; gemeinsam mit longitude NULL oder gesetzt |
| longitude | NUMERIC(9,6) | ja |  | WGS84-Längengrad. -180 bis 180; gemeinsam mit latitude NULL oder gesetzt |
| created_at | TIMESTAMPTZ | nein |  | Anlagezeitpunkt. |

- latitude und longitude sind gemeinsam NULL oder gesetzt; Wertebereiche und country_code prüfen.

## publishers

Verlage bibliografischer Ausgaben.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| publisher_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| name | VARCHAR(150) | nein |  | Verlagsname. UNIQUE; nicht leer |


## genres

Kontrolliertes Genre je Ausgabe; Mehrfachgenres sind nicht Teil des Entwurfs.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| genre_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| name | VARCHAR(80) | nein |  | Genrebezeichnung. UNIQUE; nicht leer |


## languages

Primäre Sprache einer Ausgabe.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| language_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| code | VARCHAR(10) | nein |  | Sprachcode, beispielsweise de oder en. UNIQUE; nicht leer |
| name | VARCHAR(80) | nein |  | Lesbare Sprachbezeichnung. UNIQUE; nicht leer |


## authors

Personen oder benannte Autorengruppen; Namen sind nicht zwingend eindeutig.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| author_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| display_name | VARCHAR(150) | nein |  | Anzuzeigender Autorenname. nicht leer |


## books

Titel und gemeinsame bibliografische Eigenschaften einer bestimmten Ausgabe, unabhängig vom Besitzer.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| book_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| title | VARCHAR(200) | nein |  | Buchtitel. nicht leer |
| subtitle | VARCHAR(200) | ja |  | Optionaler Untertitel. |
| isbn | VARCHAR(13) | ja |  | Normalisierte ISBN-10 oder ISBN-13 ohne Trennzeichen. UNIQUE falls gesetzt; Format und Prüfziffer validieren |
| publisher_id | BIGINT | ja | FK → publishers.publisher_id | Verlag der Ausgabe; unbekannter Verlag ist zulässig. |
| publication_year | SMALLINT | ja |  | Erscheinungsjahr; unbekannt zulässig. 1450 bis 2100 |
| genre_id | BIGINT | nein | FK → genres.genre_id | Ein primäres Genre. |
| language_id | BIGINT | nein | FK → languages.language_id | Eine primäre Sprache. |
| description | TEXT | ja |  | Optionale bibliografische Beschreibung. |
| created_at | TIMESTAMPTZ | nein |  | Erfassungszeitpunkt. |


## book_authors

Auflösung der N:M-Beziehung zwischen Ausgaben und Autoren.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| book_id | BIGINT | nein | PK FK → books.book_id | Zugeordnete Ausgabe. |
| author_id | BIGINT | nein | PK FK → authors.author_id | Zugeordneter Autor. |
| author_order | SMALLINT | nein |  | Reihenfolge in der Autorennennung. größer 0 |

- Zusammengesetzter PK (book_id, author_id).
- UNIQUE (book_id, author_order).
- Jede Katalogausgabe hat mindestens eine Autorenzuordnung; deferred Prüfung am Transaktionsende.

## book_copies

Individuelles Buch eines Eigentümers mit Angebotsbedingungen; Verfügbarkeit wird abgeleitet.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| copy_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| book_id | BIGINT | nein | FK → books.book_id | Bibliografische Ausgabe. |
| owner_id | BIGINT | nein | FK → users.user_id | Eigentümer; Eigentumsübertragungen sind nicht Projektumfang. |
| pickup_address_id | BIGINT | ja | FK → addresses.address_id | Standort und gegebenenfalls Abholanschrift des Eigentümers; bei Entwurf optional. |
| condition | VARCHAR(12) | nein |  | Zustand dieses Exemplars. new  /  very_good  /  good  /  used |
| max_loan_days | SMALLINT | nein |  | Maximale vereinbarte Gesamtdauer einschließlich genehmigter Verlängerungen. 1 bis 90 |
| allow_pickup | BOOLEAN | nein |  | Persönliche Übergabe erlaubt. |
| allow_shipping | BOOLEAN | nein |  | Postalische Übergabe erlaubt. |
| is_active | BOOLEAN | nein |  | Exemplar als Angebot freigeschaltet. |
| notes | TEXT | ja |  | Optionale Hinweise zum Exemplar oder zur Übergabe. |
| created_at | TIMESTAMPTZ | nein |  | Erfassungszeitpunkt. |

- Mindestens eine Übergabeart ist erlaubt.
- Aktivierung nur mit Standortkoordinaten und vollständigen Katalogdaten.
- owner_id bleibt unverändert; Deaktivierung erhält die Ausleihhistorie.

## pickup_slots

Wiederkehrende lokale Wochenzeitfenster für ein bestimmtes Exemplar.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| slot_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| copy_id | BIGINT | nein | FK → book_copies.copy_id | Exemplar, für das das Zeitfenster gilt. |
| weekday | SMALLINT | nein |  | ISO-Wochentag in Europe/Berlin. 1 Montag bis 7 Sonntag |
| start_time | TIME | nein |  | Lokaler Beginn ohne Zeitzone. |
| end_time | TIME | nein |  | Lokales Ende am selben Tag. größer als start_time |
| is_active | BOOLEAN | nein |  | Für neue Abholvereinbarungen auswählbar. |

- UNIQUE (copy_id, weekday, start_time, end_time).
- Überlappende aktive Zeitfenster desselben Exemplars am selben Wochentag werden abgewiesen.

## loans

Anfrage, verbindliche Vereinbarung und Rückgabe eines Exemplars; Teilnehmer sind während des Vorgangs unveränderlich.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| loan_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| copy_id | BIGINT | nein | FK → book_copies.copy_id | Angefragtes Exemplar. |
| borrower_id | BIGINT | nein | FK → users.user_id | Anfragende und ausleihende Person; darf nicht Eigentümer sein. |
| handover_mode | VARCHAR(8) | nein |  | Vereinbarte Übergabeart. pickup  /  shipping |
| requested_days | SMALLINT | nein |  | Vom Mitglied beantragte Anfangsdauer. 1 bis 90 |
| agreed_days | SMALLINT | ja |  | Verbindlich vereinbarte Anfangsdauer. 1 bis max_loan_days_snapshot |
| max_loan_days_snapshot | SMALLINT | ja |  | Bei Annahme eingefrorene Höchstdauer des Angebots. 1 bis 90 |
| status | VARCHAR(12) | nein |  | Zustand des Vorgangs. requested  /  accepted  /  outbound  /  active  /  returning  /  completed  /  rejected  /  cancelled |
| pickup_slot_id | BIGINT | ja | FK → pickup_slots.slot_id | Gewähltes Wochenzeitfenster für persönliche Abholung. |
| pickup_start_at | TIMESTAMPTZ | ja |  | Vereinbarter konkreter Beginn der Abholung; als Momentaufnahme eingefroren. |
| pickup_end_at | TIMESTAMPTZ | ja |  | Vereinbartes konkretes Ende der Abholung. |
| pickup_address_snapshot | TEXT | ja |  | Eingefrorene vollständige Abholanschrift einschließlich Name. |
| requested_at | TIMESTAMPTZ | nein |  | Zeitpunkt der Anfrage. |
| accepted_at | TIMESTAMPTZ | ja |  | Verbindliche Einigung durch Eigentümer oder Annahme eines Gegenvorschlags durch den Ausleiher. |
| received_at | TIMESTAMPTZ | ja |  | Vom Ausleiher bestätigter Erhalt; startet die Leihfrist. |
| due_date | DATE | ja |  | Lokaler Rückgabetag in Europe/Berlin einschließlich genehmigter Verlängerungen. |
| return_started_at | TIMESTAMPTZ | ja |  | Vom Ausleiher gemeldete persönliche Rückgabe oder postalische Rücksendung. |
| completed_at | TIMESTAMPTZ | ja |  | Vom Eigentümer bestätigter Rückerhalt; beendet die Sperre. |
| rejected_at | TIMESTAMPTZ | ja |  | Ablehnung durch den Eigentümer. |
| cancelled_at | TIMESTAMPTZ | ja |  | Zulässige Stornierung vor Übergabe. |
| cancelled_by_user_id | BIGINT | ja | FK → users.user_id | Stornierender Teilnehmer. |

- Partieller UNIQUE-Index auf copy_id für accepted, outbound, active, returning.
- Keine Eigenleihe; erlaubte Übergabeart und aktives Angebot werden bei Anfrage und Annahme geprüft.
- Unveränderliche Teilnehmer: Eigentümer ergibt sich aus dem dauerhaft unveränderlichen book_copies.owner_id.
- requested: agreed_days/max_loan_days_snapshot/accepted_at und sämtliche Erhalts-/Frist-/Rückgabe-/Terminalwerte NULL.
- accepted/outbound: Annahme und Dauer gesetzt; received_at/due_date/return_started_at/completed_at/rejected_at/cancelled_at NULL.
- active: Annahme, Erhalt und due_date gesetzt; return_started_at/completed_at/rejected_at/cancelled_at NULL.
- returning: zusätzlich return_started_at gesetzt; completed_at/rejected_at/cancelled_at NULL.
- completed: zusätzlich completed_at gesetzt; rejected_at/cancelled_at NULL.
- rejected: nur requested_at und rejected_at als Ereignisse; keine Einigung, Frist oder Erhalt/Rückgabe.
- cancelled: cancelled_at und cancelled_by_user_id gesetzt; Annahme/Dauer entweder vollständig gesetzt oder vollständig NULL; kein Erhalt/Frist/Rückgabe/rejected_at.
- cancelled_by_user_id ist genau dann gesetzt, wenn cancelled_at gesetzt ist. Ereigniszeiten sind chronologisch gemäß R16.
- shipping: alle pickup-Felder NULL; angenommene pickup-Ausleihe: alle pickup-Felder gesetzt und pickup_end_at > pickup_start_at.

## loan_proposals

Historie alternativer Anfangsdauern; Vorschläge stammen vom Eigentümer.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| proposal_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| loan_id | BIGINT | nein | FK → loans.loan_id | Noch unverbindliche Anfrage. |
| proposed_by_user_id | BIGINT | nein | FK → users.user_id | Vorschlagender Eigentümer. |
| proposed_days | SMALLINT | nein |  | Alternative Anfangsdauer. 1 bis aktuelle max_loan_days |
| status | VARCHAR(10) | nein |  | Entscheidung zum Gegenvorschlag. pending  /  accepted  /  rejected  /  withdrawn |
| proposed_at | TIMESTAMPTZ | nein |  | Vorschlagszeitpunkt. |
| decided_by_user_id | BIGINT | ja | FK → users.user_id | Ausleiher bei Annahme/Ablehnung; Eigentümer bei Rücknahme; beendender Teilnehmer bei automatischem Schließen. |
| decided_at | TIMESTAMPTZ | ja |  | Zeitpunkt der Entscheidung. |

- Höchstens ein pending-Vorschlag je loan_id.
- Annahme eines Vorschlags und Reservierung des Exemplars erfolgen in einer Transaktion.
- pending genau dann, wenn entschiedenes Datum und Person beide NULL sind; andere Status verlangen beide Werte. decided_at >= proposed_at.

## loan_extensions

Beantragte zusätzliche Tage und deren Entscheidung mit nachvollziehbarer Änderung der Frist.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| extension_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| loan_id | BIGINT | nein | FK → loans.loan_id | Aktive Ausleihe; Antragsteller ist ihr borrower_id. |
| extra_days | SMALLINT | nein |  | Zusätzliche Kalendertage. 1 bis 90 |
| status | VARCHAR(10) | nein |  | Antragsentscheidung. pending  /  approved  /  rejected  /  withdrawn |
| requested_at | TIMESTAMPTZ | nein |  | Antragszeitpunkt. |
| decided_by_user_id | BIGINT | ja | FK → users.user_id | Eigentümer bei Genehmigung/Ablehnung, Ausleiher bei Rücknahme. |
| decided_at | TIMESTAMPTZ | ja |  | Entscheidungszeitpunkt. |
| old_due_date | DATE | ja |  | Frist unmittelbar vor einer Genehmigung. |
| new_due_date | DATE | ja |  | Frist nach genau einmaliger Addition der extra_days. |

- Höchstens ein pending-Antrag je loan_id.
- Genehmigungen insgesamt plus agreed_days überschreiten max_loan_days_snapshot nicht.
- pending ohne Entscheidungspaar; andere Status mit entschiedenem Datum und Person. decided_at >= requested_at.
- Nur approved setzt beide Fristwerte; new_due_date = old_due_date + extra_days. Sonst sind beide NULL.

## payments

Eine gemeinsame manuell bestätigte Portozahlung für Hin- und Rückweg einer postalischen Ausleihe.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| payment_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| loan_id | BIGINT | nein | FK → loans.loan_id | Postalischer Vorgang. |
| outbound_fee | NUMERIC(8,2) | nein |  | Vereinbartes Hinporto in EUR. größer oder gleich 0 |
| return_fee | NUMERIC(8,2) | nein |  | Vereinbartes Rückporto in EUR. größer oder gleich 0 |
| currency | CHAR(3) | nein |  | Währung der Portobeträge. EUR |
| status | VARCHAR(10) | nein |  | Zahlungsmeldung und manuelle Bestätigung. pending  /  reported  /  confirmed  /  cancelled |
| created_at | TIMESTAMPTZ | nein |  | Anlage der Portovereinbarung. |
| reported_at | TIMESTAMPTZ | ja |  | Vom Ausleiher gemeldete Zahlung. |
| confirmed_by_user_id | BIGINT | ja | FK → users.user_id | Bestätigender Eigentümer. |
| confirmed_at | TIMESTAMPTZ | ja |  | Manuelle Eingangsbestätigung. |

- UNIQUE (loan_id).
- Keine Bank-/Kartendaten und kein Zahlungs-Gateway.
- Bestätigte Portobeträge und Bestätigung bleiben unverändert.
- pending ohne Meldung/Bestätigung; reported mit reported_at, ohne Bestätigung; confirmed mit Meldung und vollständigem Bestätigungspaar; cancelled ohne Bestätigungspaar.
- Vorhandene Zeitpunkte: created_at <= reported_at <= confirmed_at.

## shipments

Je eine Hin- und Rücksendung mit unveränderlichen Adressmomentaufnahmen.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| shipment_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| loan_id | BIGINT | nein | FK → loans.loan_id | Postalischer Leihvorgang. |
| direction | VARCHAR(8) | nein |  | Richtung relativ zum Leihvorgang. outbound  /  return |
| status | VARCHAR(8) | nein |  | Fortschritt einer einzelnen Sendung. prepared  /  sent  /  received |
| sender_address_id | BIGINT | nein | FK → addresses.address_id | Ausgewählte Anschrift des richtungsabhängigen Absenders. |
| recipient_address_id | BIGINT | nein | FK → addresses.address_id | Ausgewählte Anschrift des richtungsabhängigen Empfängers. |
| sender_address_snapshot | TEXT | nein |  | Name, Straße/Hausnummer, PLZ, Ort und Land bei Vorbereitung. |
| recipient_address_snapshot | TEXT | nein |  | Name, Straße/Hausnummer, PLZ, Ort und Land bei Vorbereitung. |
| carrier | VARCHAR(80) | ja |  | Optionales Versandunternehmen. |
| tracking_number | VARCHAR(120) | ja |  | Optionale Sendungsnummer. |
| prepared_at | TIMESTAMPTZ | nein |  | Zeitpunkt der Vorbereitung und Erstellung der Adressmomentaufnahmen. |
| sent_at | TIMESTAMPTZ | ja |  | Bestätigter Versand durch den Absender. |
| received_at | TIMESTAMPTZ | ja |  | Bestätigter Erhalt durch den Empfänger. |
| receipt_confirmed_by | BIGINT | ja | FK → users.user_id | Ausleiher beim Hinweg, Eigentümer beim Rückweg. |

- UNIQUE (loan_id, direction): höchstens zwei Sendungen je Ausleihe.
- Adressmomentaufnahmen werden nach Erstellung nicht aus Profilanschriften aktualisiert.
- prepared ohne Versand/Erhalt/Bestätiger; sent mit sent_at, ohne Erhalt/Bestätiger; received mit allen drei Werten.
- Vorhandene Zeitpunkte: prepared_at <= sent_at <= received_at.

## notifications

Persönliche Mitteilungen als Datensätze; Test-E-Mails benötigen keinen realen Maildienst.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| notification_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| recipient_user_id | BIGINT | nein | FK → users.user_id | Empfänger der Mitteilung. |
| loan_id | BIGINT | ja | FK → loans.loan_id | Optionaler fachlicher Bezug zur Ausleihe. |
| channel | VARCHAR(10) | nein |  | Ausgabekanal im Demonstrator. in_app  /  test_email |
| message | TEXT | nein |  | Mitteilungstext ohne Passwörter oder unnötige private Anschriften. |
| status | VARCHAR(10) | nein |  | Bearbeitungsstatus des Datensatzes. queued  /  delivered  /  failed |
| created_at | TIMESTAMPTZ | nein |  | Anlagezeitpunkt. |
| delivered_at | TIMESTAMPTZ | ja |  | Ausgabe oder simulierte Zustellung. |
| read_at | TIMESTAMPTZ | ja |  | Optionaler Lesebestätigungszeitpunkt. |

- Nur delivered hat delivered_at; queued/failed haben delivered_at/read_at NULL. read_at verlangt delivered und read_at >= delivered_at >= created_at.

## generated_documents

Geplante oder erzeugte PDF-Bestätigungen; der Status unterscheidet Metadaten von tatsächlich erzeugten Dateien.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| document_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| loan_id | BIGINT | nein | FK → loans.loan_id | Ausleihe, für die das Dokument vorgesehen ist. |
| shipment_id | BIGINT | ja | FK → shipments.shipment_id | Optionaler Bezug auf eine Sendung desselben Vorgangs. |
| recipient_user_id | BIGINT | nein | FK → users.user_id | Berechtigter Teilnehmer als Dokumentempfänger. |
| document_type | VARCHAR(20) | nein |  | Fachlicher Dokumenttyp. loan_confirmation  /  shipment_summary  /  return_confirmation |
| status | VARCHAR(8) | nein |  | Ob die Datei nur geplant ist oder tatsächlich vorliegt. planned  /  created  /  failed |
| storage_path | TEXT | ja |  | Relativer geschützter Dateipfad; keine öffentlich erreichbare URL. |
| created_at | TIMESTAMPTZ | nein |  | Anlage der Dokumentanforderung. |
| generated_at | TIMESTAMPTZ | ja |  | Zeitpunkt erfolgreicher Dateierzeugung. |

- Dokument mit shipment_id gehört zum selben loan_id wie die Sendung.
- status=created erfordert storage_path und generated_at; planned/failed behaupten keine vorhandene Datei.
- created genau dann, wenn storage_path und generated_at beide gesetzt sind; planned/failed ohne beide Werte. generated_at >= created_at.

## reviews

Je Teilnehmer eine Bewertung eines abgeschlossenen Leihvorgangs.

| Attribut | Typ | NULL | Schlüssel | Beschreibung |
|---|---|---|---|---|
| review_id | BIGINT | nein | PK  | Technischer Primärschlüssel; als Identity erzeugt. |
| loan_id | BIGINT | nein | FK → loans.loan_id | Abgeschlossene Ausleihe. |
| reviewer_id | BIGINT | nein | FK → users.user_id | Bewertender Eigentümer oder Ausleiher. |
| rating | SMALLINT | nein |  | Bewertungsskala. 1 bis 5 |
| comment | TEXT | ja |  | Optionaler Kommentar. |
| created_at | TIMESTAMPTZ | nein |  | Bewertungszeitpunkt nach Abschluss. |

- UNIQUE (loan_id, reviewer_id).
- Nur die beiden Teilnehmer einer completed-Ausleihe dürfen bewerten; daraus folgen höchstens zwei Bewertungen.

## Geschäftsregeln

### R01 Rollen und Teilnehmer

Gast ist anonym. users.role speichert member oder admin; Eigentümer und Ausleiher sind kontextabhängige Rollen. Ein Administrator moderiert Konten und Angebote, bestätigt jedoch keine fremden Übergaben, Zahlungen oder Rückgaben. Kontodeaktivierung deaktiviert eigene Angebote atomar und verhindert neue Anfragen/Annahmen; bestehende Vorgänge dürfen abgeschlossen werden. Erneute Kontoaktivierung aktiviert Angebote nicht automatisch.

Durchsetzung: Anwendungsberechtigung und Datenbankfunktionen

### R02 Standort und Sichtbarkeit

Für jede aktive book_copy muss pickup_address_id auf eine Anschrift des Eigentümers mit gesetztem Koordinatenpaar zeigen. Die Anschrift dient auch bei rein postalischen Angeboten als Standort. Gäste sehen nur Ort/PLZ, keine vollständige Anschrift oder präzisen Koordinaten. Testdaten enthalten WGS84-Koordinaten; keine externe Geocoding-Abhängigkeit.

Durchsetzung: CHECK für Wertebereiche; Transaktion/Trigger für Aktivierung und Adressänderung

### R03 Katalog und Aktivierung

Jede Katalogausgabe besitzt mindestens einen Autor; die Mindestbeteiligung wird am Transaktionsende geprüft. Aktive Angebote erfordern einen aktiven Eigentümer und mindestens eine erlaubte Übergabeart. ISBN ist optional und normalisiert; vorhandene ISBN sind eindeutig. Unbekannter Verlag und Erscheinungsjahr sind zulässig.

Durchsetzung: FK/UNIQUE/CHECK plus deferred Mindestautor- und Aktivierungsprüfung

### R04 Eigentum und Löschungen

book_copies.owner_id und addresses.user_id bleiben unverändert; Eigentumsübertragungen sind kein Projektprozess. Historisch referenzierte Benutzer, Exemplare, Anschriften und Zeitfenster werden nicht gelöscht, sondern soweit vorgesehen deaktiviert. Fremdschlüssel verwenden standardmäßig NO ACTION; Änderungen von Schlüsseln sind nicht vorgesehen.

Durchsetzung: Datenbankberechtigungen, FK und Trigger

### R05 Verfügbarkeit und Annahme

Verfügbar bedeutet: Angebot aktiv, Eigentümer aktiv und keine Ausleihe desselben Exemplars mit accepted/outbound/active/returning. requested-Anfragen reservieren nicht. requested_days wird bei Anfrage, proposed_days bei Vorschlag und agreed_days bei Annahme gegen die jeweils aktuelle max_loan_days geprüft. Annahme sperrt die Exemplarzeile, prüft Teilnehmer/aktive Bedingungen und setzt accepted atomar. Ein partieller UNIQUE-Index sichert parallele Annahmen zusätzlich ab. Spätere Angebotsänderungen verändern die angenommene Höchstdauer nicht.

Durchsetzung: Partieller UNIQUE-Index und Transaktion mit Zeilensperre

### R06 Dauer und Frist

Bei Annahme wird max_loan_days als max_loan_days_snapshot eingefroren. agreed_days plus alle genehmigten extra_days sind höchstens diese Grenze. Nach Erhalt gilt due_date = Datum von received_at in Europe/Berlin + agreed_days + genehmigte Zusatztage. Rückgabe ist bis Ende dieses lokalen Kalendertags fällig. Überfällig ist ein abgeleitetes Merkmal aktiver/zurückkehrender Ausleihen; kein zusätzlicher Status.

Durchsetzung: CHECK für positive Bereiche; Transaktion für Summen und Frist

### R07 Abholtermin

Bei pickup enthält eine angenommene Ausleihe pickup_slot_id, konkreten Beginn/Ende und eine vollständige Adressmomentaufnahme. Das aktive Zeitfenster gehört zur selben copy_id; das lokale Datum und die Uhrzeiten passen zum Wochentag und Wochenzeitfenster. Zeitpunkt der Vereinbarung liegt vor Beginn des Termins. Aktive Abholangebote haben mindestens ein aktives Zeitfenster.

Durchsetzung: FK plus Transaktion/Trigger einschließlich Aktivierungsprüfung

### R08 Historische Abholung

Abholtermin und Anschrift werden bei Annahme eingefroren und nicht durch spätere Änderungen an Wochenzeitfenstern oder Profilanschriften umgeschrieben. Anpassungen des Wochenplans gelten nur für neue Vereinbarungen. Bei shipping bleiben sämtliche pickup-Felder NULL.

Durchsetzung: CHECK für Übergabeart und Pflichtfelder; Schreibschutz/Trigger

### R09 Gegenvorschläge

Nur der Eigentümer schlägt bei requested eine alternative Dauer vor; höchstens ein Vorschlag ist pending. Nur der Ausleiher nimmt ihn an oder lehnt ihn ab, der Eigentümer darf ihn zurücknehmen. Ablehnung/Rücknahme lässt requested bestehen. Annahme setzt agreed_days und reserviert atomar; direkte Eigentümerannahme ist nur ohne pending-Vorschlag möglich. Bei Ende einer offenen Anfrage werden ausstehende Vorschläge withdrawn und erhalten den beendenden Teilnehmer mit Ereigniszeit als Entscheidung.

Durchsetzung: Partieller UNIQUE-Index und Transaktion/Teilnehmerprüfung

### R10 Verlängerungen

Nur der Ausleiher beantragt während active zusätzliche Tage; höchstens ein Antrag ist pending. Der Eigentümer genehmigt oder lehnt ab, der Ausleiher darf zurücknehmen. Genehmigung speichert old_due_date/new_due_date und erhöht due_date genau einmal in derselben Transaktion unter Sperre der Ausleihe. Die eingefrorene Gesamthöchstdauer bleibt verbindlich. Mit Beginn der Rückgabe werden offene Anträge withdrawn.

Durchsetzung: Partieller UNIQUE-Index und Transaktion mit Zeilensperre

### R11 Porto

Nur postalische, angenommene Ausleihen erhalten maximal einen payments-Datensatz. Dieser umfasst Hin- und Rückporto in EUR. pending→reported erfolgt durch den Ausleiher, reported→confirmed nur durch den Eigentümer; pending/reported→cancelled nur bei zulässiger Stornierung. Vor Hinversand ist confirmed erforderlich. Eine reale Zahlungsabwicklung findet nicht statt. Bestätigte Beträge und Nachweise bleiben unverändert.

Durchsetzung: UNIQUE/FK/CHECK plus Status- und Teilnehmerprüfung

### R12 Zahlung bei Stornierung

Bei einer zulässigen Stornierung wird eine noch pending/reported-Portozahlung cancelled. Ein bereits bestätigter Eingang bleibt confirmed als historischer Nachweis erhalten; Rückerstattungen werden außerhalb des Demonstrators vereinbart. Eine Stornierung ist nach Beginn einer physischen Übergabe oder einem Versand nicht mehr zulässig.

Durchsetzung: Transaktion; bestätigte Zahlung unveränderlich

### R13 Sendungen und Anschriften

Sendungen gehören nur zu shipping-Ausleihen; UNIQUE (loan_id,direction) begrenzt auf Hin- und Rückweg. Beim Hinweg ist der Eigentümer Absender und der Ausleiher Empfänger, beim Rückweg umgekehrt. Ausgewählte Anschriften gehören diesen Personen. Name, Straße/Hausnummer, PLZ, Ort und Land werden als unveränderlicher formatierter TEXT kopiert.

Durchsetzung: UNIQUE/FK plus Teilnehmer- und Snapshot-Prüfung

### R14 Versand und Rückerhalt

Hin-Sendungen werden nur bei accepted, Rücksendungen nur bei active vorbereitet; terminale Ausleihen erhalten keine neuen Sendungen. prepared→sent bestätigt der Absender, sent→received der Empfänger. Hinversand verlangt accepted und Porto confirmed und setzt outbound. Hinerhalt setzt active und Frist. Rückversand setzt returning, Rückerhalt completed. Gemeinsame Ereignisse verwenden identische Zeitpunkte: Hinerhalt=loans.received_at, Rückversand=return_started_at, Rückerhalt=completed_at. Alle Änderungen erfolgen atomar.

Durchsetzung: Transaktion und Zeilen-/Statussperren

### R15 Persönliche Übergabe

Bei pickup bestätigt der Ausleiher den Erhalt accepted→active. Eine vorzeitige Rückgabe ist erlaubt; er meldet active→returning. Erst der Eigentümer bestätigt returning→completed. Bestätigungen und Ereigniszeiten dürfen nicht rückwärts datiert werden. Ein Rückgabetermin ist keine zweite verbindliche Reservierung.

Durchsetzung: Teilnehmerprüfung und Transaktion

### R16 Zeitpunkte und Zustände

Zeitpunkte sind TIMESTAMPTZ, Wochenzeitfenster TIME und due_date DATE. Annahme liegt nicht vor Anfrage; Erhalt nicht vor Annahme; Rückgabebeginn nicht vor Erhalt; Abschluss nicht vor Rückgabebeginn. Je Status gelten die in der Zustandsmatrix genannten Pflichtwerte. Terminale Vorgänge werden nicht wieder geöffnet.

Durchsetzung: CHECK für gleiche Zeile; Transaktion für Kindereignisse

### R17 Bewertungen

Nur completed-Ausleihen und ihre beiden Teilnehmer sind bewertbar. rating liegt zwischen 1 und 5. UNIQUE (loan_id,reviewer_id) verhindert mehrfache Bewertungen; der bewertete Teilnehmer ergibt sich als Gegenüber.

Durchsetzung: CHECK/UNIQUE und Teilnehmer-/Statusprüfung

### R18 Kommunikation und Dokumente

Benachrichtigungen mit loan_id und Dokumente gehen nur an Teilnehmer. Eine referenzierte Sendung gehört zur selben Ausleihe. loan_confirmation setzt Annahme voraus, shipment_summary eine Sendung, return_confirmation den Abschluss. planned-Dokumente und test_email-Datensätze behaupten keine reale Datei oder produktive Zustellung. Private Dokumentdateien liegen außerhalb des öffentlich lesbaren Webverzeichnisses.

Durchsetzung: FK und zusammengesetzter FK oder Trigger; Berechtigung

### R19 Lokale und tabellenübergreifende Regeln

NOT NULL, CHECK und UNIQUE sichern Werte derselben Zeile beziehungsweise Schlüsselmengen. CHECK wird nicht als Prüfung fremder Tabellen verwendet. Eigentum, Rollen, Mindestautorenzahl, Zeitfenster, Fristsummen und Statusfolgen erfordern kontrollierte SQL-Funktionen/Trigger und Transaktionen; direkte unkontrollierte Schreibzugriffe des Webkontos sind gesperrt.

Durchsetzung: Dokumentierte Durchsetzung in Phase 2

### R20 Wiederholung und Erhalt der Historie

book_copies.book_id bleibt ab Erfassung unverändert. loans.copy_id, borrower_id, handover_mode und requested_days sind ab Anfrage fest; agreed_days und max_loan_days_snapshot ab Annahme. Bestätigte Ereignisse, genehmigte Friständerungen und Adressmomentaufnahmen werden nicht überschrieben. Verlängerungen ändern nur due_date über genehmigte Anträge. Wiederholte Bestätigungen erzeugen keine erneute Friständerung oder zweite Sendung. Kinddatensätze werden unter Sperre der Ausleihe bearbeitet.

Durchsetzung: Idempotente Datenbankfunktionen, Zeilensperren und UNIQUE

## Zustandsübergänge

- `requested` → `accepted`: Eigentümer nimmt Originalanfrage an oder Ausleiher akzeptiert Gegenvorschlag. accepted_at, agreed_days, max_loan_days_snapshot; bei pickup Termin und Anschrift. R05–R09
- `requested` → `rejected`: Eigentümer lehnt ab. rejected_at; offene Vorschläge schließen. R09
- `requested` → `cancelled`: Ausleiher zieht offene Anfrage zurück. cancelled_at und cancelled_by_user_id. R09
- `accepted` → `cancelled`: Einer der Teilnehmer storniert vor jeder physischen Übergabe. cancelled_at/actor; Sperre frei; Porto gemäß R12. R12
- `accepted` → `outbound`: Eigentümer bestätigt Hinversand. shipping; Hin-Sendung sent; Porto confirmed. R11/R14
- `accepted` → `active`: Ausleiher bestätigt persönliche Abholung. pickup; received_at und due_date. R06/R15
- `outbound` → `active`: Ausleiher bestätigt Postempfang. Hin-Sendung received; received_at und due_date. R06/R14
- `active` → `returning`: Ausleiher meldet persönliche Rückgabe oder Rückversand. return_started_at; bei shipping Rücksendung sent. R10/R14/R15
- `returning` → `completed`: Eigentümer bestätigt Rückerhalt. completed_at; bei shipping Rücksendung received; Sperre frei. R14/R15

## Drei Tabellen je Abfrage

### Exemplar mit Ausgabe und Eigentümer

```sql
SELECT c.copy_id, b.title, u.first_name, u.last_name
FROM book_copies AS c
JOIN books AS b ON b.book_id = c.book_id
JOIN users AS u ON u.user_id = c.owner_id;
```

### Ausleihe mit Exemplar und ausleihender Person

```sql
SELECT l.loan_id, c.copy_id, u.first_name, l.status
FROM loans AS l
JOIN book_copies AS c ON c.copy_id = l.copy_id
JOIN users AS u ON u.user_id = l.borrower_id;
```

### Portozahlung mit Ausleihe und bestätigender Person

```sql
SELECT p.payment_id, l.loan_id, u.first_name, p.confirmed_at
FROM payments AS p
JOIN loans AS l ON l.loan_id = p.loan_id
LEFT JOIN users AS u ON u.user_id = p.confirmed_by_user_id;
```
