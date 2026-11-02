"""BookBridge HTTP boundary for the unchanged Phase 2 domain workflows.

The connection factory supplies transactional psycopg3 connections with dict_row.
Authentication, CSRF and error translation belong to app.py. Business transitions
always run through the Phase 2 functions; the HTTP client cannot choose an actor
or an event timestamp.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import re
from zoneinfo import ZoneInfo

from flask import jsonify, request


BERLIN = ZoneInfo("Europe/Berlin")
UTC = timezone.utc
PAGE_SIZE = 12
CONDITIONS = {"new", "very_good", "good", "used"}
BINDING = ("accepted", "outbound", "active", "returning")
# Live addresses are needed to prepare a parcel during an ongoing loan only.
# Completed history retains its immutable shipment address snapshots instead.
SHARED_ADDRESS_STATES = set(BINDING)
# Only these three actual editions have retained, documented cover assets.
COVERS = {
    "9783792000571": "/pictures/der-kleine-prinz.jpg",
    "9783522202756": "/pictures/momo.png",
    "9783257229530": "/pictures/der-vorleser.jpg",
}


def _json_value(value):
    """Use ISO values, including timezone offsets (Flask defaults to HTTP dates)."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _body(allowed, required=()):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Bitte ein gültiges JSON-Objekt senden.")
    _fields(data, allowed, required)
    return data


def _fields(data, allowed, required=()):
    if set(data) - set(allowed):
        raise ValueError("Die Anfrage enthält nicht unterstützte Felder.")
    if set(required) - set(data):
        raise ValueError("Erforderliche Angaben fehlen.")


def _integer(value, label, minimum=1, maximum=9223372036854775807):
    if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value or "")):
        raise ValueError(f"{label}: Bitte eine ganze Zahl angeben.")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{label}: Wert außerhalb des zulässigen Bereichs.")
    return result


def _text(value, label, maximum, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}: Bitte Text angeben.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} darf nicht leer sein.")
    if len(value) > maximum:
        raise ValueError(f"{label}: Höchstens {maximum} Zeichen erlaubt.")
    return value or None


def _boolean(value, label):
    if not isinstance(value, bool):
        raise ValueError(f"{label}: Bitte true oder false angeben.")
    return value


def _active(user):
    if not user.get("is_active", True):
        raise PermissionError("Dein Konto ist deaktiviert. Bestehende Ausleihen kannst du weiterhin abschließen; "
                              "neue Angebote, Anfragen und Annahmen sind gesperrt.")


def _choice(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label}: Ungültiger Wert.")
    return value


def _money(value, label):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label}: Bitte einen gültigen EUR-Betrag angeben.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}: Bitte einen gültigen EUR-Betrag angeben.") from None
    if not number.is_finite() or number < 0 or number > Decimal("999999.99"):
        raise ValueError(f"{label}: Bitte einen Betrag von 0 bis 999999,99 EUR angeben.")
    if number != number.quantize(Decimal("0.01")):
        raise ValueError(f"{label}: Höchstens zwei Nachkommastellen erlaubt.")
    return number


def _clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value):
        raise ValueError("Abholzeiten müssen das Format HH:MM haben.")
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError("Die Abholzeit ist ungültig.") from None


def _pickup_slots(raw):
    if not isinstance(raw, list) or len(raw) > 28:
        raise ValueError("Bitte höchstens 28 gültige Abholzeitfenster angeben.")
    slots = []
    for slot in raw:
        if not isinstance(slot, dict):
            raise ValueError("Ein Abholzeitfenster muss ein Objekt sein.")
        _fields(slot, {"weekday", "start_time", "end_time"}, {"weekday", "start_time", "end_time"})
        weekday = _integer(slot["weekday"], "Wochentag", 1, 7)
        start, end = _clock(slot["start_time"]), _clock(slot["end_time"])
        if end <= start:
            raise ValueError("Das Ende eines Abholzeitfensters muss nach dessen Beginn liegen.")
        slots.append((weekday, start, end))
    ordered = sorted(slots)
    for previous, current in zip(ordered, ordered[1:]):
        if previous[0] == current[0] and current[1] < previous[2]:
            raise ValueError("Wöchentliche Abholzeitfenster dürfen sich nicht überschneiden.")
    return slots


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("Der Abholtermin benötigt Datum, Uhrzeit und Zeitzonenoffset.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Der Abholtermin ist kein gültiger ISO-Zeitpunkt.") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Der Abholtermin benötigt einen Zeitzonenoffset, z. B. +02:00.")
    return result


