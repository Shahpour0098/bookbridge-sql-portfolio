# Optionales PostgreSQL-Backup

`bookbridge_phase2.dump` ist ein geprüftes PostgreSQL-Custom-Archiv der lokalen
Projektdatenbank. Die SQL-Dateien unter `sql/` bleiben die bevorzugte, nachvollziehbare
Installationsquelle. `evidence/backup_verification.json` enthält SHA-256, Größe,
DBMS-Version und den Nachweis identischer Inhalte aller 18 Tabellen nach Restore.

Für eine Wiederherstellung eine **neue, leere** Datenbank anlegen. Bestehende
Projektdatenbanken nicht überschreiben. Der folgende Ablauf verwendet die
PostgreSQL-17-Werkzeuge im PATH; Host, Port und Benutzer bei Bedarf anpassen:

```powershell
createdb -h 127.0.0.1 -p 55432 -U bookbridge_admin --template=template0 bookbridge_restored
pg_restore -h 127.0.0.1 -p 55432 -U bookbridge_admin --no-owner --no-acl --exit-on-error --dbname=bookbridge_restored database/bookbridge_phase2.dump
psql -h 127.0.0.1 -p 55432 -U bookbridge_admin -d bookbridge_restored -v ON_ERROR_STOP=1 -c "DROP VIEW bookbridge.public_catalog;"
psql -h 127.0.0.1 -p 55432 -U bookbridge_admin -d bookbridge_restored -v ON_ERROR_STOP=1 -f sql/06_access.sql
```

`--no-owner --no-acl` vermeidet eine Abhängigkeit von ursprünglichen Besitzer-
oder Rollenrechten. `06_access.sql` erstellt fehlende Leser-/Backend-Rollen und
richtet deren Rechte ein; der ausführende Datenbankbenutzer benötigt dafür die
entsprechenden Verwaltungsrechte. Zuvor wird ausschließlich die gerade
wiederhergestellte, abgeleitete öffentliche Katalogsicht entfernt, da das
unveränderte Zugriffsskript sie einschließlich ihrer Rechte neu erstellt.
Gespeicherte Tabelleninhalte werden dadurch nicht entfernt.

`tests/verify_backup.py` reproduziert Backup und Restore samt Inhaltsvergleich
in einer automatisch benannten neuen Datenbank. Die geprüfte Restore-Datenbank
bleibt zur Kontrolle erhalten. Bereits vorhandene Backup-Dateien werden vom
Prüfprogramm nicht überschrieben. Identity-Sequenzstände werden beim Vergleich
nicht als fachliche Daten behandelt; Test-Rollbacks können technische ID-Lücken
verursachen.
