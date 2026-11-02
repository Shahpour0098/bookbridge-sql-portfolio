-- BookBridge: dokumentierter SQL-Einstiegspunkt fuer eine getrennte Referenzpruefung.
-- PostgreSQL 17 / psql. Die Originaldateien bleiben unveraendert erhalten.
--
-- EMPFOHLENE ANWENDUNGSINSTALLATION: scripts/setup.ps1.
-- Dieses Referenzskript erzeugt KEINE Laufzeitkonfiguration, Login-Passwoerter
-- oder Migrationseintraege und ersetzt deshalb nicht den Anwendungsinstaller.
-- Es dient der nachvollziehbaren Betrachtung des vollstaendigen Schemas,
-- der synthetischen Ausgangsdaten und der dokumentierten Ergebnisabfragen.
--
-- Voraussetzungen fuer diese optionale Referenzpruefung:
-- 1. Einen eigenen, kontrollierten PostgreSQL-Pruefcluster verwenden.
-- 2. Eine neue leere Datenbank bookbridge_reference_<eigener_suffix> anlegen.
-- 3. Dort einen Schemaeigner mit CREATEROLE oder Superuser-Rechten nutzen.
-- 4. Die vorhandenen Rollen bookbridge_reader und bookbridge_backend sind
--    NOLOGIN; bookbridge_web ist NOSUPERUSER NOCREATEDB NOCREATEROLE
--    NOREPLICATION und bereits Mitglied von bookbridge_backend. Der regulare
--    Installer stellt dies bereit. In einem neuen separaten Cluster diese
--    Rollen vorab bereitstellen; ein Web-Login ist fuer die Referenz unnoetig.
-- 5. psql explizit mit -v bookbridge_reference_build=1 -v ON_ERROR_STOP=1
--    und -f BookBridge_Gesamt.sql starten. -h/-p/-U/-d passend setzen.
--
-- Das Skript verweigert vorhandene BookBridge-Schemata und privilegierte
-- Web-Rollen. Bestehende Rollen/Mitgliedschaften werden vorausgesetzt;
-- die folgenden GRANTs bestaetigen sie lediglich fuer die neue Datenbank.
-- Es loescht keine Daten und fuehrt kein DROP oder TRUNCATE aus.
-- Bei einem Fehler abbrechen; die Einzeldateien besitzen eigene Transaktionen.
-- Ein bereits teilweise aufgebautes Schema nicht durch erneute Ausfuehrung
-- ueberschreiben. Fuer eine Wiederholung eine neue leere Pruefdatenbank nutzen.
\set ON_ERROR_STOP on
\if :{?bookbridge_reference_build}
\else
  DO $reference_opt_in$ BEGIN
    RAISE EXCEPTION 'Abbruch: nur mit -v bookbridge_reference_build=1 fuer neue Referenzdatenbank.';
  END $reference_opt_in$;
\endif
SELECT :'bookbridge_reference_build' = '1' AS reference_build_allowed \gset
\if :reference_build_allowed
\else
  DO $reference_opt_in$ BEGIN
    RAISE EXCEPTION 'Abbruch: bookbridge_reference_build muss 1 sein.';
  END $reference_opt_in$;
\endif

DO $bookbridge_reference_guard$
BEGIN
  IF NOT starts_with(current_database(), 'bookbridge_reference_') THEN
    RAISE EXCEPTION 'Nur neue Datenbank bookbridge_reference_<suffix> zugelassen.';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN ('bookbridge','bookbridge_app')) THEN
    RAISE EXCEPTION 'BookBridge-Schema bereits vorhanden; vorhandene Daten werden nicht veraendert.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolcreaterole)) THEN
    RAISE EXCEPTION 'Die Referenzinstallation benoetigt eine passende Schemaeigner-Rolle mit CREATEROLE.';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname='bookbridge_web'
      AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication
  ) THEN
    RAISE EXCEPTION 'Vorhandene eingeschraenkte Rolle bookbridge_web erforderlich.';
  END IF;
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('bookbridge_reader','bookbridge_backend')
        AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
        AND NOT rolcreaterole AND NOT rolreplication) <> 2 THEN
    RAISE EXCEPTION 'Vorhandene eingeschraenkte NOLOGIN-Rollen bookbridge_reader und bookbridge_backend erforderlich.';
  END IF;
  IF NOT pg_has_role('bookbridge_web','bookbridge_backend','MEMBER') THEN
    RAISE EXCEPTION 'Die Backend-Mitgliedschaft des Webkontos muss bereits vorhanden sein.';
  END IF;
END
$bookbridge_reference_guard$;

-- Die acht versionierten Quelldateien in der Reihenfolge des Installers:
-- 01: 18 Fachtabellen, 142 Spalten, 32 Fremdschluessel, Indizes und Kommentare.
\ir phase2/01_schema.sql
-- 02: Tabellenuebergreifende Konsistenz, historische Momentaufnahmen, Trigger.
\ir phase2/02_integrity.sql
-- 03: 20 kontrollierte Geschaeftsfunktionen fuer Anfrage bis Bewertung.
\ir phase2/03_workflows.sql
-- 04: 1.431 synthetische Zeilen, mindestens zwoelf je fachlicher Tabelle.
\ir phase2/04_seed.sql
-- 06: Oeffentlicher Katalog sowie eingeschraenkte Reader-/Backend-Rollen.
\ir phase2/06_access.sql
-- 07: Zwei technische Tabellen fuer Sitzungen/Migrationserfassung, Webrechte.
\ir 07_application.sql
-- 08: Berechtigungen fuer Profil- und Angebotsbearbeitung.
\ir 08_application_editing.sql
-- 09: Berechtigter Ausfuehrungskontext des aufgeschobenen Ausleih-Triggers.
\ir 09_deferred_validation.sql

-- 05 enthaelt ausschliesslich acht Ergebnisabfragen und ist keine Migration.
\ir phase2/05_queries.sql

-- Nachvollziehbare Metadaten der gerade aufgebauten Referenzdatenbank.
SELECT table_schema, count(*) AS base_tables
FROM information_schema.tables
WHERE table_schema IN ('bookbridge','bookbridge_app') AND table_type='BASE TABLE'
GROUP BY table_schema ORDER BY table_schema;
SELECT current_database() AS database_name,
       pg_database_size(current_database()) AS bytes,
       pg_size_pretty(pg_database_size(current_database())) AS volume;
-- Die Referenzfassung laesst bookbridge_app.migrations bewusst leer.
-- Die Anwendung dokumentiert die acht Quelldatei-Hashes erst bei setup.ps1.
