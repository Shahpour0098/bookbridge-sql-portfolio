"""Authenticated same-origin application serving the retained Phase 1 UI."""
from __future__ import annotations
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory
from flask.json.provider import DefaultJSONProvider
import psycopg
from psycopg.rows import dict_row
from werkzeug.exceptions import HTTPException
from .security import hash_password, verify_password, token_hash

ROOT = Path(__file__).resolve().parents[1]
COOKIE = 'bookbridge_session'
USER_FIELDS = 'user_id,first_name,last_name,email,role,is_active'

class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime,)):
            return value.isoformat()
        from datetime import date, time as daytime
        if isinstance(value, (date, daytime)):
            return value.isoformat()
        return DefaultJSONProvider.default(value)

def body(fields):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - set(fields):
        raise ValueError('Die Formulardaten sind ungültig. Bitte die Seite neu laden und erneut versuchen.')
    return data

def text(data, key, limit, required=True):
    value = data.get(key, '')
    if not isinstance(value, str):
        raise ValueError(f'Das Feld {key} muss Text enthalten.')
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise ValueError(f'Bitte {key} ausfüllen (höchstens {limit} Zeichen).')
    return value

def address_values(data):
    country = text(data, 'country_code', 2).upper()
    if not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('Bitte einen Ländercode mit zwei Buchstaben angeben, beispielsweise DE.')
    coords = [None if data.get(key) in ('', None) else data[key] for key in ('latitude', 'longitude')]
    if (coords[0] is None) != (coords[1] is None):
        raise ValueError('Breiten- und Längengrad bitte gemeinsam angeben.')
    if coords[0] is not None:
        try:
            coords = [Decimal(str(value)) for value in coords]
            if not all(value.is_finite() for value in coords) or not (-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180):
                raise ValueError()
        except Exception:
            raise ValueError('Die Koordinaten sind ungültig.') from None
    return (text(data, 'street', 200), text(data, 'postal_code', 20), text(data, 'city', 100), country, *coords)

