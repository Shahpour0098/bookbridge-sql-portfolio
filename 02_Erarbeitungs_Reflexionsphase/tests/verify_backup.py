"""Create a custom PostgreSQL backup and verify a restore into a new database.

Existing databases are never overwritten or removed. The restore database is
retained for inspection. Original SQL scripts remain the preferred installation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")

import run_tests as integration
import psycopg


def command(args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} exited {result.returncode}: {result.stderr}")
    return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}


def describe(c):
    return {
        "tables": integration.scalar(c, "SELECT count(*) FROM information_schema.tables WHERE table_schema='bookbridge' AND table_type='BASE TABLE'"),
        "columns": integration.scalar(c, "SELECT count(*) FROM information_schema.columns c JOIN information_schema.tables t USING(table_catalog,table_schema,table_name) WHERE c.table_schema='bookbridge' AND t.table_type='BASE TABLE'"),
        "foreign_keys": integration.scalar(c, "SELECT count(*) FROM pg_constraint pc JOIN pg_namespace n ON n.oid=pc.connamespace WHERE n.nspname='bookbridge' AND pc.contype='f'"),
        "rows": {table: integration.scalar(c, f"SELECT count(*) FROM bookbridge.{table}") for table in integration.TABLES},
        "fingerprints": integration.fingerprints(c),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default="host=127.0.0.1 port=55432 dbname=bookbridge_phase2 user=bookbridge_admin")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pg-bin", type=Path, default=Path("D:/PostgreSQL/17/bin"))
    args = parser.parse_args()
    destination = args.project / "database"
    destination.mkdir(parents=True, exist_ok=True)
    evidence = args.project / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    backup = destination / "bookbridge_phase2.dump"
    if backup.exists():
        raise SystemExit("Backup already exists; choose a new output project folder or archive the existing backup manually.")
    restore_db = "bookbridge_phase2_restore_" + uuid.uuid4().hex[:12]
    restore_dsn = psycopg.conninfo.make_conninfo(args.dsn, dbname=restore_db)
    maintenance = psycopg.conninfo.make_conninfo(args.dsn, dbname="postgres")
    pg_dump = args.pg_bin / "pg_dump.exe"
    pg_restore = args.pg_bin / "pg_restore.exe"
    record = {
        "project": "BookBridge",
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "format": "PostgreSQL custom archive",
        "backup": str(backup.resolve()),
        "restored_database": restore_db,
        "restored_database_retained": True,
        "source_database_modified": False,
        "existing_databases_overwritten": False,
        "restore_options": ["--no-owner", "--no-acl", "--exit-on-error"],
        "sequence_comparison": "Identity sequence positions are deliberately excluded; rollback test fixtures may consume sequence values.",
    }
    try:
        with integration.connect(args.dsn) as c:
            record["source_database"] = integration.scalar(c, "SELECT current_database()")
            record["server_version"] = integration.scalar(c, "SELECT version()")
            record["source"] = describe(c)
        record["pg_dump_version"] = command([pg_dump, "--version"])["stdout"].strip()
        record["pg_restore_version"] = command([pg_restore, "--version"])["stdout"].strip()
        record["dump_execution"] = command([pg_dump, "--format=custom", "--file", backup, "--dbname", args.dsn])
        raw = backup.read_bytes()
        record["dump_bytes"] = len(raw)
        record["dump_sha256"] = hashlib.sha256(raw).hexdigest()
        with psycopg.connect(maintenance, autocommit=True) as admin:
            admin.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(restore_db)))
        record["restore_execution"] = command([pg_restore, "--no-owner", "--no-acl", "--exit-on-error", "--dbname", restore_dsn, backup])
        # 06_access.sql creates the public catalog view. Recreate this derived
        # view only in our new restore database so the unchanged script also
        # restores permissions and creates roles when they do not yet exist.
        with integration.connect(restore_dsn) as c:
            c.execute("DROP VIEW bookbridge.public_catalog")
            security = (args.project / "sql" / "06_access.sql").read_bytes()
            cur = c.execute(security.decode("utf-8-sig"))
            while cur.nextset():
                pass
            record["access_script_sha256"] = hashlib.sha256(security).hexdigest()
            record["restored"] = describe(c)
            record["public_catalog_rows"] = integration.scalar(c, "SELECT count(*) FROM bookbridge.public_catalog")
        with integration.connect(args.dsn) as c:
            source_after = describe(c)
        integration.eq(source_after, record["source"], "Source contents stayed unchanged during backup")
        integration.eq(record["restored"], record["source"], "All 18 tables restored exactly, including every row fingerprint")
        integration.eq(record["restored"]["tables"], 18)
        integration.eq(record["restored"]["columns"], 142)
        integration.eq(record["restored"]["foreign_keys"], 32)
        integration.eq(sum(record["restored"]["rows"].values()), 1431)
        record["total_rows"] = sum(record["restored"]["rows"].values())
        record["all_table_fingerprints_match"] = True
        record["status"] = "passed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (evidence / "backup_verification.json").write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"Backup verified: {record['dump_bytes']} bytes; SHA256 {record['dump_sha256']}")
    print(f"Restore retained: {restore_db}; 18 tables, 142 columns, 32 foreign keys, 1431 matching rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