def _local_candidates(day, clock):
    """Round-trip validation skips nonexistent times during the DST spring gap."""
    naive = datetime.combine(day, clock)
    candidates = {}
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=BERLIN, fold=fold)
        utc = candidate.astimezone(UTC)
        if utc.astimezone(BERLIN).replace(tzinfo=None) == naive:
            candidates[utc] = candidate
    return [candidates[key] for key in sorted(candidates)]


def next_pickup_occurrence(weekday, start_time, end_time, now=None):
    """Return the next whole future window in Berlin, handling both DST changes."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Ein Zeitzonenoffset ist erforderlich.")
    local_now = now.astimezone(BERLIN)
    first_day = local_now.date() + timedelta(days=(weekday - local_now.isoweekday()) % 7)
    for week in range(8):
        day = first_day + timedelta(weeks=week)
        for start in _local_candidates(day, start_time):
            if start.astimezone(UTC) <= now.astimezone(UTC):
                continue
            for end in _local_candidates(day, end_time):
                if end.astimezone(UTC) > start.astimezone(UTC):
                    return start, end
    raise ValueError("Für dieses Zeitfenster konnte kein künftiger Termin ermittelt werden.")


def _slots(conn, copy_ids):
    if not copy_ids:
        return {}
    rows = conn.execute(
        "SELECT slot_id,copy_id,weekday,start_time,end_time FROM bookbridge.pickup_slots "
        "WHERE copy_id=ANY(%s) AND is_active ORDER BY weekday,start_time,slot_id",
        (list(copy_ids),),
    ).fetchall()
    result = {}
    now = datetime.now(UTC)
    for row in rows:
        row = dict(row)
        start, end = next_pickup_occurrence(row["weekday"], row["start_time"], row["end_time"], now)
        row.update(next_start_at=start, next_end_at=end)
        copy_id = row.pop("copy_id")
        result.setdefault(copy_id, []).append(row)
    return result


CATALOG_SELECT = """
    SELECT c.copy_id,c.book_id,b.title,b.isbn,b.description,b.publication_year,
           p.name AS publisher,b.genre_id,b.language_id,
           (SELECT string_agg(au.display_name,', ' ORDER BY ba.author_order)
            FROM bookbridge.book_authors ba JOIN bookbridge.authors au USING(author_id)
            WHERE ba.book_id=b.book_id) AS authors,
           g.name AS genre,lg.name AS language,c.condition,c.max_loan_days,
           c.allow_pickup,c.allow_shipping,c.is_active,c.notes,
           (c.is_active AND u.is_active AND NOT EXISTS(
              SELECT 1 FROM bookbridge.loans l WHERE l.copy_id=c.copy_id
              AND l.status IN ('accepted','outbound','active','returning'))) AS available,
           ad.city,ad.postal_code,c.owner_id
           {distance}
    FROM bookbridge.book_copies c
    JOIN bookbridge.books b ON b.book_id=c.book_id
    JOIN bookbridge.users u ON u.user_id=c.owner_id
    LEFT JOIN bookbridge.addresses ad ON ad.address_id=c.pickup_address_id
    JOIN bookbridge.genres g ON g.genre_id=b.genre_id
    JOIN bookbridge.languages lg ON lg.language_id=b.language_id
    LEFT JOIN bookbridge.publishers p ON p.publisher_id=b.publisher_id
