"""Real PostgreSQL/API verification in a fresh, uniquely named disposable DB.

Requires this project's setup. Never writes application data to the main DB.
Only the database created by this invocation is removed, even after failure.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.runtime/python'), str(ROOT), str(ROOT / 'scripts')]
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from backend.app import create_app
from install_database import MIGRATIONS, migration_body
from runtime import load_owner, validate_cluster, DATA


def verify(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    owner = load_owner()
    validate_cluster(owner)
    common = dict(host=owner['host'], port=owner['port'], user=owner['owner_role'],
                  password=owner['owner_password'], connect_timeout=10)
    name = 'bookbridge_phase3_verify_' + uuid.uuid4().hex
    report = dict(started_at=datetime.now(timezone.utc).isoformat(), database=name,
                  database_created=False, database_removed=False, tests=[], status='running')
    created = False

    def save():
        (output / 'integration-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def passed(label):
        report['tests'].append(dict(name=label, status='passed'))
        print('PASS ' + label)

    def expect(response, code=200):
        if response.status_code != code:
            detail = (response.get_json(silent=True) or {}).get('error', '')
            raise AssertionError(f'HTTP {response.status_code}, expected {code}: {detail}')
        return response.get_json(silent=True)

    try:
        with psycopg.connect(dbname='postgres', autocommit=True, **common) as c:
            if Path(c.execute('SHOW data_directory').fetchone()[0]).resolve() != DATA.resolve():
                raise RuntimeError('Cluster identity mismatch')
            c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
            created = report['database_created'] = True
        with psycopg.connect(dbname=name, **common) as c:
            for path in MIGRATIONS:
                c.execute(migration_body(path.read_text(encoding='utf-8-sig')), prepare=False)
            c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO bookbridge_web').format(sql.Identifier(name)))
        passed('Fresh template0 database installs every application migration')
        with psycopg.connect(dbname=name, row_factory=dict_row, **common) as c:
            tables = c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='bookbridge' AND table_type='BASE TABLE' ORDER BY table_name").fetchall()
            counts = {t['table_name']: c.execute(sql.SQL('SELECT count(*) AS n FROM bookbridge.{}').format(sql.Identifier(t['table_name']))).fetchone()['n'] for t in tables}
            metadata = c.execute("""SELECT pg_database_size(current_database()) AS bytes,
                (SELECT count(*) FROM information_schema.columns c
                 JOIN information_schema.tables t USING(table_catalog,table_schema,table_name)
                 WHERE c.table_schema='bookbridge' AND t.table_type='BASE TABLE') AS columns,
                (SELECT count(*) FROM information_schema.table_constraints
                 WHERE table_schema='bookbridge' AND constraint_type='FOREIGN KEY') AS foreign_keys,
                (SELECT count(*) FROM information_schema.views
                 WHERE table_schema='bookbridge') AS view_count,
                (SELECT count(*) FROM information_schema.columns c
                 JOIN information_schema.views v USING(table_catalog,table_schema,table_name)
                 WHERE c.table_schema='bookbridge') AS view_columns,
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_schema='bookbridge_app' AND table_type='BASE TABLE') AS technical_table_count,
                (SELECT count(*) FROM information_schema.columns c
                 JOIN information_schema.tables t USING(table_catalog,table_schema,table_name)
                 WHERE c.table_schema='bookbridge_app' AND t.table_type='BASE TABLE') AS technical_columns
                """).fetchone()
            report['baseline'] = dict(table_count=len(tables), row_count=sum(counts.values()), rows=counts,
                bytes_scope='Whole PostgreSQL database, including system catalogs and application objects', **metadata)
        assert len(tables) == 18 and sum(counts.values()) == 1431
        assert (metadata['columns'], metadata['foreign_keys'], metadata['view_count'], metadata['view_columns']) == (142, 32, 1, 15)
        assert (metadata['technical_table_count'], metadata['technical_columns']) == (2, 8)
        passed('Retained Phase 2 baseline: 18 tables and 1431 fictitious rows')
        # Re-run the original SQL suite against the integrated schema too. Its
        # own race database is a second UUID clone and is removed by that suite.
        module_spec = importlib.util.spec_from_file_location('phase2_regression', ROOT / 'tests/phase2_regression.py')
        phase2 = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(phase2)
        saved_arguments = sys.argv
        try:
            sys.argv = ['phase2_regression', '--dsn', make_conninfo(dbname=name, **common), '--out', str(output / 'phase2')]
            assert phase2.main() == 0, 'Original Phase 2 regression failed'
        finally:
            sys.argv = saved_arguments
        report['phase2_regression'] = json.loads((output / 'phase2/test-report.json').read_text(encoding='utf-8'))['summary']
        passed('All original Phase 2 SQL tests also pass on the integrated schema')
        dsn = make_conninfo(dbname=name, host=owner['host'], port=owner['port'], user='bookbridge_web', password=owner['service_password'])
        temporary_root = ROOT / '.runtime' / 'test-tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='bookbridge-phase3-api-', dir=temporary_root) as runtime:
            app = create_app(dict(database_dsn=dsn, runtime_directory=runtime, TESTING=True))
            clients = [app.test_client() for _ in range(3)]
            tokens = {}

            for public_path in ('/api/meta', '/api/catalog'):
                public_response = clients[0].get(public_path)
                expect(public_response)
                assert 'Set-Cookie' not in public_response.headers
            passed('Public catalogue and metadata do not overwrite a fresh browser session')

            def get(client, path):
                return expect(client.get(path))

            def send(client, path, data, code=200, method='POST'):
                response = client.open(path, method=method, json=data, headers={'X-CSRF-Token': tokens[id(client)]})
                payload = expect(response, code)
                if payload and payload.get('csrf_token'):
                    tokens[id(client)] = payload['csrf_token']
                return payload

            def act(client, loan, action, code=200, **fields):
                return send(client, f'/api/loans/{loan}/actions', dict(action=action, **fields), code)['id'] if code == 200 else send(client, f'/api/loans/{loan}/actions', dict(action=action, **fields), code)

            for client in clients:
                tokens[id(client)] = get(client, '/api/session')['csrf_token']
            guest = clients[2]
            assert guest.get('/').status_code == 200
            assert guest.get('/app.js').status_code == 200
            expect(guest.get('/api/my-books'), 401)
            expect(guest.post('/api/register', json={}), 403)
            passed('Application assets, anonymous access and CSRF rejection')

            accounts = []
            for i, client in enumerate(clients):
                account = dict(first_name=['Mara','Jonas','Nora'][i], last_name='Prüfung', email=f'phase3-{i}@example.invalid', password='Testkonto nur lokal 2026!')
                accounts.append(account)
                result = send(client, '/api/register', account, 201)
                assert result['user']['email'] == account['email']
            owner_client, borrower, outsider = clients
            passed('Three isolated real-password accounts and rotated sessions')
            expect(owner_client.get('/api/admin/users'), 403)
            send(owner_client, '/api/admin/users/1', {'is_active': False}, 403, method='PATCH')
            # Privileged role provisioning is a fixture performed by the local
            # DB owner, never a web signup/profile field.
            admin_id = get(outsider, '/api/session')['user']['user_id']
            borrower_id = get(borrower, '/api/session')['user']['user_id']
            with psycopg.connect(dbname=name, **common) as c:
                c.execute("UPDATE bookbridge.users SET role='admin' WHERE user_id=%s", (admin_id,))
            assert get(outsider, '/api/admin/users')['items']
            passed('Moderation requires an active administrator; signup cannot assign roles')
            # Password changes revoke other sessions while retaining this one.
            second = app.test_client()
            tokens[id(second)] = get(second, '/api/session')['csrf_token']
            send(second, '/api/login', dict(email=accounts[0]['email'], password=accounts[0]['password']))
            send(owner_client, '/api/password', dict(current_password=accounts[0]['password'], new_password='Neues Testpasswort lokal 2026!'))
            assert get(second, '/api/session')['user'] is None
            assert get(owner_client, '/api/session')['user'] is not None
            passed('Password change revokes another browser session')
            expect(owner_client.post('/api/profile', json={}, headers={'X-CSRF-Token': tokens[id(owner_client)], 'Origin':'https://foreign.invalid'}), 403)
            expect(owner_client.get('/api/session', headers={'Host':'foreign.invalid'}), 400)
            passed('Foreign Origin and untrusted Host rejected')

            addresses = []
            for i, client in enumerate(clients):
                result = send(client, '/api/addresses', dict(street=f'Fiktive Prüfstraße {i+1}', postal_code='10115', city='Berlin', country_code='DE', latitude=52.53, longitude=13.38), 201)
                addresses.append(result['address']['address_id'])
            meta = get(guest, '/api/meta')
            offer = dict(title='Prüfbuch über sichere Ausleihen', author='Fiktive Testautorin',
                         genre_id=meta['genres'][0]['genre_id'], language_id=meta['languages'][0]['language_id'],
                         condition='good', max_loan_days=30, address_id=addresses[0], allow_pickup=True, allow_shipping=True,
                         pickup_slots=[dict(weekday=1, start_time='16:00', end_time='18:00')])
            copy_id = send(owner_client, '/api/books', offer, 201)['copy_id']
            detail = get(outsider, f'/api/catalog/{copy_id}')
            forbidden = {'street','latitude','longitude','email','password_hash','pickup_address_snapshot'}
            assert not forbidden.intersection(detail['item'])
            catalog = get(outsider, '/api/catalog?query=Prüfbuch&radius=2&latitude=52.53&longitude=13.38')
            assert catalog['total'] == 1 and catalog['items'][0]['distance_km'] == 0
            assert get(outsider, '/api/catalog?query=Prüfbuch&city=10115')['total'] == 1
            assert get(outsider, '/api/catalog?query=Prüfbuch&city=berlin')['total'] == 1
            assert get(outsider, '/api/catalog?query=Prüfbuch&city=99999')['total'] == 0
            passed('Own offer with pickup window; public catalogue and radius preserve privacy')
            assert any(x['copy_id'] == copy_id for x in get(outsider, '/api/admin/offers')['items'])
            send(outsider, f'/api/admin/offers/{copy_id}', {'is_active': False}, method='PATCH')
            expect(guest.get(f'/api/catalog/{copy_id}'), 404)
            send(outsider, f'/api/admin/offers/{copy_id}', {'is_active': True}, method='PATCH')
            passed('Administrator can pause and restore an offer without editing its owner')
            send(outsider, f'/api/books/{copy_id}', dict(notes='Forbidden'), 403, method='PATCH')
            send(owner_client, '/api/loans', dict(copy_id=copy_id, days=7, mode='pickup'), 403)
            send(borrower, '/api/loans', dict(copy_id=copy_id, days=7, mode='pickup', actor_id=999), 400)
            passed('Other-owner edit, self-borrowing and actor spoofing blocked')
            loan = send(borrower, '/api/loans', dict(copy_id=copy_id, days=7, mode='pickup'), 201)['loan_id']

            def current(client, loan_id):
                return next(x for x in get(client, '/api/loans')['items'] if x['loan_id'] == loan_id)

            assert not get(outsider, '/api/loans')['items']
            assert current(borrower, loan)['pickup_address_snapshot'] is None
            act(outsider, loan, 'accept', 403)
            initial_slot = detail['pickup_slots'][0]
            act(borrower, loan, 'accept', 403, slot_id=initial_slot['slot_id'], start_at=initial_slot['next_start_at'], end_at=initial_slot['next_end_at'])
            passed('Participant-only loans and concealed address before acceptance')
            proposal = act(owner_client, loan, 'propose', days=6)
            act(owner_client, loan, 'decide_proposal', proposal_id=proposal, decision='withdrawn')
            proposal = act(owner_client, loan, 'propose', days=7)
            slot = detail['pickup_slots'][0]
            act(borrower, loan, 'decide_proposal', proposal_id=proposal, decision='accepted', slot_id=slot['slot_id'], start_at=slot['next_start_at'], end_at=slot['next_end_at'])
            assert current(borrower, loan)['status'] == 'accepted'
            assert current(borrower, loan)['pickup_address_snapshot']
            passed('Counterproposal withdrawal and acceptance with Berlin appointment')
            frozen = current(borrower, loan)
            edited_address = dict(street='Fiktive neue Prüfstraße 9', postal_code='10115', city='Berlin', country_code='DE', latitude=52.53, longitude=13.38)
            send(outsider, f'/api/addresses/{addresses[0]}', edited_address, 404, method='PATCH')
            send(owner_client, f'/api/addresses/{addresses[0]}', edited_address, method='PATCH')
            changed_slots = [dict(weekday=2, start_time='15:00', end_time='17:00')]
            send(owner_client, f'/api/books/{copy_id}', dict(address_id=addresses[0], allow_pickup=True, allow_shipping=True,
                 max_loan_days=20, pickup_slots=changed_slots), method='PATCH')
            history = current(borrower, loan)
            assert history['pickup_address_snapshot'] == frozen['pickup_address_snapshot']
            assert history['pickup_start_at'] == frozen['pickup_start_at']
            assert history['max_loan_days_snapshot'] == 30
            changed_detail = get(outsider, f'/api/catalog/{copy_id}')
            assert changed_detail['pickup_slots'][0]['weekday'] == 2
            assert changed_detail['pickup_slots'][0]['slot_id'] != slot['slot_id']
            assert get(owner_client, '/api/my-books')['items'][0]['address_id'] == addresses[0]
            passed('Own address and weekly-plan edits preserve accepted time, address and duration snapshots')
            send(owner_client, f'/api/addresses/{addresses[0]}', dict(edited_address, latitude=None, longitude=None), 409, method='PATCH')
            assert get(owner_client, '/api/addresses')['addresses'][0]['latitude'] is not None
            passed('Invalid coordinate removal rolls back while an active offer uses the address')
            document = current(owner_client, loan)['documents'][0]
            with owner_client.get(document['download_url']) as pdf:
                pdf_bytes = pdf.data
                assert pdf.status_code == 200 and pdf_bytes.startswith(b'%PDF-')
            expect(outsider.get(document['download_url']), 404)
            with owner_client.get(document['download_url']) as pdf_again:
                assert pdf_again.data == pdf_bytes
            (output / 'sample-loan-confirmation.pdf').write_bytes(pdf_bytes)
            passed('Actual PDF generated once; stable bytes and recipient-only download')
            act(borrower, loan, 'receive_pickup')
            deactivated = send(borrower, '/api/account/deactivate', {})
            assert not get(borrower, '/api/session')['user']['is_active']
            send(borrower, '/api/loans', dict(copy_id=copy_id, days=7, mode='pickup'), 403)
            # Inactive members can sign in to finish an existing obligation.
            inactive_login = app.test_client()
            tokens[id(inactive_login)] = get(inactive_login, '/api/session')['csrf_token']
            login_result = send(inactive_login, '/api/login', dict(email=accounts[1]['email'], password=accounts[1]['password']))
            assert login_result['user'] and not login_result['user']['is_active']
            passed('Inactive member keeps access and can sign in but cannot start new loans')
            before_due = current(borrower, loan)['due_date']
            extension = act(borrower, loan, 'request_extension', days=2)
            act(borrower, loan, 'decide_extension', extension_id=extension, decision='withdrawn')
            extension = act(borrower, loan, 'request_extension', days=3)
            act(owner_client, loan, 'decide_extension', extension_id=extension, decision='approved')
            assert current(borrower, loan)['due_date'] != before_due
            passed('Pickup receipt, extension withdrawal and approval update due date')
            act(borrower, loan, 'start_return')
            act(owner_client, loan, 'confirm_return')
            act(borrower, loan, 'review', rating=5, comment='Rein fiktiver API-Prüflauf')
            act(owner_client, loan, 'review', rating=4, comment='Fiktive Rückgabeprüfung')
            assert current(borrower, loan)['status'] == 'completed'
            assert len(current(borrower, loan)['reviews']) == 2
            assert get(outsider, f'/api/catalog/{copy_id}')['item']['available']
            passed('Pickup return, two participant reviews and restored availability')
            send(outsider, f'/api/admin/users/{borrower_id}', {'is_active': True}, method='PATCH')
            assert get(borrower, '/api/session')['user']['is_active']
            passed('Administrator reactivates account after existing return is completed')
            # Postal round trip uses the same newly available copy.
            shipping = send(borrower, '/api/loans', dict(copy_id=copy_id, days=8, mode='shipping'), 201)['loan_id']
            act(owner_client, shipping, 'accept')
            assert current(owner_client, shipping)['recipient_addresses']
            act(owner_client, shipping, 'decide_extension', 404, extension_id=extension, decision='approved')
            passed('Shipping acceptance shares necessary addresses; cross-loan child ID blocked')
            shipment = act(owner_client, shipping, 'prepare_shipment', direction='outbound', sender_address_id=addresses[0], recipient_address_id=addresses[1], carrier='Fiktiver Prüfdienst', tracking_number='TEST-OUT')
            act(owner_client, shipping, 'send_shipment', 409, shipment_id=shipment)
            payment = act(owner_client, shipping, 'create_postage', outbound_fee='2.50', return_fee='2.50')
            act(borrower, shipping, 'report_postage', payment_id=payment)
            act(owner_client, shipping, 'confirm_postage', payment_id=payment)
            act(owner_client, shipping, 'send_shipment', shipment_id=shipment)
            act(borrower, shipping, 'receive_shipment', shipment_id=shipment)
            assert current(borrower, shipping)['status'] == 'active'
            passed('Postage required, reported and confirmed; outbound dispatch and receipt')
            return_shipment = act(borrower, shipping, 'prepare_shipment', direction='return', sender_address_id=addresses[1], recipient_address_id=addresses[0], carrier='Fiktiver Prüfdienst', tracking_number='TEST-RETURN')
            act(borrower, shipping, 'send_shipment', shipment_id=return_shipment)
            act(owner_client, shipping, 'receive_shipment', shipment_id=return_shipment)
            result = current(owner_client, shipping)
            assert result['status'] == 'completed'
            assert not result['recipient_addresses'] and not result['sender_addresses']
            assert result['shipments'][0]['recipient_address_snapshot']
            passed('Postal return completes; live addresses hidden and historical snapshots retained')
            notifications = get(borrower, '/api/notifications')['items']
            notification = notifications[0]['notification_id']
            send(outsider, f'/api/notifications/{notification}/read', {}, 404)
            send(borrower, f'/api/notifications/{notification}/read', {})
            assert next(n for n in get(borrower, '/api/notifications')['items'] if n['notification_id']==notification)['read_at']
            passed('Notifications delivered and marked read only by recipient')
            # Logout invalidates the previous browser token.
            prior_cookie = borrower.get_cookie('bookbridge_session').value
            send(borrower, '/api/logout', {})
            assert get(borrower, '/api/session')['user'] is None
            second.set_cookie('bookbridge_session', prior_cookie)
            assert get(second, '/api/session')['user'] is None
            passed('Logout revokes old session token')
            report['sample_pdf_sha256'] = hashlib.sha256(pdf_bytes).hexdigest()
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if created:
            with psycopg.connect(dbname='postgres', autocommit=True, **common) as c:
                # name originates solely from this invocation's UUID above.
                c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            report['database_removed'] = True
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence' / ('api-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    result = verify(args.output.resolve())
    print(f"{len(result['tests'])} checks passed; disposable database removed.")
