"""Project-local PostgreSQL lifecycle. Never changes a system service or Phase 2.

Credentials are generated into owner.json/config.json, never command arguments.
The owner file and cluster must belong to this copy of the project.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
DATA = RUNTIME / "pgdata"
OWNER_FILE = RUNTIME / "owner.json"
OWNER_ROLE = "bookbridge_phase3_owner"
DATABASE = "bookbridge_phase3"
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("timeout", 120)
    return subprocess.run(command, creationflags=HIDDEN, check=True, **kwargs)


def private_runtime() -> None:
    RUNTIME.mkdir(exist_ok=True)
    if RUNTIME.is_symlink() or RUNTIME.resolve().parent != ROOT:
        raise RuntimeError(".runtime muss ein direkter Projektordner sein.")
    if os.name == "nt":
        # User SID avoids localized account names; grant before removing
        # inherited rights. Keep SYSTEM access for Windows tools/backups.
        sid = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                   "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
                  capture_output=True, text=True).stdout.strip()
        run(["icacls.exe", str(RUNTIME), "/grant:r", f"*{sid}:(OI)(CI)F",
             "*S-1-5-18:(OI)(CI)F", "/inheritance:r"], capture_output=True, text=True)
    else:
        RUNTIME.chmod(0o700)


def write_json(path: Path, value: dict) -> None:
    # Atomic replacement also prevents an interrupted write corrupting secrets.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=RUNTIME,
                                     prefix=".state-", delete=False) as handle:
        temp = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        if os.name != "nt":
            temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_owner() -> dict:
    if not OWNER_FILE.is_file():
        raise RuntimeError("Zuerst scripts/setup.ps1 ausfuehren.")
    value = json.loads(OWNER_FILE.read_text(encoding="utf-8-sig"))
    if value.get("project_id") != "bookbridge-phase3" or value.get("database") != DATABASE:
        raise RuntimeError("Unbekannte Laufzeitkonfiguration. Keine Aenderung vorgenommen.")
    if value.get("host") != "127.0.0.1" or value.get("owner_role") != OWNER_ROLE:
        raise RuntimeError("Nur der eigene lokale Phase-3-Cluster ist erlaubt.")
    return value


def pg_binary(owner: dict, name: str) -> str:
    target = Path(owner["postgres_bin"]) / (name + (".exe" if os.name == "nt" else ""))
    if not target.is_file():
        raise RuntimeError(f"PostgreSQL-Werkzeug fehlt: {target}")
    return str(target)


def validate_cluster(owner: dict) -> None:
    if DATA.is_symlink() or DATA.resolve().parent != RUNTIME.resolve():
        raise RuntimeError("Der Datenpfad liegt nicht im eigenen .runtime-Ordner.")
    marker = DATA / "bookbridge_cluster_id"
    if not marker.is_file() or marker.read_text(encoding="ascii").strip() != owner["cluster_id"]:
        raise RuntimeError("Der Datenordner ist nicht als eigener Phase-3-Cluster registriert.")
    pid_file = DATA / "postmaster.pid"
    if pid_file.is_file():
        lines = pid_file.read_text(encoding="utf-8-sig").splitlines()
        # A raw copy of a running cluster carries its original PID. pg_ctl
        # can otherwise mistake that still-live source process for this copy.
        if len(lines) < 2 or Path(lines[1]).resolve() != DATA.resolve():
            raise RuntimeError("Die Datenbank-PID-Datei verweist auf einen anderen Datenordner. "
                               "Keine Prozesssteuerung; zuerst die urspruengliche Laufzeit sicher pruefen.")


def initialize(postgres_bin: str | None, port: int | None) -> dict:
    private_runtime()
    if OWNER_FILE.exists():
        owner = load_owner()
        if port is not None and owner["port"] != port:
            raise RuntimeError("Dieser Cluster verwendet einen anderen Port; bestehende Konfiguration bleibt erhalten.")
        if postgres_bin is not None and Path(postgres_bin).resolve() != Path(owner["postgres_bin"]).resolve():
            raise RuntimeError("PostgreSQL-Pfad stimmt nicht mit der gespeicherten Installation ueberein.")
    else:
        if DATA.exists() and any(DATA.iterdir()):
            raise RuntimeError("Vorhandener nicht registrierter Datenordner; keine Uebernahme oder Loeschung.")
        if postgres_bin is None:
            raise RuntimeError("Fuer die Ersteinrichtung -PostgresBin angeben.")
        owner = {"project_id": "bookbridge-phase3", "cluster_id": uuid.uuid4().hex,
                 "postgres_bin": str(Path(postgres_bin).resolve()), "host": "127.0.0.1",
                 "port": port or 55434, "database": DATABASE, "owner_role": OWNER_ROLE,
                 "owner_password": secrets.token_urlsafe(36),
                 "service_password": secrets.token_urlsafe(36), "python_executable": sys.executable}
        pg_binary(owner, "initdb")
        pg_binary(owner, "pg_ctl")
        write_json(OWNER_FILE, owner)
    if not (DATA / "PG_VERSION").exists():
        if DATA.exists() and any(DATA.iterdir()):
            raise RuntimeError("Unvollstaendiger Datenordner; bitte zuerst pruefen, keine automatische Loeschung.")
        with tempfile.NamedTemporaryFile("w", encoding="ascii", dir=RUNTIME,
                                         prefix=".initdb-password-", delete=False) as handle:
            password_file = Path(handle.name)
            handle.write(owner["owner_password"] + "\n")
        try:
            if os.name != "nt":
                password_file.chmod(0o600)
            run([pg_binary(owner, "initdb"), "-D", str(DATA), "-U", OWNER_ROLE,
                 "-E", "UTF8", "--locale=C", "--auth-local=scram-sha-256",
                 "--auth-host=scram-sha-256", f"--pwfile={password_file}"],
                capture_output=True, text=True)
            (DATA / "bookbridge_cluster_id").write_text(owner["cluster_id"] + "\n", encoding="ascii")
        finally:
            password_file.unlink(missing_ok=True)
    validate_cluster(owner)
    return owner


def start_database(owner: dict) -> None:
    validate_cluster(owner)
    status = subprocess.run([pg_binary(owner, "pg_ctl"), "-D", str(DATA), "status"],
                            creationflags=HIDDEN, capture_output=True, text=True)
    if status.returncode == 3:
        # On Windows detached descendants can inherit captured pipe handles.
        # File handles let pg_ctl finish without waiting for the server to stop.
        with (RUNTIME / "pg-control.log").open("ab") as diagnostics:
            run([pg_binary(owner, "pg_ctl"), "-D", str(DATA), "-l", str(RUNTIME / "postgres.log"),
                 "-o", f"-p {owner['port']} -h 127.0.0.1", "-w", "-t", "30", "start"],
                stdout=diagnostics, stderr=subprocess.STDOUT)
    elif status.returncode != 0:
        raise RuntimeError("Der Zustand des eigenen PostgreSQL-Clusters konnte nicht sicher ermittelt werden.")
    print(f"Phase-3-Datenbank bereit auf 127.0.0.1:{owner['port']}.")


def stop_database(owner: dict) -> None:
    validate_cluster(owner)
    status = subprocess.run([pg_binary(owner, "pg_ctl"), "-D", str(DATA), "status"],
                            creationflags=HIDDEN, capture_output=True, text=True)
    if status.returncode == 0:
        run([pg_binary(owner, "pg_ctl"), "-D", str(DATA), "-m", "fast", "-w", "-t", "30", "stop"],
            capture_output=True, text=True)
        print("Eigener Phase-3-Datenbankprozess beendet. Daten bleiben erhalten.")
    elif status.returncode == 3:
        print("Eigene Phase-3-Datenbank ist bereits beendet.")
    else:
        raise RuntimeError("Unklarer Datenbankzustand; kein Prozess wurde beendet.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "start", "stop"))
    parser.add_argument("--postgres-bin")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("Port muss zwischen 1024 und 65535 liegen.")
    if args.action == "init":
        start_database(initialize(args.postgres_bin, args.port))
    elif args.action == "start":
        owner = load_owner()
        if args.port is not None and owner["port"] != args.port:
            raise RuntimeError("Port weicht von der gespeicherten Konfiguration ab.")
        start_database(owner)
    else:
        stop_database(load_owner())


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        # Subprocess commands contain only paths/port, but do not emit captured
        # PostgreSQL diagnostics that could include SQL or runtime contents.
        raise SystemExit(f"PostgreSQL-Werkzeug fehlgeschlagen (Code {error.returncode}); .runtime/postgres.log pruefen.")
    except subprocess.TimeoutExpired:
        raise SystemExit("PostgreSQL-Werkzeug antwortet nicht; .runtime/postgres.log und pg-control.log pruefen. Vorhandene Daten bleiben erhalten.")
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
