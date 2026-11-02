"""Serve the real application on 8768 using a disposable browser-QA database.

Create .runtime/browser-qa.stop to end this invocation and remove its own DB.
Never uses or changes the main application's user records. Runtime files and
generated private documents remain inside the protected .runtime directory.
"""
from pathlib import Path
import json
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.runtime/python'), str(ROOT), str(ROOT / 'scripts')]
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from waitress import create_server
from backend.app import create_app
from install_database import MIGRATIONS, migration_body
from runtime import DATA, RUNTIME, load_owner, validate_cluster


def main():
    owner = load_owner()
    validate_cluster(owner)
    common = dict(host=owner['host'], port=owner['port'], user=owner['owner_role'],
                  password=owner['owner_password'], connect_timeout=10)
    name = 'bookbridge_phase3_browser_' + uuid.uuid4().hex
    stop = RUNTIME / 'browser-qa.stop'
    if stop.exists():
        raise RuntimeError('Remove the previous stop marker before starting a new QA run.')
    created = False
    server = None
    try:
        with psycopg.connect(dbname='postgres', autocommit=True, **common) as c:
            if Path(c.execute('SHOW data_directory').fetchone()[0]).resolve() != DATA.resolve():
                raise RuntimeError('Wrong cluster')
            c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
            created = True
        with psycopg.connect(dbname=name, **common) as c:
            for migration in MIGRATIONS:
                c.execute(migration_body(migration.read_text(encoding='utf-8-sig')), prepare=False)
            c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO bookbridge_web').format(sql.Identifier(name)))
        dsn = make_conninfo(dbname=name, host=owner['host'], port=owner['port'],
                            user='bookbridge_web', password=owner['service_password'])
        app = create_app(dict(database_dsn=dsn, app_port=8768,
                              runtime_directory=str(RUNTIME / 'browser-qa-documents')))
        server = create_server(app, host='127.0.0.1', port=8768, threads=8)
        print('Browser QA ready at http://127.0.0.1:8768 (isolated database)', flush=True)
        while not stop.exists():
            server.asyncore.loop(timeout=.2, count=1, map=server._map)
    finally:
        if server:
            server.task_dispatcher.shutdown()
            server.asyncore.close_all(server._map)
            server.close()
        if created:
            with psycopg.connect(dbname='postgres', autocommit=True, **common) as c:
                c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        (RUNTIME / 'browser-qa-result.json').write_text(json.dumps(dict(database=name, database_removed=created)), encoding='utf-8')
        print('Browser QA stopped; its disposable database removed.', flush=True)


if __name__ == '__main__':
    main()