def create_app(overrides=None):
    config_path = ROOT / '.runtime/config.json'
    settings = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    settings.update(overrides or {})
    if not settings.get('database_dsn'):
        raise RuntimeError('Zuerst scripts/setup.ps1 ausführen; die lokale Datenbankkonfiguration fehlt.')
    app = Flask(__name__, static_folder=None)
    app.json = JSONProvider(app)
    app.config.update(MAX_CONTENT_LENGTH=131072, TRUSTED_HOSTS=['127.0.0.1', 'localhost', '[::1]'], APP_PORT=int(settings.get('app_port', settings.get('port', 8767))), TESTING=settings.get('TESTING', False))
    runtime = Path(settings.get('runtime_directory', ROOT / '.runtime')).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    limiter = defaultdict(deque)
    limit_lock = threading.Lock()
    dummy_hash = hash_password('BookBridge timing padding only')

    def connection():
        return psycopg.connect(settings['database_dsn'], row_factory=dict_row, options='-c search_path=bookbridge,bookbridge_app,public -c timezone=Europe/Berlin', connect_timeout=5)

    app.extensions['bookbridge_connection'] = connection

    def rate_limit(kind, identity, maximum, seconds):
        key = (kind, request.remote_addr, identity)
        now = time.monotonic()
        with limit_lock:
            queue = limiter[key]
            while queue and queue[0] < now - seconds:
                queue.popleft()
            if len(queue) >= maximum:
                abort(429, description='Zu viele Versuche. Bitte später erneut versuchen.')
            queue.append(now)
            if len(limiter) > 10000:
                for old_key in list(limiter):
                    if not limiter[old_key] or limiter[old_key][-1] < now - 3600:
                        del limiter[old_key]

    def new_session(user_id=None):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with connection() as c:
            if getattr(g, 'session_data', None):
                c.execute('DELETE FROM bookbridge_app.sessions WHERE token_hash=%s', (g.session_data['token_hash'],))
            row = c.execute('INSERT INTO bookbridge_app.sessions(token_hash,user_id,csrf_token,expires_at) VALUES(%s,%s,%s,%s) RETURNING *', (token_hash(token), user_id, csrf, datetime.now(timezone.utc)+timedelta(hours=12))).fetchone()
            if secrets.randbelow(100) == 0:
                c.execute('DELETE FROM bookbridge_app.sessions WHERE expires_at < CURRENT_TIMESTAMP')
        g.session_data = row
        g.cookie_token = token
        g.user = None
        if user_id is not None:
            with connection() as c:
                g.user = c.execute(f'SELECT {USER_FIELDS} FROM users WHERE user_id=%s', (user_id,)).fetchone()

    def load_session():
        if hasattr(g, 'session_data'):
            return
        g.session_data = None
        g.user = None
        token = request.cookies.get(COOKIE, '')
        if token and len(token) < 150:
            with connection() as c:
                g.session_data = c.execute('SELECT * FROM bookbridge_app.sessions WHERE token_hash=%s AND expires_at>CURRENT_TIMESTAMP', (token_hash(token),)).fetchone()
                if g.session_data and g.session_data['user_id']:
                    g.user = c.execute(f'SELECT {USER_FIELDS} FROM users WHERE user_id=%s', (g.session_data['user_id'],)).fetchone()
        if not g.session_data or (g.session_data['user_id'] and not g.user):
            new_session()

    def require_user():
        load_session()
        if not g.user:
            abort(401, description='Bitte zuerst anmelden.')
        return g.user

    def require_admin():
        user = require_user()
        if user['role'] != 'admin' or not user['is_active']:
            abort(403, description='Diese Verwaltung ist aktiven Administratoren vorbehalten.')
        return user

    def activation(data):
        value = data.get('is_active')
        if not isinstance(value, bool):
            raise ValueError('Für is_active bitte true oder false angeben.')
        return value

    def require_csrf():
        load_session()
        origin = request.headers.get('Origin')
        if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.scheme, request.host):
            abort(403, description='Diese Anfrage stammt nicht von BookBridge.')
        token = request.headers.get('X-CSRF-Token', '')
        if not token.isascii() or not secrets.compare_digest(token, g.session_data['csrf_token']):
            abort(403, description='Die Sitzung ist abgelaufen. Bitte die Seite neu laden.')

    def session_payload():
        load_session()
        addresses = []
        if g.user:
            with connection() as c:
                addresses = c.execute('SELECT address_id,street,postal_code,city,country_code,latitude,longitude FROM addresses WHERE user_id=%s ORDER BY address_id', (g.user['user_id'],)).fetchall()
        return {'user': g.user, 'csrf_token': g.session_data['csrf_token'], 'addresses': addresses}

    @app.before_request
    def protect_api():
        if request.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
            require_csrf()

    @app.after_request
    def headers(response):
        if hasattr(g, 'cookie_token'):
            response.set_cookie(COOKIE, g.cookie_token, max_age=43200, httponly=True, samesite='Lax', secure=bool(settings.get('secure_cookies', False)), path='/')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers['Permissions-Policy'] = 'geolocation=(self), camera=(), microphone=()'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def errors(exc):
        if isinstance(exc, HTTPException):
            code, message = exc.code, exc.description
        elif isinstance(exc, PermissionError):
            code, message = 403, str(exc)
        elif isinstance(exc, LookupError):
            code, message = 404, str(exc)
        elif isinstance(exc, ValueError):
            code, message = 400, str(exc)
        elif isinstance(exc, psycopg.Error):
            state = exc.sqlstate or ''
            if state == '23505':
                code, message = 409, 'Dieser Eintrag besteht bereits oder ein anderer Vorgang hat das Buch gerade reserviert.'
            elif state in ('42501',):
                code, message = 403, 'Für diese Aktion fehlt die Berechtigung.'
            elif state.startswith(('22','23','55','40')):
                code, message = 409, 'Die Aktion passt nicht zu den aktuellen Daten. Bitte Angaben und Status prüfen und aktualisieren.'
            else:
                code, message = 503, 'Die Datenbank ist derzeit nicht erreichbar. Bitte den lokalen Dienst prüfen.'
                app.logger.error('Database operation failed; SQLSTATE=%s', state)
        else:
            code, message = 500, 'Die Aktion konnte nicht abgeschlossen werden. Bitte erneut versuchen.'
            app.logger.exception('Unhandled application error')
        return jsonify(error=message, code=str(code)), code

    @app.get('/')
    def index():
        return send_from_directory(ROOT / 'frontend', 'index.html')

    @app.get('/app.js')
    def application_script():
        return send_from_directory(ROOT / 'frontend', 'app.js')

    @app.get('/<directory>/<path:filename>')
    def assets(directory, filename):
        if directory not in {'css','js','pictures'}:
            abort(404)
        return send_from_directory(ROOT / 'frontend' / directory, filename)

    @app.get('/api/health')
    def health():
        with connection() as c:
            c.execute('SELECT 1').fetchone()
        return jsonify(status='ok',project='bookbridge-phase3')

    @app.get('/api/session')
    def session_route():
        return jsonify(session_payload())

    @app.post('/api/register')
    def register():
        data = body({'first_name','last_name','email','password'})
        email = text(data, 'email', 254).lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Bitte eine gültige E-Mail-Adresse angeben.')
        first, last = text(data,'first_name',80), text(data,'last_name',80)
        rate_limit('register', '', 15, 3600)
        password_hash = hash_password(data.get('password'))
        with connection() as c:
            user = c.execute('INSERT INTO users(first_name,last_name,email,password_hash) VALUES(%s,%s,%s,%s) RETURNING user_id', (first,last,email,password_hash)).fetchone()
        new_session(user['user_id'])
        return jsonify(session_payload()), 201

    @app.post('/api/login')
    def login():
        data = body({'email','password'})
        email = text(data,'email',254).lower()
        rate_limit('login', email, 10, 900)
        rate_limit('login-all','',60,900)
        with connection() as c:
            user = c.execute('SELECT user_id,password_hash,is_active FROM users WHERE lower(email)=%s', (email,)).fetchone()
        valid = verify_password(data.get('password'), user['password_hash'] if user else dummy_hash)
        if not user or not valid:
            abort(401, description='E-Mail oder Passwort ist falsch.')
        new_session(user['user_id'])
        return jsonify(session_payload())

    @app.post('/api/logout')
    def logout():
        body(set())
        new_session()
        return jsonify(session_payload())

    @app.patch('/api/profile')
    def profile():
        user = require_user()
        data = body({'first_name','last_name'})
        with connection() as c:
            g.user = c.execute(f'UPDATE users SET first_name=%s,last_name=%s WHERE user_id=%s RETURNING {USER_FIELDS}', (text(data,'first_name',80),text(data,'last_name',80),user['user_id'])).fetchone()
        return jsonify(user=g.user)

    @app.post('/api/account/deactivate')
    def deactivate_account():
        user = require_user()
        body(set())
        if not user['is_active']:
            return jsonify(user=user)
        with connection() as c:
            c.execute('SELECT bookbridge.set_user_active(%s,%s,false)', (user['user_id'], user['user_id']))
            g.user = c.execute(f'SELECT {USER_FIELDS} FROM users WHERE user_id=%s', (user['user_id'],)).fetchone()
        return jsonify(user=g.user)

    @app.get('/api/admin/users')
    def admin_users():
        require_admin()
        with connection() as c:
            rows = c.execute(f'SELECT {USER_FIELDS} FROM users ORDER BY user_id').fetchall()
        return jsonify(items=rows)

    @app.get('/api/admin/offers')
    def admin_offers():
        require_admin()
        with connection() as c:
            rows = c.execute("SELECT c.copy_id,b.title,c.owner_id,"
                             "u.first_name||' '||u.last_name AS owner_name,c.is_active "
                             "FROM book_copies c JOIN books b USING(book_id) "
                             "JOIN users u ON u.user_id=c.owner_id ORDER BY c.copy_id").fetchall()
        return jsonify(items=rows)

    @app.patch('/api/admin/users/<int:user_id>')
    def admin_user_activation(user_id):
        user = require_admin()
        active = activation(body({'is_active'}))
        with connection() as c:
            if not c.execute('SELECT user_id FROM users WHERE user_id=%s', (user_id,)).fetchone():
                abort(404, description='Mitglied nicht gefunden.')
            c.execute('SELECT bookbridge.set_user_active(%s,%s,%s)', (user['user_id'], user_id, active))
            result = c.execute(f'SELECT {USER_FIELDS} FROM users WHERE user_id=%s', (user_id,)).fetchone()
        return jsonify(user=result)

    @app.patch('/api/admin/offers/<int:copy_id>')
    def admin_offer_activation(copy_id):
        user = require_admin()
        active = activation(body({'is_active'}))
        with connection() as c:
            if not c.execute('SELECT copy_id FROM book_copies WHERE copy_id=%s', (copy_id,)).fetchone():
                abort(404, description='Angebot nicht gefunden.')
            c.execute('SELECT bookbridge.set_offer_active(%s,%s,%s)', (user['user_id'], copy_id, active))
        return jsonify(copy_id=copy_id, is_active=active)

    @app.post('/api/password')
    def password():
        user = require_user()
        data = body({'current_password','new_password'})
        rate_limit('password', str(user['user_id']), 10,900)
        with connection() as c:
            current = c.execute('SELECT password_hash FROM users WHERE user_id=%s FOR UPDATE', (user['user_id'],)).fetchone()
            if not verify_password(data.get('current_password'),current['password_hash']):
                abort(400,description='Das aktuelle Passwort ist falsch.')
            c.execute('UPDATE users SET password_hash=%s WHERE user_id=%s',(hash_password(data.get('new_password')),user['user_id']))
            c.execute('DELETE FROM bookbridge_app.sessions WHERE user_id=%s AND token_hash<>%s',(user['user_id'],g.session_data['token_hash']))
        return jsonify(ok=True)

    @app.get('/api/addresses')
    def addresses():
        require_user()
        return jsonify(addresses=session_payload()['addresses'])

    @app.post('/api/addresses')
    def add_address():
        user = require_user()
        data = body({'street','postal_code','city','country_code','latitude','longitude'})
        values = address_values(data)
        with connection() as c:
            address = c.execute('INSERT INTO addresses(user_id,street,postal_code,city,country_code,latitude,longitude) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING address_id,street,postal_code,city,country_code,latitude,longitude', (user['user_id'], *values)).fetchone()
        return jsonify(address=address),201

    @app.patch('/api/addresses/<int:address_id>')
    def edit_address(address_id):
        user = require_user()
        data = body({'street','postal_code','city','country_code','latitude','longitude'})
        values = address_values(data)
        with connection() as c:
            address = c.execute('UPDATE addresses SET street=%s,postal_code=%s,city=%s,country_code=%s,latitude=%s,longitude=%s '
                                'WHERE address_id=%s AND user_id=%s '
                                'RETURNING address_id,street,postal_code,city,country_code,latitude,longitude',
                                (*values, address_id, user['user_id'])).fetchone()
            if address is None:
                abort(404, description='Eigene Anschrift nicht gefunden.')
        return jsonify(address=address)

    @app.get('/api/notifications')
    def notifications():
        user = require_user()
        with connection() as c:
            c.execute("UPDATE notifications SET status='delivered',delivered_at=GREATEST(CURRENT_TIMESTAMP,created_at) WHERE recipient_user_id=%s AND channel='in_app' AND status='queued'", (user['user_id'],))
            rows = c.execute("SELECT notification_id,loan_id,message,status,created_at,read_at FROM notifications WHERE recipient_user_id=%s AND channel='in_app' ORDER BY created_at DESC,notification_id DESC LIMIT 100", (user['user_id'],)).fetchall()
        return jsonify(items=rows)

    @app.post('/api/notifications/<int:notification_id>/read')
    def read_notification(notification_id):
        user = require_user()
        body(set())
        with connection() as c:
            row = c.execute("UPDATE notifications SET status='delivered',delivered_at=coalesce(delivered_at,GREATEST(CURRENT_TIMESTAMP,created_at)),read_at=coalesce(read_at,GREATEST(CURRENT_TIMESTAMP,created_at,delivered_at)) WHERE notification_id=%s AND recipient_user_id=%s AND channel='in_app' RETURNING notification_id", (notification_id,user['user_id'])).fetchone()
            if not row:
                abort(404,description='Mitteilung nicht gefunden.')
        return jsonify(ok=True)

    @app.get('/api/documents/<int:document_id>/download')
    def download_document(document_id):
        user = require_user()
        with connection() as c:
            document = c.execute('SELECT * FROM generated_documents WHERE document_id=%s AND recipient_user_id=%s FOR UPDATE', (document_id,user['user_id'])).fetchone()
            if not document:
                abort(404,description='Dokument nicht gefunden.')
            if document['status']=='created':
                path = (runtime / document['storage_path']).resolve()
                if not path.is_relative_to(runtime / 'documents') or not path.is_file():
                    abort(410,description='Die gespeicherte Datei fehlt. Bitte die Dokumentensicherung wiederherstellen.')
            else:
                loan = c.execute('SELECT l.*,b.title,ou.first_name||\' \'||ou.last_name AS owner_name,bu.first_name||\' \'||bu.last_name AS borrower_name FROM loans l JOIN book_copies bc USING(copy_id) JOIN books b USING(book_id) JOIN users ou ON ou.user_id=bc.owner_id JOIN users bu ON bu.user_id=l.borrower_id WHERE l.loan_id=%s', (document['loan_id'],)).fetchone()
                shipment = c.execute('SELECT * FROM shipments WHERE shipment_id=%s',(document['shipment_id'],)).fetchone() if document['shipment_id'] else None
                path = runtime / 'documents' / f'document-{document_id}.pdf'
                path.parent.mkdir(parents=True, exist_ok=True)
                generated_at = max(datetime.now(timezone.utc),document['created_at'])
                temporary = path.with_suffix('.'+secrets.token_hex(8)+'.tmp')
                try:
                    temporary.write_bytes(build_pdf(document,loan,shipment,generated_at))
                    temporary.replace(path)
                    c.execute("UPDATE generated_documents SET status='created',storage_path=%s,generated_at=%s WHERE document_id=%s",(path.relative_to(runtime).as_posix(),generated_at,document_id))
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise
        return send_file(path,mimetype='application/pdf',as_attachment=True,download_name=f'BookBridge-{document_id}.pdf',conditional=False)

    from .domain import register_routes
    register_routes(app,connection,require_user,require_csrf)
    return app

