"""Install the published SQL into a new empty database and execute the suite.

The verified database is retained for inspection. No existing database is
overwritten or removed. A CREATEDB PostgreSQL owner is required.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

# Keep Windows console and subprocess evidence consistently UTF-8.
for output_stream in (sys.stdout, sys.stderr):
    if hasattr(output_stream, 'reconfigure'):
        output_stream.reconfigure(encoding='utf-8', errors='backslashreplace')
import time
import uuid

import run_tests as integration
import psycopg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", "host=127.0.0.1 port=55432 dbname=bookbridge_phase2 user=bookbridge_admin"))
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    output = args.out or args.project / "evidence"
    output.mkdir(parents=True, exist_ok=True)
    database = "bookbridge_phase2_verify_" + uuid.uuid4().hex[:12]
    maintenance = psycopg.conninfo.make_conninfo(args.dsn, dbname="postgres")
    verified_dsn = psycopg.conninfo.make_conninfo(args.dsn, dbname=database)
    record = {
        "project": "BookBridge",
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "empty_template": "template0",
        "database": database,
        "retained_for_inspection": True,
        "source_directory": str(args.project.resolve()),
        "runtime": {"python": sys.version, "platform": platform.platform(), "psycopg": psycopg.__version__},
        "scripts": [],
    }
    log = []
    try:
        with psycopg.connect(maintenance, autocommit=True) as admin:
            admin.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(database)))
        with integration.connect(verified_dsn) as c:
            for name in ["01_schema.sql", "02_integrity.sql", "03_workflows.sql", "04_seed.sql", "06_access.sql"]:
                path = args.project / "sql" / name
                raw = path.read_bytes()
                started = time.perf_counter()
                cur = c.execute(raw.decode("utf-8-sig"))
                statuses = []
                while True:
                    statuses.append(cur.statusmessage)
                    if not cur.nextset():
                        break
                script = {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "status": "executed", "duration_ms": round((time.perf_counter()-started)*1000,2), "statements": len(statuses)}
                record["scripts"].append(script)
                log.append(f"{name}: SUCCESS, {len(statuses)} statements, SHA256 {script['sha256']}")
                print(log[-1], flush=True)
            # Query-only file is executed separately and every result is counted.
            query_path = args.project / "sql" / "05_queries.sql"
            raw = query_path.read_bytes()
            cur = c.execute(raw.decode("utf-8-sig"))
            results = []
            while True:
                if cur.description:
                    results.append({"columns": [col.name for col in cur.description], "rows": len(cur.fetchall())})
                if not cur.nextset():
                    break
            record["scripts"].append({"file": "05_queries.sql", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "status": "executed", "resultsets": results})
            record["server_version"] = integration.scalar(c, "SELECT version()")
            record["database_user"] = integration.scalar(c, "SELECT current_user")
            record["timezone"] = integration.scalar(c, "SHOW TIME ZONE")
            record["base_tables"] = integration.scalar(c, "SELECT count(*) FROM information_schema.tables WHERE table_schema='bookbridge' AND table_type='BASE TABLE'")
            record["base_table_columns"] = integration.scalar(c, "SELECT count(*) FROM information_schema.columns c JOIN information_schema.tables t USING(table_catalog,table_schema,table_name) WHERE c.table_schema='bookbridge' AND t.table_type='BASE TABLE'")
            record["foreign_keys"] = integration.scalar(c, "SELECT count(*) FROM pg_constraint pc JOIN pg_namespace n ON n.oid=pc.connamespace WHERE n.nspname='bookbridge' AND pc.contype='f'")
            record["indexes"] = integration.scalar(c, "SELECT count(*) FROM pg_indexes WHERE schemaname='bookbridge'")
            record["triggers"] = integration.scalar(c, "SELECT count(*) FROM information_schema.triggers WHERE trigger_schema='bookbridge'")
            record["seed_rows"] = {table: integration.scalar(c, f"SELECT count(*) FROM bookbridge.{table}") for table in integration.TABLES}
            record["total_seed_rows"] = sum(record["seed_rows"].values())
            integration.eq(record["base_tables"], 18)
            integration.eq(record["base_table_columns"], 142)
            integration.eq(record["foreign_keys"], 32)
            integration.eq(len(results), 8, "All query-only resultsets executed")
        completed = subprocess.run([sys.executable, str(args.project / "tests" / "run_tests.py"), "--dsn", verified_dsn, "--out", str(output)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        (output / "integration-test-console.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        print(completed.stdout, end="", flush=True)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="", flush=True)
        record["integration_exit_code"] = completed.returncode
        report_path = output / "test-report.json"
        if report_path.exists():
            record["integration_summary"] = json.loads(report_path.read_text(encoding="utf-8"))["summary"]
        if completed.returncode:
            raise RuntimeError("Integration suite failed; see test-report.json")
        record["status"] = "passed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (output / "schema_verification.json").write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        (output / "clean-install-console.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("Verified database retained: " + database, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
