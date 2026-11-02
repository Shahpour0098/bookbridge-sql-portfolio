"""Promote one existing active account in this project's own Phase 3 database.

Run locally after registering an account in the browser. This operator command
does not create an account, set a password, or expose administrative SQL in HTTP.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from runtime import DATA, DATABASE, OWNER_ROLE, RUNTIME, load_owner, validate_cluster

sys.path.insert(0, str(RUNTIME / "python"))
try:
    import psycopg
except ImportError as error:
    raise SystemExit("Zuerst scripts/install_dependencies.ps1 ausfuehren.") from error


def promote(email: str) -> int:
    email = email.strip().lower()
    if len(email) > 254 or "@" not in email or any(character.isspace() for character in email):
        raise ValueError("Eine gueltige registrierte E-Mail-Adresse angeben.")
    owner = load_owner()
    validate_cluster(owner)
    with psycopg.connect(host=owner["host"], port=owner["port"], dbname=DATABASE,
                         user=OWNER_ROLE, password=owner["owner_password"],
                         connect_timeout=10, application_name="bookbridge_phase3_admin") as connection:
        actual = Path(connection.execute("SHOW data_directory").fetchone()[0]).resolve()
        if actual != DATA.resolve():
            raise RuntimeError("Der Port gehoert nicht zum eigenen Datenordner; keine Aenderung.")
        row = connection.execute(
            "UPDATE bookbridge.users SET role='admin' "
            "WHERE lower(email)=%s AND is_active RETURNING user_id", (email,)).fetchone()
        if row is None:
            raise RuntimeError("Kein aktives registriertes Konto gefunden; keine Aenderung.")
        return row[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="E-Mail des selbst registrierten aktiven Kontos")
    args = parser.parse_args()
    try:
        user_id = promote(args.email)
        print(f"Mitglied {user_id} hat jetzt die Administratorrolle. Browseransicht neu laden.")
    except psycopg.Error as error:
        raise SystemExit(f"Administratorrolle konnte nicht gesetzt werden (SQLSTATE {error.sqlstate or 'Verbindung'}).")
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
