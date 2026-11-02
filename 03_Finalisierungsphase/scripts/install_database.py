"""Atomic, hash-verified migrations into this project's own local cluster."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sys

from runtime import DATA, DATABASE, OWNER_ROLE, ROOT, RUNTIME, load_owner, validate_cluster, write_json

sys.path.insert(0, str(RUNTIME / "python"))
try:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
except ImportError as error:
    raise SystemExit("Zuerst install_dependencies.ps1 mit diesem Python ausfuehren.") from error

MIGRATIONS = [ROOT / "database" / "phase2" / name for name in (
    "01_schema.sql", "02_integrity.sql", "03_workflows.sql", "04_seed.sql", "06_access.sql")]
MIGRATIONS.extend(ROOT / "database" / name for name in (
    "07_application.sql", "08_application_editing.sql", "09_deferred_validation.sql"))


def migration_body(source: str) -> str:
    # Preserve the delivered SQL; only their outer transaction is handled by
    # psycopg so schema changes and their hash record commit together.
    source, first = re.subn(r"(?m)^BEGIN;\s*$", "", source, count=1)
    source, last = re.subn(r"(?m)^COMMIT;\s*\Z", "", source, count=1)
    if (first, last) != (1, 1):
        raise RuntimeError("Migration hat keine erwartete aeussere Transaktion.")
    return source


def install() -> None:
    owner = load_owner()
    validate_cluster(owner)
    common = {"host": owner["host"], "port": owner["port"], "user": OWNER_ROLE,
              "password": owner["owner_password"], "connect_timeout": 10}
    with psycopg.connect(dbname="postgres", autocommit=True, **common) as connection:
        actual = Path(connection.execute("SHOW data_directory").fetchone()[0]).resolve()
        if actual != DATA.resolve():
            raise RuntimeError("Der Port gehoert nicht zum eigenen Datenordner; Installation abgebrochen.")
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='bookbridge_web'").fetchone():
            connection.execute(sql.SQL("CREATE ROLE bookbridge_web LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}")
                               .format(sql.Literal(owner["service_password"])))
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)).fetchone():
            connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'")
                               .format(sql.Identifier(DATABASE), sql.Identifier(OWNER_ROLE)))
    applied, unchanged = [], []
    with psycopg.connect(dbname=DATABASE, autocommit=True, **common) as connection:
        connection.execute("SELECT pg_advisory_lock(8767,55434)")
        try:
            with connection.transaction():
                connection.execute("CREATE SCHEMA IF NOT EXISTS bookbridge_app")
                connection.execute("REVOKE ALL ON SCHEMA bookbridge_app FROM PUBLIC")
                connection.execute("""CREATE TABLE IF NOT EXISTS bookbridge_app.migrations (
                    version TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL CHECK (source_hash ~ '^[a-f0-9]{64}$'),
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            for path in MIGRATIONS:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                version = path.relative_to(ROOT / "database").as_posix()
                previous = connection.execute("SELECT source_hash FROM bookbridge_app.migrations WHERE version=%s", (version,)).fetchone()
                if previous:
                    if previous[0] != digest:
                        raise RuntimeError(f"Bereits installierte Quelldatei wurde veraendert: {version}. Bestehende Daten bleiben erhalten; neue Migration statt Neusaat erforderlich.")
                    unchanged.append(version)
                    continue
                with connection.transaction():
                    connection.execute(migration_body(raw.decode("utf-8-sig")), prepare=False)
                    connection.execute("INSERT INTO bookbridge_app.migrations(version,source_hash) VALUES(%s,%s)", (version, digest))
                applied.append(version)
                print(f"Migration installiert: {version}")
            connection.execute("ALTER ROLE bookbridge_web IN DATABASE bookbridge_phase3 SET search_path=bookbridge,bookbridge_app,public")
            connection.execute("ALTER ROLE bookbridge_web IN DATABASE bookbridge_phase3 SET timezone='Europe/Berlin'")
            connection.execute("REVOKE ALL ON DATABASE bookbridge_phase3 FROM PUBLIC")
            connection.execute("GRANT CONNECT ON DATABASE bookbridge_phase3 TO bookbridge_web")
        finally:
            connection.execute("SELECT pg_advisory_unlock(8767,55434)")
    dsn = make_conninfo(host=owner["host"], port=owner["port"], dbname=DATABASE,
                        user="bookbridge_web", password=owner["service_password"],
                        connect_timeout=10, application_name="bookbridge_phase3")
    with psycopg.connect(dsn) as connection:
        role = connection.execute("SELECT current_user,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
        if role != ("bookbridge_web", False, False, False):
            raise RuntimeError("Die Web-Datenbankrolle besitzt unerwartete Verwaltungsrechte.")
        counts = connection.execute("SELECT (SELECT count(*) FROM bookbridge.books),(SELECT count(*) FROM bookbridge.book_copies)").fetchone()
    config = {"database_dsn": dsn, "host": "127.0.0.1", "port": 8767,
              "project_id": "bookbridge-phase3"}
    write_json(RUNTIME / "config.json", config)
    write_json(RUNTIME / "installation.json", {
        "project_id": "bookbridge-phase3", "database": DATABASE,
        "database_port": owner["port"], "migrations_applied": applied,
        "migrations_unchanged": unchanged, "book_count": counts[0], "copy_count": counts[1],
        "runtime_python": sys.executable, "service_superuser": False})
    print(f"Installation bereit: {len(applied)} neue, {len(unchanged)} unveraenderte Migrationen; {counts[0]} Ausgaben / {counts[1]} Angebote.")


if __name__ == "__main__":
    try:
        install()
    except psycopg.Error as error:
        # SQL errors may include details of rows. Do not emit credentials/rows.
        raise SystemExit(f"Datenbankinstallation fehlgeschlagen (SQLSTATE {error.sqlstate or 'Verbindung'}). Bestehende Daten werden nicht geloescht.")
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