def build_pdf(document,loan,shipment,generated_at):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    labels = {'loan_confirmation':'Ausleihbestätigung','shipment_summary':'Versandübersicht','return_confirmation':'Rückgabebestätigung'}
    out = BytesIO()
    pdf = SimpleDocTemplate(out,pagesize=(21*cm,29.7*cm),rightMargin=2*cm,leftMargin=2*cm,topMargin=2*cm,bottomMargin=2*cm,title=labels[document['document_type']],author='BookBridge')
    styles = getSampleStyleSheet()
    for name in ('Normal','BodyText'):
        styles[name].fontName='Helvetica'
        styles[name].fontSize=10
        styles[name].leading=15
        styles[name].alignment=TA_LEFT
    safe = lambda value: escape(str(value if value is not None else '–')).replace('\n','<br/>')
    story=[Paragraph('BookBridge',styles['Title']),Spacer(1,0.4*cm),Paragraph(labels[document['document_type']],styles['Heading1']),Paragraph('Gespeicherte Bestätigung für die teilnehmenden Personen. Erstellt am '+safe(generated_at.isoformat()),styles['BodyText']),Spacer(1,0.5*cm)]
    fields=[('Ausleihe',loan['loan_id']),('Buch',loan['title']),('Eigentümer/in',loan['owner_name']),('Ausleihende Person',loan['borrower_name']),('Übergabe','Abholung' if loan['handover_mode']=='pickup' else 'Versand'),('Vereinbarte Dauer',str(loan['agreed_days'])+' Tage'),('Annahme',loan['accepted_at'])]
    if document['document_type']=='return_confirmation':
        fields.append(('Rückerhalt',loan['completed_at']))
    if loan['pickup_address_snapshot']:
        fields += [('Vereinbarte Abholung',loan['pickup_start_at']),('Abholanschrift',loan['pickup_address_snapshot'])]
    if shipment:
        fields += [('Versandrichtung','Hinversand' if shipment['direction']=='outbound' else 'Rückversand'),('Absender',shipment['sender_address_snapshot']),('Empfänger',shipment['recipient_address_snapshot']),('Versanddienst',shipment['carrier']),('Sendungsnummer',shipment['tracking_number'])]
    table=Table([[Paragraph(safe(k),styles['BodyText']),Paragraph(safe(v),styles['BodyText'])] for k,v in fields],colWidths=[5*cm,12*cm],hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),0.4,colors.HexColor('#D9D9D9')),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story += [table,Spacer(1,0.6*cm),Paragraph('Diese Bestätigung dokumentiert den in BookBridge gespeicherten Vorgang. Sie ist kein Zahlungsbeleg und kein Versandetikett.',styles['BodyText'])]
    pdf.build(story)
    return out.getvalue()