"""


def _catalog_item(row):
    item = dict(row)
    item["cover_url"] = COVERS.get(item.get("isbn"))
    if item.get("distance_km") is not None:
        item["distance_km"] = round(float(item["distance_km"]), 2)
    return item


def _norm(value):
    return " ".join((value or "").split()).casefold()


def _existing_book(conn, data, isbn, title, author, genre_id, language_id):
    # Serialize same-ISBN creation so concurrent requests do not rewrite or race
    # shared bibliography. This is an application transaction lock, not a secret.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("bookbridge-isbn:" + isbn,))
    row = conn.execute(
        "SELECT b.*,p.name AS publisher,"
        "(SELECT string_agg(a.display_name,', ' ORDER BY ba.author_order) "
        " FROM bookbridge.book_authors ba JOIN bookbridge.authors a USING(author_id) "
        " WHERE ba.book_id=b.book_id) AS authors "
        "FROM bookbridge.books b LEFT JOIN bookbridge.publishers p USING(publisher_id) "
        "WHERE b.isbn=%s", (isbn,),
    ).fetchone()
    if row is None:
        return None
    conflicts = []
    for label, provided, saved in (
        ("Titel", title, row["title"]), ("Autor", author, row["authors"]),
        ("Genre", genre_id, row["genre_id"]), ("Sprache", language_id, row["language_id"]),
    ):
        if _norm(str(provided)) != _norm(str(saved)):
            conflicts.append(label)
    for key, label in (("publisher", "Verlag"), ("publication_year", "Erscheinungsjahr"), ("description", "Beschreibung")):
        if data.get(key) not in (None, "") and _norm(str(data[key])) != _norm(str(row[key] or "")):
            conflicts.append(label)
    if conflicts:
        raise ValueError(
            "Diese ISBN ist bereits mit anderen bibliografischen Angaben gespeichert ("
            + ", ".join(conflicts)
            + "). Bitte die vorhandenen Angaben verwenden. Gemeinsame Titeldaten werden nicht überschrieben."
        )
    return row["book_id"]


def _participant_loan(conn, loan_id, actor):
    row = conn.execute(
        "SELECT l.*,c.owner_id FROM bookbridge.loans l "
        "JOIN bookbridge.book_copies c USING(copy_id) WHERE l.loan_id=%s", (loan_id,),
    ).fetchone()
    if row is None:
        raise LookupError("Die Ausleihe wurde nicht gefunden.")
    if actor not in (row["owner_id"], row["borrower_id"]):
        raise PermissionError("Auf diese Ausleihe dürfen nur ihre Teilnehmer zugreifen.")
    return row


def _child(conn, table, column, value, loan_id):
    # Table/column identifiers are selected solely by the fixed action map below.
    child_id = _integer(value, "Vorgangs-ID")
    row = conn.execute(
        f"SELECT {column} FROM bookbridge.{table} WHERE {column}=%s AND loan_id=%s",
        (child_id, loan_id),
    ).fetchone()
    if row is None:
        raise LookupError("Der Untervorgang gehört nicht zu dieser Ausleihe oder existiert nicht.")
    return child_id


def _appointment(conn, data, loan):
    fields = ("slot_id", "start_at", "end_at")
    if loan["handover_mode"] == "shipping":
        if any(data.get(field) is not None for field in fields):
            raise ValueError("Beim Versand darf kein Abholtermin angegeben werden.")
        return None, None, None
    if any(data.get(field) is None for field in fields):
        raise ValueError("Für die Abholung bitte ein Zeitfenster und einen künftigen Termin auswählen.")
    slot_id = _integer(data["slot_id"], "Abholzeitfenster")
    if conn.execute(
        "SELECT 1 FROM bookbridge.pickup_slots WHERE slot_id=%s AND copy_id=%s AND is_active",
        (slot_id, loan["copy_id"]),
    ).fetchone() is None:
        raise ValueError("Das aktive Abholzeitfenster muss zu diesem Buch gehören.")
    start, end = _instant(data["start_at"]), _instant(data["end_at"])
    if start.astimezone(UTC) <= datetime.now(UTC) or end.astimezone(UTC) <= start.astimezone(UTC):
        raise ValueError("Bitte einen künftigen Abholtermin mit Ende nach Beginn auswählen.")
    return slot_id, start, end


def register_routes(app, connection_factory, require_user, require_csrf):
    """Register routes once; no global credentials or connections are retained."""

    @app.get("/api/meta")
    def meta():
        with connection_factory() as conn:
            genres = conn.execute("SELECT genre_id,name FROM bookbridge.genres ORDER BY name").fetchall()
            languages = conn.execute("SELECT language_id,code,name FROM bookbridge.languages ORDER BY name").fetchall()
        return jsonify(_json_value({"genres": genres, "languages": languages}))

    @app.get("/api/catalog")
    def catalog():
        page = _integer(request.args.get("page", "1"), "Seite", maximum=1000000)
        filters, parameters = ["c.is_active AND u.is_active"], []
        query = _text(request.args.get("query", ""), "Suchbegriff", 200)
        if query:
            # Treat search text literally, including SQL LIKE metacharacters.
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            filters.append("(b.title ILIKE %s OR b.isbn ILIKE %s OR EXISTS("
                           "SELECT 1 FROM bookbridge.book_authors ba JOIN bookbridge.authors au USING(author_id) "
                           "WHERE ba.book_id=b.book_id AND au.display_name ILIKE %s))")
            parameters.extend([pattern] * 3)
        for key in ("genre_id", "language_id"):
            if request.args.get(key):
                filters.append(f"b.{key}=%s")
                parameters.append(_integer(request.args[key], key))
        city = _text(request.args.get("city", ""), "Ort", 100)
        if city:
            filters.append("(lower(ad.city)=lower(%s) OR ad.postal_code=%s)")
            parameters.extend((city, city))
        available = request.args.get("available_only", "true").lower()
        if available not in ("true", "false"):
            raise ValueError("Verfügbarkeitsfilter: Bitte true oder false angeben.")
        if available == "true":
            filters.append("NOT EXISTS(SELECT 1 FROM bookbridge.loans open_loan WHERE "
                           "open_loan.copy_id=c.copy_id AND open_loan.status IN ('accepted','outbound','active','returning'))")
        radius = request.args.get("radius", "")
        lat_raw, lon_raw = request.args.get("latitude", ""), request.args.get("longitude", "")
        distance, origin = "", []
        if radius or lat_raw or lon_raw:
            if not (radius and lat_raw and lon_raw):
                raise ValueError("Für die Umkreissuche bitte Radius, Breitengrad und Längengrad gemeinsam angeben.")
            try:
                distance_limit, lat, lon = float(radius), float(lat_raw), float(lon_raw)
            except (ValueError, TypeError):
                raise ValueError("Radius und Koordinaten müssen gültige Zahlen sein.") from None
            if not all(math.isfinite(x) for x in (distance_limit, lat, lon)) or not (
                0 < distance_limit <= 20000 and -90 <= lat <= 90 and -180 <= lon <= 180
            ):
                raise ValueError("Radius (0–20000 km) oder Koordinaten liegen außerhalb des gültigen Bereichs.")
            distance = ", 6371.0088 * 2 * asin(sqrt(least(1.0,greatest(0.0," \
                "power(sin(radians(ad.latitude::double precision-%s)/2),2)+" \
                "cos(radians(%s))*cos(radians(ad.latitude::double precision))*" \
                "power(sin(radians(ad.longitude::double precision-%s)/2),2))))) AS distance_km"
            origin = [lat, lat, lon]
            filters.append("ad.latitude IS NOT NULL AND ad.longitude IS NOT NULL")
        base = CATALOG_SELECT.format(distance=distance) + " WHERE " + " AND ".join(filters)
        outer_where = " WHERE distance_km<=%s" if radius else ""
        values = origin + parameters + ([distance_limit] if radius else [])
        order = "distance_km,copy_id" if radius else "copy_id"
        with connection_factory() as conn:
            total = conn.execute("WITH catalog AS (" + base + ") SELECT count(*) AS n FROM catalog" + outer_where, values).fetchone()["n"]
            rows = conn.execute("WITH catalog AS (" + base + ") SELECT * FROM catalog" + outer_where
                                + " ORDER BY " + order + " LIMIT %s OFFSET %s",
                                values + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        return jsonify(_json_value({"items": [_catalog_item(row) for row in rows], "total": total,
                                    "page": page, "page_size": PAGE_SIZE}))

    @app.get("/api/catalog/<int:copy_id>")
    def catalog_detail(copy_id):
        with connection_factory() as conn:
            row = conn.execute(CATALOG_SELECT.format(distance="")
                               + " WHERE c.copy_id=%s AND c.is_active AND u.is_active", (copy_id,)).fetchone()
            if row is None:
                raise LookupError("Das Angebot wurde nicht gefunden oder ist deaktiviert.")
            slots = _slots(conn, [copy_id]).get(copy_id, [])
            reviews = conn.execute(
                "SELECT r.rating,r.comment,u.first_name FROM bookbridge.reviews r "
                "JOIN bookbridge.loans l USING(loan_id) JOIN bookbridge.users u ON u.user_id=r.reviewer_id "
                "WHERE l.copy_id=%s ORDER BY r.created_at DESC,r.review_id DESC LIMIT 50", (copy_id,),
            ).fetchall()
        return jsonify(_json_value({"item": _catalog_item(row), "pickup_slots": slots, "reviews": reviews}))

    @app.get("/api/my-books")
    def my_books():
        user = require_user()
        with connection_factory() as conn:
            rows = conn.execute(CATALOG_SELECT.format(distance=",c.pickup_address_id AS address_id")
                                + " WHERE c.owner_id=%s ORDER BY c.created_at DESC,c.copy_id DESC",
                                (user["user_id"],)).fetchall()
            slots = _slots(conn, [row["copy_id"] for row in rows])
            items = [_catalog_item(row) for row in rows]
            for item in items:
                item["pickup_slots"] = slots.get(item["copy_id"], [])
        return jsonify(_json_value({"items": items}))

    @app.post("/api/books")
    def create_book():
        user = require_user()
        require_csrf()
        _active(user)
        data = _body({"title", "author", "publisher", "publication_year", "isbn", "genre_id", "language_id",
                      "condition", "max_loan_days", "address_id", "allow_pickup", "allow_shipping", "notes",
                      "description", "pickup_slots"},
                     {"title", "author", "genre_id", "language_id", "condition", "max_loan_days", "address_id",
                      "allow_pickup", "allow_shipping"})
        title, author = _text(data["title"], "Titel", 200, True), _text(data["author"], "Autor", 150, True)
        publisher = _text(data.get("publisher"), "Verlag", 150)
        description, notes = _text(data.get("description"), "Beschreibung", 10000), _text(data.get("notes"), "Hinweise", 5000)
        genre_id = _integer(data["genre_id"], "Genre")
        language_id = _integer(data["language_id"], "Sprache")
        address_id = _integer(data["address_id"], "Anschrift")
        days = _integer(data["max_loan_days"], "Maximale Leihdauer", maximum=90)
        condition = _choice(data["condition"], CONDITIONS, "Zustand")
        pickup = _boolean(data["allow_pickup"], "Abholung")
        shipping = _boolean(data["allow_shipping"], "Versand")
        if not (pickup or shipping):
            raise ValueError("Bitte mindestens Abholung oder Versand anbieten.")
        year = None if data.get("publication_year") in (None, "") else _integer(
            data["publication_year"], "Erscheinungsjahr", 1450, 2100)
        raw_isbn = _text(data.get("isbn"), "ISBN", 40)
        isbn = re.sub(r"[\s-]", "", raw_isbn).upper() if raw_isbn else None
        if isbn and not re.fullmatch(r"(?:\d{9}[\dX]|97[89]\d{10})", isbn):
            raise ValueError("Bitte eine gültige ISBN-10 oder ISBN-13 angeben.")
        slots = _pickup_slots(data.get("pickup_slots", []))
        if pickup and not slots:
            raise ValueError("Für ein Abholangebot ist mindestens ein wöchentliches Zeitfenster erforderlich.")
        with connection_factory() as conn:
            address = conn.execute("SELECT latitude,longitude FROM bookbridge.addresses "
                                   "WHERE address_id=%s AND user_id=%s", (address_id, user["user_id"])).fetchone()
            if address is None:
                raise PermissionError("Bitte eine eigene gespeicherte Anschrift auswählen.")
            if address["latitude"] is None or address["longitude"] is None:
                raise ValueError("Für ein aktives Angebot benötigt die eigene Anschrift Breiten- und Längengrad. "
                                 "Bitte diese Angaben zuerst unter Mein Konto ergänzen bzw. eine vollständige Anschrift anlegen.")
            reused = False
            book_id = _existing_book(conn, data, isbn, title, author, genre_id, language_id) if isbn else None
            if book_id is not None:
                reused = True
            else:
                publisher_id = None
                if publisher:
                    conn.execute("INSERT INTO bookbridge.publishers(name) VALUES(%s) ON CONFLICT(name) DO NOTHING", (publisher,))
                    publisher_id = conn.execute("SELECT publisher_id FROM bookbridge.publishers WHERE name=%s", (publisher,)).fetchone()["publisher_id"]
                book_id = conn.execute(
                    "INSERT INTO bookbridge.books(title,isbn,publisher_id,publication_year,genre_id,language_id,description) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING book_id",
                    (title, isbn, publisher_id, year, genre_id, language_id, description),
                ).fetchone()["book_id"]
                author_row = conn.execute("SELECT author_id FROM bookbridge.authors WHERE display_name=%s ORDER BY author_id LIMIT 1", (author,)).fetchone()
                author_id = author_row["author_id"] if author_row else conn.execute(
                    "INSERT INTO bookbridge.authors(display_name) VALUES(%s) RETURNING author_id", (author,),
                ).fetchone()["author_id"]
                conn.execute("INSERT INTO bookbridge.book_authors(book_id,author_id,author_order) VALUES(%s,%s,1)", (book_id, author_id))
            copy_id = conn.execute(
                "INSERT INTO bookbridge.book_copies(book_id,owner_id,pickup_address_id,condition,max_loan_days,"
                "allow_pickup,allow_shipping,is_active,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,false,%s) RETURNING copy_id",
                (book_id, user["user_id"], address_id, condition, days, pickup, shipping, notes),
            ).fetchone()["copy_id"]
            for weekday, start, end in slots:
                conn.execute("INSERT INTO bookbridge.pickup_slots(copy_id,weekday,start_time,end_time) VALUES(%s,%s,%s,%s)",
                             (copy_id, weekday, start, end))
            conn.execute("SELECT bookbridge.set_offer_active(%s,%s,true)", (user["user_id"], copy_id))
        result = {"copy_id": copy_id}
        if reused:
            result["message"] = "Die vorhandenen bibliografischen Daten dieser ISBN wurden unverändert für Ihr eigenes Exemplar verwendet."
        return jsonify(result), 201

    @app.patch("/api/books/<int:copy_id>")
    def edit_book(copy_id):
        user = require_user()
        require_csrf()
        data = _body({"condition", "max_loan_days", "notes", "is_active", "address_id", "allow_pickup",
                      "allow_shipping", "pickup_slots"})
        if not data:
            raise ValueError("Bitte mindestens eine Änderung angeben.")
        updates, values = [], []
        if "condition" in data:
            updates.append("condition=%s")
            values.append(_choice(data["condition"], CONDITIONS, "Zustand"))
        if "max_loan_days" in data:
            updates.append("max_loan_days=%s")
            values.append(_integer(data["max_loan_days"], "Maximale Leihdauer", maximum=90))
        if "notes" in data:
            updates.append("notes=%s")
            values.append(_text(data["notes"], "Hinweise", 5000))
        for key, label in (("allow_pickup", "Abholung"), ("allow_shipping", "Versand")):
            if key in data:
                updates.append(key + "=%s")
                values.append(_boolean(data[key], label))
        address_id = _integer(data["address_id"], "Anschrift") if "address_id" in data else None
        if address_id is not None:
            updates.append("pickup_address_id=%s")
            values.append(address_id)
        slots = _pickup_slots(data["pickup_slots"]) if "pickup_slots" in data else None
        active = _boolean(data["is_active"], "Aktivierung") if "is_active" in data else None
        with connection_factory() as conn:
            copy = conn.execute("SELECT owner_id,allow_pickup,allow_shipping,is_active FROM bookbridge.book_copies "
                                "WHERE copy_id=%s FOR UPDATE", (copy_id,)).fetchone()
            if copy is None:
                raise LookupError("Das eigene Angebot wurde nicht gefunden.")
            if copy["owner_id"] != user["user_id"]:
                raise PermissionError("Sie dürfen nur Ihre eigenen Angebote bearbeiten.")
            pickup, shipping = data.get("allow_pickup", copy["allow_pickup"]), data.get("allow_shipping", copy["allow_shipping"])
            if not (pickup or shipping):
                raise ValueError("Bitte mindestens Abholung oder Versand anbieten.")
            if pickup:
                has_slots = bool(slots) if slots is not None else conn.execute(
                    "SELECT 1 FROM bookbridge.pickup_slots WHERE copy_id=%s AND is_active LIMIT 1", (copy_id,),
                ).fetchone() is not None
                if not has_slots:
                    raise ValueError("Für ein Abholangebot ist mindestens ein wöchentliches Zeitfenster erforderlich.")
            if address_id is not None:
                address = conn.execute("SELECT latitude,longitude FROM bookbridge.addresses "
                                       "WHERE address_id=%s AND user_id=%s FOR SHARE", (address_id, user["user_id"])).fetchone()
                if address is None:
                    raise PermissionError("Bitte eine eigene gespeicherte Anschrift auswählen.")
                if (copy["is_active"] if active is None else active) and (address["latitude"] is None or address["longitude"] is None):
                    raise ValueError("Für ein aktives Angebot benötigt die eigene Anschrift Breiten- und Längengrad.")
            if active is False:
                # Pause before changing a location whose coordinates may be
                # absent; the immediate copy guard sees the intended state.
                conn.execute("SELECT bookbridge.set_offer_active(%s,%s,false)", (user["user_id"], copy_id))
            if updates:
                conn.execute("UPDATE bookbridge.book_copies SET " + ",".join(updates) + " WHERE copy_id=%s", values + [copy_id])
            if slots is not None:
                # Keep old slot IDs and times for accepted loans; only the live
                # weekly plan is replaced within this copy-locked transaction.
                conn.execute("UPDATE bookbridge.pickup_slots SET is_active=false WHERE copy_id=%s AND is_active", (copy_id,))
                for weekday, start, end in slots:
                    conn.execute("INSERT INTO bookbridge.pickup_slots(copy_id,weekday,start_time,end_time) VALUES(%s,%s,%s,%s)",
                                 (copy_id, weekday, start, end))
            if active is True:
                conn.execute("SELECT bookbridge.set_offer_active(%s,%s,%s)", (user["user_id"], copy_id, active))
        return jsonify({"copy_id": copy_id})

    @app.get("/api/loans")
    def loans():
        user = require_user()
        actor = user["user_id"]
        with connection_factory() as conn:
            rows = conn.execute(
                "SELECT l.*,b.title,c.owner_id,c.max_loan_days,owner_u.first_name||' '||owner_u.last_name AS owner_name,"
                "borrower_u.first_name||' '||borrower_u.last_name AS borrower_name "
                "FROM bookbridge.loans l JOIN bookbridge.book_copies c USING(copy_id) "
                "JOIN bookbridge.books b USING(book_id) JOIN bookbridge.users owner_u ON owner_u.user_id=c.owner_id "
                "JOIN bookbridge.users borrower_u ON borrower_u.user_id=l.borrower_id "
                "WHERE c.owner_id=%s OR l.borrower_id=%s ORDER BY l.requested_at DESC,l.loan_id DESC", (actor, actor),
            ).fetchall()
            items = [dict(row) for row in rows]
            by_id = {item["loan_id"]: item for item in items}
            slots = _slots(conn, {item["copy_id"] for item in items})
            for item in items:
                item["role"] = "owner" if item["owner_id"] == actor else "borrower"
                item["pickup_slots"] = slots.get(item["copy_id"], [])
                for key in ("proposals", "extensions", "payments", "shipments", "reviews", "documents"):
                    item[key] = []
                item["sender_addresses"], item["recipient_addresses"] = [], []
                if item["accepted_at"] is None:
                    item["pickup_address_snapshot"] = None
            ids = list(by_id)
            if ids:
                for key, table, order in (
                    ("proposals", "loan_proposals", "proposal_id"), ("extensions", "loan_extensions", "extension_id"),
                    ("payments", "payments", "payment_id"), ("shipments", "shipments", "shipment_id"),
                    ("reviews", "reviews", "review_id"),
                ):
                    children = conn.execute(f"SELECT * FROM bookbridge.{table} WHERE loan_id=ANY(%s) ORDER BY {order}", (ids,)).fetchall()
                    for child in children:
                        by_id[child["loan_id"]][key].append(dict(child))
                documents = conn.execute(
                    "SELECT document_id,loan_id,shipment_id,recipient_user_id,document_type,status,created_at,generated_at "
                    "FROM bookbridge.generated_documents WHERE loan_id=ANY(%s) AND recipient_user_id=%s ORDER BY document_id", (ids, actor),
                ).fetchall()
                for document in documents:
                    document = dict(document)
                    document["download_url"] = f"/api/documents/{document['document_id']}/download"
                    by_id[document["loan_id"]]["documents"].append(document)
                shipping = [item for item in items if item["handover_mode"] == "shipping"
                            and item["accepted_at"] is not None and item["status"] in SHARED_ADDRESS_STATES]
                participant_ids = {actor} if shipping else set()
                for item in shipping:
                    participant_ids.update((item["owner_id"], item["borrower_id"]))
                addresses = {}
                if participant_ids:
                    # Coordinates and email are unnecessary for parcel preparation.
                    address_rows = conn.execute(
                        "SELECT address_id,user_id,street,postal_code,city,country_code FROM bookbridge.addresses "
                        "WHERE user_id=ANY(%s) ORDER BY address_id", (list(participant_ids),),
                    ).fetchall()
                    for address in address_rows:
                        address = dict(address)
                        addresses.setdefault(address.pop("user_id"), []).append(address)
                for item in shipping:
                    other = item["borrower_id"] if item["owner_id"] == actor else item["owner_id"]
                    item["sender_addresses"] = addresses.get(actor, [])
                    item["recipient_addresses"] = addresses.get(other, [])
        return jsonify(_json_value({"items": items}))

    @app.post("/api/loans")
    def create_loan():
        user = require_user()
        require_csrf()
        _active(user)
        data = _body({"copy_id", "days", "mode"}, {"copy_id", "days", "mode"})
        copy_id = _integer(data["copy_id"], "Buch-ID")
        days = _integer(data["days"], "Leihdauer", maximum=90)
        mode = _choice(data["mode"], {"pickup", "shipping"}, "Übergabeart")
        with connection_factory() as conn:
            loan_id = conn.execute("SELECT bookbridge.create_request(%s,%s,%s,%s) AS id",
                                   (user["user_id"], copy_id, days, mode)).fetchone()["id"]
        return jsonify({"loan_id": loan_id}), 201

    @app.post("/api/loans/<int:loan_id>/actions")
    def loan_action(loan_id):
        user = require_user()
        require_csrf()
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("action"), str):
            raise ValueError("Bitte eine gültige Aktion angeben.")
        action = data["action"]
        definitions = {
            "accept": ({"slot_id", "start_at", "end_at"}, set()),
            "reject": (set(), set()), "cancel": (set(), set()), "receive_pickup": (set(), set()),
            "start_return": (set(), set()), "confirm_return": (set(), set()),
            "propose": ({"days"}, {"days"}),
            "decide_proposal": ({"proposal_id", "decision", "slot_id", "start_at", "end_at"}, {"proposal_id", "decision"}),
            "request_extension": ({"days"}, {"days"}),
            "decide_extension": ({"extension_id", "decision"}, {"extension_id", "decision"}),
            "create_postage": ({"outbound_fee", "return_fee"}, {"outbound_fee", "return_fee"}),
            "report_postage": ({"payment_id"}, {"payment_id"}), "confirm_postage": ({"payment_id"}, {"payment_id"}),
            "prepare_shipment": ({"direction", "sender_address_id", "recipient_address_id", "carrier", "tracking_number"},
                                 {"direction", "sender_address_id", "recipient_address_id"}),
            "send_shipment": ({"shipment_id"}, {"shipment_id"}), "receive_shipment": ({"shipment_id"}, {"shipment_id"}),
            "review": ({"rating", "comment"}, {"rating"}),
        }
        if action not in definitions:
            raise ValueError("Diese Aktion wird nicht unterstützt.")
        allowed, required = definitions[action]
        _fields(data, allowed | {"action"}, required | {"action"})
        if action in ("accept", "propose") or (action == "decide_proposal" and data.get("decision") == "accepted"):
            _active(user)
        actor = user["user_id"]
        with connection_factory() as conn:
            # Phase 2 functions acquire the authoritative parent/child row locks.
            # Participant identities and child loan references are immutable;
            # this read needs no direct UPDATE grant on workflow tables.
            loan = _participant_loan(conn, loan_id, actor)
            args = [actor, loan_id]
            simple = {"reject": "reject_request", "cancel": "cancel_request", "receive_pickup": "receive_pickup",
                      "start_return": "start_return", "confirm_return": "confirm_return"}
            if action in simple:
                function = simple[action]
            elif action == "accept":
                function = "accept_request"
                args.extend(_appointment(conn, data, loan))
            elif action in ("propose", "request_extension"):
                function = "propose_days" if action == "propose" else "request_extension"
                args.append(_integer(data["days"], "Tage", maximum=90))
            elif action == "decide_proposal":
                function = "decide_proposal"
                proposal_id = _child(conn, "loan_proposals", "proposal_id", data["proposal_id"], loan_id)
                decision = _choice(data["decision"], {"accepted", "rejected", "withdrawn"}, "Entscheidung")
                args = [actor, proposal_id, decision]
                if decision == "accepted":
                    args.extend(_appointment(conn, data, loan))
                elif any(data.get(key) is not None for key in ("slot_id", "start_at", "end_at")):
                    raise ValueError("Bei einer Ablehnung oder Rücknahme ist kein Abholtermin zulässig.")
            elif action == "decide_extension":
                function = "decide_extension"
                args = [actor, _child(conn, "loan_extensions", "extension_id", data["extension_id"], loan_id),
                        _choice(data["decision"], {"approved", "rejected", "withdrawn"}, "Entscheidung")]
            elif action == "create_postage":
                function = "create_postage"
                args.extend((_money(data["outbound_fee"], "Hinporto"), _money(data["return_fee"], "Rückporto")))
            elif action in ("report_postage", "confirm_postage"):
                function = action
                args = [actor, _child(conn, "payments", "payment_id", data["payment_id"], loan_id)]
            elif action == "prepare_shipment":
                function = "prepare_shipment"
                args.extend((_choice(data["direction"], {"outbound", "return"}, "Versandrichtung"),
                             _integer(data["sender_address_id"], "Absenderanschrift"),
                             _integer(data["recipient_address_id"], "Empfängeranschrift"),
                             _text(data.get("carrier"), "Versandunternehmen", 80),
                             _text(data.get("tracking_number"), "Sendungsnummer", 120)))
            elif action in ("send_shipment", "receive_shipment"):
                function = action
                args = [actor, _child(conn, "shipments", "shipment_id", data["shipment_id"], loan_id)]
            else:
                function = "review_loan"
                args.extend((_integer(data["rating"], "Bewertung", 1, 5), _text(data.get("comment"), "Kommentar", 5000)))
            # Function name is never read from the HTTP body; event time defaults
            # to PostgreSQL CURRENT_TIMESTAMP. Every argument is parameterized.
            placeholders = ",".join(["%s"] * len(args))
            result = conn.execute(f"SELECT bookbridge.{function}({placeholders}) AS id", args).fetchone()["id"]
        return jsonify({"id": result})
