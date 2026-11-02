"""Real PostgreSQL integration tests. No simulated results or external services.

Run after sql/01..04 against a dedicated project database. Ordinary tests roll
back their fixtures. The race test requires a disposable *different database*
via --concurrency-dsn; committed race fixtures remain only in that test clone.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

# Keep Windows console and subprocess evidence consistently UTF-8.
for output_stream in (sys.stdout, sys.stderr):
    if hasattr(output_stream, 'reconfigure'):
        output_stream.reconfigure(encoding='utf-8', errors='backslashreplace')
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

for library in [os.environ.get("BOOKBRIDGE_PYTHON_LIB"), str(Path(__file__).resolve().parents[1] / ".runtime" / "python")]:
    if library and Path(library).exists():
        sys.path.insert(0, library)
try:
    import psycopg
except ImportError as exc:
    raise SystemExit("psycopg 3 required. Set BOOKBRIDGE_PYTHON_LIB or install requirements.txt.") from exc

TABLES = ["users", "addresses", "publishers", "genres", "languages", "authors", "books", "book_authors", "book_copies", "pickup_slots", "loans", "loan_proposals", "loan_extensions", "payments", "shipments", "notifications", "generated_documents", "reviews"]
REQUEST = "2026-10-20 09:00:00+02"
ACCEPT = "2026-10-21 09:00:00+02"
START = "2026-10-26 18:15:00+01"
END = "2026-10-26 18:45:00+01"
RECEIVE = "2026-10-26 18:20:00+01"
JOIN_QUERIES = {
    "Q01_copy_book_owner": "SELECT c.copy_id,b.title,u.first_name||' '||u.last_name AS owner,c.condition,c.max_loan_days FROM bookbridge.book_copies c JOIN bookbridge.books b ON b.book_id=c.book_id JOIN bookbridge.users u ON u.user_id=c.owner_id ORDER BY c.copy_id",
    "Q02_loan_copy_borrower": "SELECT l.loan_id,c.copy_id,u.first_name||' '||u.last_name AS borrower,l.handover_mode,l.status,l.due_date FROM bookbridge.loans l JOIN bookbridge.book_copies c ON c.copy_id=l.copy_id JOIN bookbridge.users u ON u.user_id=l.borrower_id ORDER BY l.loan_id",
    "Q03_payment_loan_confirmer": "SELECT p.payment_id,l.loan_id,l.status AS loan_status,p.status AS payment_status,p.outbound_fee+p.return_fee AS total_eur,u.first_name||' '||u.last_name AS confirmed_by,p.confirmed_at FROM bookbridge.payments p JOIN bookbridge.loans l ON l.loan_id=p.loan_id LEFT JOIN bookbridge.users u ON u.user_id=p.confirmed_by_user_id ORDER BY p.payment_id",
}


def connect(dsn):
    connection = psycopg.connect(dsn, autocommit=True)
    connection.execute("SET search_path=bookbridge,public")
    connection.execute("SET TIME ZONE 'Europe/Berlin'")
    connection.execute("SET statement_timeout='15s'")
    return connection


def scalar(c, query, params=None):
    return c.execute(query, params).fetchone()[0]


def call(c, name, *args):
    # Function names are constants in this source, never user input.
    args = tuple(Decimal(str(value)) if isinstance(value, float) else value for value in args)
    return scalar(c, f"SELECT bookbridge.{name}({','.join(['%s'] * len(args))})", args)


def eq(actual, expected, message=""):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def truth(condition, message):
    if not condition:
        raise AssertionError(message)


def rejected(c, action, reason):
    try:
        with c.transaction():
            action()
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
    except psycopg.Error as exc:
        # Missing objects, syntax bugs and connection errors must fail the test.
        if exc.sqlstate not in {"P0001", "23514", "23505", "23503", "23502", "23P01", "42501", "55000", "22023", "22003", "22007", "22008"}:
            raise
        return exc.sqlstate
    raise AssertionError("Forbidden operation was accepted: " + reason)


def fixture(c, mode="pickup", days=14, maximum=42, accept=False, receive=False):
    copy_id = scalar(c, "INSERT INTO bookbridge.book_copies(book_id,owner_id,pickup_address_id,condition,max_loan_days,allow_pickup,allow_shipping,is_active,created_at) VALUES(1,1,1,'good',%s,true,true,false,'2026-01-01+01') RETURNING copy_id", (maximum,))
    slot = scalar(c, "INSERT INTO bookbridge.pickup_slots(copy_id,weekday,start_time,end_time) VALUES(%s,1,'18:00','20:00') RETURNING slot_id", (copy_id,))
    c.execute("UPDATE bookbridge.book_copies SET is_active=true WHERE copy_id=%s", (copy_id,))
    loan = call(c, "create_request", 2, copy_id, days, mode, REQUEST)
    f = {"copy": copy_id, "slot": slot, "loan": loan, "owner": 1, "borrower": 2}
    if accept:
        accept_fixture(c, f, mode)
    if receive:
        if mode == "pickup":
            call(c, "receive_pickup", 2, loan, RECEIVE)
        else:
            payment = call(c, "create_postage", 1, loan, 2.90, 3.20, "2026-10-21 10:00+02")
            call(c, "report_postage", 2, payment, "2026-10-21 11:00+02")
            call(c, "confirm_postage", 1, payment, "2026-10-21 12:00+02")
            shipment = call(c, "prepare_shipment", 1, loan, "outbound", 1, 2, "DHL Demo", "TEST-H", "2026-10-21 13:00+02")
            call(c, "send_shipment", 1, shipment, "2026-10-22 10:00+02")
            call(c, "receive_shipment", 2, shipment, RECEIVE)
            f.update(payment=payment, outbound=shipment)
    return f


def accept_fixture(c, f, mode="pickup"):
    return call(c, "accept_request", 1, f["loan"], f["slot"] if mode == "pickup" else None, START if mode == "pickup" else None, END if mode == "pickup" else None, ACCEPT)


def finish_pickup(c, f):
    call(c, "start_return", 2, f["loan"], "2026-10-27 16:00+01")
    call(c, "confirm_return", 1, f["loan"], "2026-10-27 18:00+01")


def loan_row(c, loan):
    row = c.execute("SELECT status,due_date,received_at,return_started_at,completed_at FROM bookbridge.loans WHERE loan_id=%s", (loan,)).fetchone()
    return row


def t_catalog(c):
    truth(scalar(c, "SELECT bookbridge.isbn_valid('9783522202756')"), "Valid ISBN-13 rejected")
    truth(scalar(c, "SELECT bookbridge.isbn_valid('0306406152')"), "Valid ISBN-10 rejected")
    truth(not scalar(c, "SELECT bookbridge.isbn_valid('9783522202757')"), "Wrong checksum accepted")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.books(title,isbn,genre_id,language_id) VALUES('Fehlerhafte ISBN','9783522202757',1,1)"), "ISBN checksum")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.users(first_name,last_name,email,password_hash) VALUES('X','Y','MITGLIED01@bookbridge.test','demo')"), "Case insensitive email")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.books(title,genre_id,language_id) VALUES('Ohne Autor',1,1)"), "Deferred minimum author")
    book = scalar(c, "INSERT INTO bookbridge.books(title,genre_id,language_id) VALUES('Positiver Autorentest',1,1) RETURNING book_id")
    c.execute("INSERT INTO bookbridge.book_authors VALUES(%s,1,1)", (book,))
    c.execute("SET CONSTRAINTS ALL IMMEDIATE")


def t_location(c):
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.addresses(user_id,street,postal_code,city,latitude) VALUES(1,'Test 1','40213','Düsseldorf',51.2)"), "Incomplete coordinate pair")
    rejected(c, lambda: c.execute("UPDATE bookbridge.addresses SET latitude=91 WHERE address_id=1"), "Coordinate range")
    rejected(c, lambda: c.execute("UPDATE bookbridge.addresses SET country_code='d1' WHERE address_id=1"), "ISO country shape")
    f = fixture(c)
    rejected(c, lambda: c.execute("UPDATE bookbridge.book_copies SET pickup_address_id=2 WHERE copy_id=%s", (f["copy"],)), "Foreign owner address")
    rejected(c, lambda: c.execute("UPDATE bookbridge.addresses SET latitude=NULL,longitude=NULL WHERE address_id=1"), "Active copies need geocoordinates")
    rejected(c, lambda: c.execute("UPDATE bookbridge.pickup_slots SET is_active=false WHERE slot_id=%s", (f["slot"],)), "Active pickup requires a slot")


def t_ownership(c):
    f = fixture(c)
    rejected(c, lambda: c.execute("UPDATE bookbridge.book_copies SET owner_id=2 WHERE copy_id=%s", (f["copy"],)), "Copy ownership immutable")
    rejected(c, lambda: c.execute("UPDATE bookbridge.book_copies SET book_id=2 WHERE copy_id=%s", (f["copy"],)), "Bibliographic identity immutable")
    rejected(c, lambda: c.execute("UPDATE bookbridge.addresses SET user_id=2 WHERE address_id=1"), "Address ownership immutable")
    rejected(c, lambda: c.execute("DELETE FROM bookbridge.book_copies WHERE copy_id=%s", (f["copy"],)), "Referenced copy retained")


def t_roles_requests(c):
    f = fixture(c)
    rejected(c, lambda: call(c, "create_request", 1, f["copy"], 14, "pickup", REQUEST), "Self lending")
    rejected(c, lambda: call(c, "create_request", 2, f["copy"], 43, "pickup", REQUEST), "Request beyond current maximum")
    rejected(c, lambda: call(c, "accept_request", 24, f["loan"], f["slot"], START, END, ACCEPT), "Admin cannot impersonate owner")
    other = call(c, "create_request", 3, f["copy"], 14, "pickup", REQUEST)
    eq(scalar(c, "SELECT count(*) FROM bookbridge.loans WHERE copy_id=%s AND status='requested'", (f["copy"],)), 2, "Requested loans do not reserve")
    accept_fixture(c, f)
    rejected(c, lambda: call(c, "accept_request", 1, other, f["slot"], START, END, ACCEPT), "Second binding loan")
    eq(scalar(c, "SELECT count(*) FROM bookbridge.loans WHERE copy_id=%s AND status IN ('accepted','outbound','active','returning')", (f["copy"],)), 1)


def t_pickup(c):
    f = fixture(c)
    rejected(c, lambda: call(c, "accept_request", 1, f["loan"], 2, START, END, ACCEPT), "Slot from another copy")
    rejected(c, lambda: call(c, "accept_request", 1, f["loan"], f["slot"], "2026-10-27 18:15+01", "2026-10-27 18:45+01", ACCEPT), "Wrong weekday")
    rejected(c, lambda: call(c, "accept_request", 1, f["loan"], f["slot"], "2026-10-26 17:00+01", END, ACCEPT), "Outside weekly window")
    rejected(c, lambda: call(c, "accept_request", 1, f["loan"], f["slot"], START, END, "2026-10-26 19:00+01"), "Agreement after appointment")
    accept_fixture(c, f)
    before = c.execute("SELECT pickup_address_snapshot,pickup_start_at,pickup_end_at,max_loan_days_snapshot FROM bookbridge.loans WHERE loan_id=%s", (f["loan"],)).fetchone()
    c.execute("UPDATE bookbridge.addresses SET street='Geänderter Beispielweg 123' WHERE address_id=1")
    c.execute("UPDATE bookbridge.pickup_slots SET start_time='19:00',end_time='21:00' WHERE slot_id=%s", (f["slot"],))
    c.execute("UPDATE bookbridge.book_copies SET max_loan_days=21 WHERE copy_id=%s", (f["copy"],))
    eq(c.execute("SELECT pickup_address_snapshot,pickup_start_at,pickup_end_at,max_loan_days_snapshot FROM bookbridge.loans WHERE loan_id=%s", (f["loan"],)).fetchone(), before, "Historical acceptance snapshot")


def t_proposals(c):
    f = fixture(c)
    rejected(c, lambda: call(c, "propose_days", 2, f["loan"], 21, "2026-10-20 10:00+02"), "Only owner proposes")
    proposal = call(c, "propose_days", 1, f["loan"], 21, "2026-10-20 10:00+02")
    rejected(c, lambda: call(c, "propose_days", 1, f["loan"], 20, "2026-10-20 11:00+02"), "One pending proposal")
    rejected(c, lambda: accept_fixture(c, f), "Direct acceptance while pending")
    rejected(c, lambda: call(c, "decide_proposal", 1, proposal, "accepted", f["slot"], START, END, ACCEPT), "Only borrower accepts alternative")
    call(c, "decide_proposal", 2, proposal, "rejected", None, None, None, "2026-10-20 12:00+02")
    eq(loan_row(c, f["loan"])[0], "requested")
    rejected(c, lambda: call(c, "propose_days", 1, f["loan"], 21, "2026-10-20 11:00+02"), "New event before previous child decision")
    proposal = call(c, "propose_days", 1, f["loan"], 21, "2026-10-20 13:00+02")
    call(c, "decide_proposal", 2, proposal, "accepted", f["slot"], START, END, ACCEPT)
    eq(scalar(c, "SELECT agreed_days FROM bookbridge.loans WHERE loan_id=%s", (f["loan"],)), 21)
    eq(loan_row(c, f["loan"])[0], "accepted")


def t_extension(c):
    f = fixture(c, maximum=21, accept=True, receive=True)
    rejected(c, lambda: call(c, "request_extension", 1, f["loan"], 7, "2026-10-27 09:00+01"), "Borrower requests extension")
    ext = call(c, "request_extension", 2, f["loan"], 7, "2026-10-27 09:00+01")
    rejected(c, lambda: call(c, "request_extension", 2, f["loan"], 1, "2026-10-27 09:01+01"), "One pending extension")
    rejected(c, lambda: call(c, "decide_extension", 2, ext, "approved", "2026-10-27 10:00+01"), "Owner decides extension")
    old = loan_row(c, f["loan"])[1]
    call(c, "decide_extension", 1, ext, "approved", "2026-10-27 10:00+01")
    new = loan_row(c, f["loan"])[1]
    eq(new, old + dt.timedelta(days=7))
    call(c, "decide_extension", 1, ext, "approved", "2026-10-27 10:01+01")
    eq(loan_row(c, f["loan"])[1], new, "Idempotent extension approval")
    rejected(c, lambda: call(c, "request_extension", 2, f["loan"], 1, "2026-10-27 11:00+01"), "Frozen total maximum")
    rejected(c, lambda: c.execute("UPDATE bookbridge.loan_extensions SET extra_days=1 WHERE extension_id=%s", (ext,)), "Approved extension immutable")


def t_early_return(c):
    f = fixture(c, accept=True, receive=True)
    ext = call(c, "request_extension", 2, f["loan"], 7, "2026-10-27 09:00+01")
    due = loan_row(c, f["loan"])[1]
    call(c, "start_return", 2, f["loan"], "2026-10-27 10:00+01")
    eq(scalar(c, "SELECT status FROM bookbridge.loan_extensions WHERE extension_id=%s", (ext,)), "withdrawn")
    rejected(c, lambda: call(c, "confirm_return", 2, f["loan"], "2026-10-27 11:00+01"), "Only owner confirms return")
    call(c, "confirm_return", 1, f["loan"], "2026-10-27 11:00+01")
    eq(loan_row(c, f["loan"])[0], "completed")
    truth(loan_row(c, f["loan"])[4].date() < due, "Early return must be allowed")
    completed = loan_row(c, f["loan"])[4]
    call(c, "confirm_return", 1, f["loan"], "2026-10-27 11:01+01")
    eq(loan_row(c, f["loan"])[4], completed, "Repeated completion cannot rewrite history")
    eq(scalar(c, "SELECT count(*) FROM bookbridge.loans WHERE copy_id=%s AND status IN ('accepted','outbound','active','returning')", (f["copy"],)), 0)


def t_late_return(c):
    f = fixture(c, days=1, accept=True, receive=True)
    due = loan_row(c, f["loan"])[1]
    call(c, "start_return", 2, f["loan"], "2026-11-02 10:00+01")
    call(c, "confirm_return", 1, f["loan"], "2026-11-03 10:00+01")
    truth(loan_row(c, f["loan"])[4].date() > due, "Late return must complete without inventing a new status")


def t_dst(c):
    for date, offset, nextdate in [("2026-03-29", "+01", dt.date(2026,4,12)), ("2026-10-25", "+02", dt.date(2026,11,8))]:
        f = fixture(c)
        # Reuse the requested fixture but put its timestamp before this special test event.
        # A new loan avoids any attempt to rewrite immutable request history.
        copy_id = f["copy"]
        sun = scalar(c, "INSERT INTO bookbridge.pickup_slots(copy_id,weekday,start_time,end_time) VALUES(%s,7,'00:00','04:00') RETURNING slot_id", (copy_id,))
        requested = date + " 00:00" + offset
        loan = call(c, "create_request", 3, copy_id, 14, "pickup", requested)
        call(c, "accept_request", 1, loan, sun, date+" 00:15"+offset, date+" 00:45"+offset, date+" 00:01"+offset)
        call(c, "receive_pickup", 3, loan, date+" 00:30"+offset)
        eq(loan_row(c, loan)[1], nextdate, "Berlin calendar date across DST")


def t_postage(c):
    pickup = fixture(c, accept=True)
    rejected(c, lambda: call(c, "create_postage", 1, pickup["loan"], 2.90, 2.90, "2026-10-21 10:00+02"), "No postage for pickup")
    f = fixture(c, mode="shipping", accept=True)
    rejected(c, lambda: call(c, "create_postage", 1, f["loan"], Decimal("NaN"), Decimal("3.20"), "2026-10-21 10:00+02"), "NaN is not a monetary amount")
    rejected(c, lambda: call(c, "create_postage", 1, f["loan"], Decimal("Infinity"), Decimal("3.20"), "2026-10-21 10:00+02"), "Infinity is not a monetary amount")
    payment = call(c, "create_postage", 1, f["loan"], 2.90, 3.20, "2026-10-21 10:00+02")
    ship = call(c, "prepare_shipment", 1, f["loan"], "outbound", 1, 2, "DHL Demo", "TEST-NOPAY", "2026-10-21 10:05+02")
    rejected(c, lambda: call(c, "send_shipment", 1, ship, "2026-10-21 10:10+02"), "Send without confirmed postage")
    rejected(c, lambda: call(c, "report_postage", 1, payment, "2026-10-21 10:15+02"), "Only borrower reports")
    call(c, "report_postage", 2, payment, "2026-10-21 10:15+02")
    rejected(c, lambda: call(c, "confirm_postage", 2, payment, "2026-10-21 10:20+02"), "Only owner confirms")
    call(c, "confirm_postage", 1, payment, "2026-10-21 10:20+02")
    rejected(c, lambda: c.execute("UPDATE bookbridge.payments SET outbound_fee=0 WHERE payment_id=%s", (payment,)), "Confirmed fee immutable")
    call(c, "send_shipment", 1, ship, "2026-10-22 10:00+02")
    eq(loan_row(c, f["loan"])[0], "outbound")
    rejected(c, lambda: call(c, "receive_shipment", 24, ship, RECEIVE), "Admin is not parcel recipient")
    call(c, "receive_shipment", 2, ship, RECEIVE)
    eq(loan_row(c, f["loan"])[0], "active")
    eq(scalar(c, "SELECT received_at FROM bookbridge.shipments WHERE shipment_id=%s", (ship,)), loan_row(c, f["loan"])[2], "Atomic matching receipt event")


def t_cancellation(c):
    for state in ("pending", "reported", "confirmed"):
        f = fixture(c, mode="shipping", accept=True)
        p = call(c, "create_postage", 1, f["loan"], 2.90, 3.20, "2026-10-21 10:00+02")
        if state in ("reported", "confirmed"):
            call(c, "report_postage", 2, p, "2026-10-21 11:00+02")
        if state == "confirmed":
            call(c, "confirm_postage", 1, p, "2026-10-21 12:00+02")
        call(c, "cancel_request", 2, f["loan"], "2026-10-21 13:00+02")
        eq(scalar(c, "SELECT status FROM bookbridge.payments WHERE payment_id=%s", (p,)), "confirmed" if state == "confirmed" else "cancelled")
        eq(loan_row(c, f["loan"])[0], "cancelled")
    f = fixture(c, mode="shipping", accept=True, receive=True)
    rejected(c, lambda: call(c, "cancel_request", 1, f["loan"], "2026-10-27 10:00+01"), "No cancellation after handover")
    f = fixture(c)
    proposal = call(c, "propose_days", 1, f["loan"], 21, "2026-10-20 10:00+02")
    call(c, "cancel_request", 2, f["loan"], "2026-10-20 11:00+02")
    eq(scalar(c, "SELECT status FROM bookbridge.loan_proposals WHERE proposal_id=%s", (proposal,)), "withdrawn")


def t_shipments(c):
    f = fixture(c, mode="shipping", accept=True, receive=True)
    rejected(c, lambda: call(c, "prepare_shipment", 1, f["loan"], "return", 1, 2, None, None, "2026-10-27 09:00+01"), "Return sender is borrower")
    rejected(c, lambda: call(c, "prepare_shipment", 2, f["loan"], "return", 3, 1, None, None, "2026-10-27 09:00+01"), "Sender address ownership")
    s = call(c, "prepare_shipment", 2, f["loan"], "return", 2, 1, "DHL Demo", "TEST-R", "2026-10-27 09:00+01")
    snapshot = scalar(c, "SELECT recipient_address_snapshot FROM bookbridge.shipments WHERE shipment_id=%s", (s,))
    c.execute("UPDATE bookbridge.addresses SET street='Neuer Testweg 90' WHERE address_id=1")
    eq(scalar(c, "SELECT recipient_address_snapshot FROM bookbridge.shipments WHERE shipment_id=%s", (s,)), snapshot)
    call(c, "send_shipment", 2, s, "2026-10-27 12:00+01")
    eq(loan_row(c, f["loan"])[0], "returning")
    eq(scalar(c, "SELECT sent_at FROM bookbridge.shipments WHERE shipment_id=%s", (s,)), loan_row(c, f["loan"])[3])
    rejected(c, lambda: call(c, "receive_shipment", 2, s, "2026-10-28 12:00+01"), "Borrower cannot confirm own return delivery")
    call(c, "receive_shipment", 1, s, "2026-10-28 12:00+01")
    eq(loan_row(c, f["loan"])[0], "completed")
    eq(scalar(c, "SELECT received_at FROM bookbridge.shipments WHERE shipment_id=%s", (s,)), loan_row(c, f["loan"])[4])
    completed = loan_row(c, f["loan"])[4]
    notification_count = scalar(c, "SELECT count(*) FROM bookbridge.notifications WHERE loan_id=%s", (f["loan"],))
    call(c, "receive_shipment", 1, s, "2026-10-28 13:00+01")
    eq(loan_row(c, f["loan"])[4], completed, "Repeated parcel receipt cannot rewrite completion")
    eq(scalar(c, "SELECT count(*) FROM bookbridge.notifications WHERE loan_id=%s", (f["loan"],)), notification_count, "No duplicate receipt notification")
    rejected(c, lambda: call(c, "prepare_shipment", 2, f["loan"], "return", 2, 1, None, None, "2026-10-29 12:00+01"), "No shipment for terminal loan")


def t_timestamps(c):
    f = fixture(c)
    rejected(c, lambda: call(c, "accept_request", 1, f["loan"], f["slot"], START, END, "2026-10-19 09:00+02"), "Acceptance before request")
    accept_fixture(c, f)
    rejected(c, lambda: call(c, "receive_pickup", 2, f["loan"], "2026-10-20 09:00+02"), "Receipt before acceptance")
    call(c, "receive_pickup", 2, f["loan"], RECEIVE)
    rejected(c, lambda: call(c, "start_return", 2, f["loan"], "2026-10-25 09:00+01"), "Return before receipt")
    call(c, "start_return", 2, f["loan"], "2026-10-27 09:00+01")
    rejected(c, lambda: call(c, "confirm_return", 1, f["loan"], "2026-10-26 09:00+01"), "Completion before return")


def t_reviews(c):
    f = fixture(c, accept=True, receive=True)
    rejected(c, lambda: call(c, "review_loan", 2, f["loan"], 5, "Too early", "2026-10-27 09:00+01"), "Review before completion")
    finish_pickup(c, f)
    rejected(c, lambda: call(c, "review_loan", 3, f["loan"], 5, "Third party", "2026-10-28 09:00+01"), "Review by third party")
    rejected(c, lambda: call(c, "review_loan", 2, f["loan"], 6, "Too high", "2026-10-28 09:00+01"), "Rating range")
    call(c, "review_loan", 2, f["loan"], 5, "Borrower test", "2026-10-28 09:00+01")
    call(c, "review_loan", 1, f["loan"], 4, "Owner test", "2026-10-28 10:00+01")
    rejected(c, lambda: call(c, "review_loan", 2, f["loan"], 4, "Duplicate", "2026-10-28 11:00+01"), "Duplicate review")
    eq(scalar(c, "SELECT count(*) FROM bookbridge.reviews WHERE loan_id=%s", (f["loan"],)), 2)


def t_documents(c):
    f = fixture(c, mode="shipping", accept=True, receive=True)
    g = fixture(c, mode="shipping", accept=True, receive=True)
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.generated_documents(loan_id,recipient_user_id,document_type,status) VALUES(%s,3,'loan_confirmation','planned')", (f["loan"],)), "Private document recipient")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.generated_documents(loan_id,shipment_id,recipient_user_id,document_type,status) VALUES(%s,%s,2,'shipment_summary','planned')", (f["loan"], g["outbound"])), "Shipment belongs to another loan")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.generated_documents(loan_id,recipient_user_id,document_type,status) VALUES(%s,2,'return_confirmation','planned')", (f["loan"],)), "Return document before completion")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.notifications(recipient_user_id,loan_id,message) VALUES(3,%s,'Forbidden')", (f["loan"],)), "Notification recipient must participate")
    rejected(c, lambda: c.execute("INSERT INTO bookbridge.generated_documents(loan_id,recipient_user_id,document_type,status,storage_path,generated_at) VALUES(%s,2,'loan_confirmation','created','/public/proof.pdf',CURRENT_TIMESTAMP)", (f["loan"],)), "Document path must be private")


def t_history(c):
    f = fixture(c, accept=True, receive=True)
    rejected(c, lambda: c.execute("UPDATE bookbridge.loans SET borrower_id=3 WHERE loan_id=%s", (f["loan"],)), "Loan borrower immutable")
    rejected(c, lambda: c.execute("UPDATE bookbridge.loans SET requested_days=21 WHERE loan_id=%s", (f["loan"],)), "Requested duration immutable")
    rejected(c, lambda: c.execute("UPDATE bookbridge.loans SET due_date=due_date+1 WHERE loan_id=%s", (f["loan"],)), "Unexplained deadline change")
    rejected(c, lambda: c.execute("UPDATE bookbridge.loans SET received_at=received_at+interval '1 minute' WHERE loan_id=%s", (f["loan"],)), "Receipt time immutable")
    finish_pickup(c, f)
    rejected(c, lambda: c.execute("UPDATE bookbridge.loans SET status='active',return_started_at=NULL,completed_at=NULL WHERE loan_id=%s", (f["loan"],)), "Terminal loan cannot reopen")


def t_deactivation(c):
    f = fixture(c, accept=True, receive=True)
    rejected(c, lambda: call(c, "set_user_active", 2, 1, False, "2026-10-27 09:00+01"), "Only admin moderates another user")
    call(c, "set_user_active", 24, 1, False, "2026-10-27 09:00+01")
    eq(scalar(c, "SELECT count(*) FROM bookbridge.book_copies WHERE owner_id=1 AND is_active"), 0)
    rejected(c, lambda: call(c, "create_request", 3, f["copy"], 14, "pickup", "2026-10-27 10:00+01"), "Inactive owner new request")
    finish_pickup(c, f)
    eq(loan_row(c, f["loan"])[0], "completed", "Existing loan may finish after account deactivation")
    call(c, "set_user_active", 24, 1, True, "2026-10-28 09:00+01")
    eq(scalar(c, "SELECT count(*) FROM bookbridge.book_copies WHERE owner_id=1 AND is_active"), 0, "Reactivation must not republish offers")
    g = fixture(c, accept=True, receive=True)
    call(c, "set_user_active", 24, 2, False, "2026-10-27 09:00+01")
    finish_pickup(c, g)
    eq(loan_row(c, g["loan"])[0], "completed", "Inactive borrower may complete an existing loan")


def t_access(c):
    f = fixture(c)
    c.execute("SET CONSTRAINTS ALL IMMEDIATE")
    public_execute = scalar(c, "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE n.nspname='bookbridge' AND a.grantee=0 AND a.privilege_type='EXECUTE'")
    eq(public_execute, 0, "No PUBLIC execution of domain or helper functions")
    c.execute("SET LOCAL ROLE bookbridge_reader")
    cur = c.execute("SELECT * FROM bookbridge.public_catalog ORDER BY copy_id")
    truth(len(cur.fetchall()) >= 24, "Reader can inspect public catalog")
    forbidden = {"email", "password_hash", "street", "latitude", "longitude", "pickup_address_id", "storage_path", "first_name", "last_name", "owner_id"}
    truth(not (forbidden & {col.name for col in cur.description}), "Public catalog contains private fields")
    rejected(c, lambda: c.execute("SELECT * FROM bookbridge.addresses"), "Public reader cannot read private addresses")
    rejected(c, lambda: call(c, "create_request", 3, f["copy"], 14, "pickup", REQUEST), "Public reader cannot invoke write API")
    c.execute("RESET ROLE")
    c.execute("SET LOCAL ROLE bookbridge_backend")
    for table in TABLES:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            truth(not scalar(c, "SELECT has_table_privilege(current_user,%s,%s)", ("bookbridge." + table, privilege)), f"Backend may not {privilege} private base table {table}")
    rejected(c, lambda: c.execute("UPDATE bookbridge.users SET is_active=false WHERE user_id=1"), "Backend cannot bypass workflows with table DML")
    rejected(c, lambda: call(c, "_actor", 1, True), "Backend cannot call private helper")
    loan = call(c, "create_request", 3, f["copy"], 14, "pickup", REQUEST)
    truth(isinstance(loan, int), "Trusted backend may invoke authorized public domain API")
    c.execute("RESET ROLE")
    eq(scalar(c, "SELECT borrower_id FROM bookbridge.loans WHERE loan_id=%s", (loan,)), 3)


TESTS = [
    ("T03", "Katalog, ISBN, E-Mail und aufgeschobene Autorenteilnahme", ["R03", "R19"], t_catalog),
    ("T04", "Koordinaten, Eigentümeranschrift und aktive Wochenfenster", ["R02", "R03", "R07"], t_location),
    ("T05", "Eigentum und referenzierte Historie", ["R04", "R20"], t_ownership),
    ("T06", "Teilnehmer, Eigenleihe, Anfragen und genau eine Reservierung", ["R01", "R05"], t_roles_requests),
    ("T07", "Konkreter Abholtermin und unveränderliche Momentaufnahme", ["R06", "R07", "R08", "R20"], t_pickup),
    ("T08", "Gegenvorschläge, Rollen und ausstehende Entscheidungen", ["R09"], t_proposals),
    ("T09", "Verlängerung genau einmal und eingefrorene Gesamthöchstdauer", ["R06", "R10", "R20"], t_extension),
    ("T10", "Vorzeitige Rückgabe, ausstehende Verlängerung und Freigabe", ["R10", "R15"], t_early_return),
    ("T11", "Verspätete Rückgabe bleibt abschließbar", ["R06", "R15"], t_late_return),
    ("T12", "Kalenderfrist über beide Zeitumstellungen in Europe/Berlin", ["R06", "R16"], t_dst),
    ("T13", "Portobestätigung, Versandvoraussetzung und atomarer Erhalt", ["R11", "R14", "R20"], t_postage),
    ("T14", "Stornierung mit offenem und bestätigtem Porto", ["R09", "R12"], t_cancellation),
    ("T15", "Hin-/Rückversand, Anschriften und korrekte Empfangsperson", ["R13", "R14"], t_shipments),
    ("T16", "Ereignisreihenfolge und Rückdatierungsverbot", ["R16"], t_timestamps),
    ("T17", "Zwei Teilnehmerbewertungen erst nach Abschluss", ["R17"], t_reviews),
    ("T18", "Private Kommunikation, Dokumente und gleiche Ausleihe", ["R18"], t_documents),
    ("T19", "Unveränderliche Ausleihhistorie und erklärbare Frist", ["R19", "R20"], t_history),
    ("T20", "Kontodeaktivierung und Fortsetzung bestehender Vorgänge", ["R01", "R05", "R15"], t_deactivation),
    ("T23", "Öffentliche Lesesicht, Backend-API und gesperrte private Tabellen/Helfer", ["R02", "R18", "R19"], t_access),
]


def record(report, test_id, name, rules, action):
    start = time.perf_counter()
    item = {"id": test_id, "name": name, "rules": rules}
    try:
        extra = action()
        item.update(status="passed")
        if extra is not None:
            item["evidence"] = extra
    except Exception as exc:
        item.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if isinstance(exc, psycopg.Error):
            item["sqlstate"] = exc.sqlstate
    item["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
    report["tests"].append(item)
    print(f"{test_id}: {item['status']} - {name}", flush=True)


def export_results(c, output, report):
    rows_dir = output / "tables"
    rows_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table in TABLES:
        columns = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='bookbridge' AND table_name=%s AND column_name<>'password_hash' ORDER BY ordinal_position", (table,)).fetchall()]
        query = "SELECT " + ",".join(columns) + f" FROM bookbridge.{table} ORDER BY 1"
        cur = c.execute(query)
        rows = cur.fetchall()
        counts[table] = len(rows)
        with (rows_dir / f"{table}.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            writer.writerows(rows)
    report["entity_counts"] = counts
    record(report, "T01", "Alle 18 Tabellen real abgefragt und mit mindestens zehn Zeilen belegt", [], lambda: truth(len(counts) == 18 and min(counts.values()) >= 10, str(counts)))
    joins = {}
    for name, query in JOIN_QUERIES.items():
        cur = c.execute(query)
        rows = cur.fetchall()
        with (output / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([col.name for col in cur.description])
            writer.writerows(rows)
        joins[name] = {"sql": query, "rows": len(rows)}
    report["join_queries"] = joins
    record(report, "T02", "Drei echte JOIN-Abfragen mit je drei Tabellen und Ergebnisexport", [], lambda: truth(all(v["rows"] >= 10 for v in joins.values()), str(joins)))


def fingerprints(c):
    return {table: scalar(c, "SELECT md5(coalesce(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),'')) FROM bookbridge." + table + " t") for table in TABLES}


def concurrent_race(dsn, expected_main_db):
    with connect(dsn) as c:
        db = scalar(c, "SELECT current_database()")
        truth(db != expected_main_db, "Race fixtures must use a separate disposable database")
        with c.transaction():
            f = fixture(c)
            other = call(c, "create_request", 3, f["copy"], 14, "pickup", REQUEST)
        ids = [f["loan"], other]
    barrier = threading.Barrier(2)

    def accept(loan):
        with connect(dsn) as c:
            c.execute("SET lock_timeout='8s'")
            barrier.wait(timeout=10)
            try:
                with c.transaction():
                    call(c, "accept_request", 1, loan, f["slot"], START, END, ACCEPT)
                    c.execute("SET CONSTRAINTS ALL IMMEDIATE")
                return {"loan_id": loan, "result": "committed"}
            except psycopg.Error as exc:
                if exc.sqlstate not in {"P0001", "23505", "23514", "55000", "22023"}:
                    raise
                return {"loan_id": loan, "result": "rejected", "sqlstate": exc.sqlstate, "message": str(exc).splitlines()[0]}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, ids))
    eq(sorted(r["result"] for r in results), ["committed", "rejected"], "Exactly one committed acceptance")
    with connect(dsn) as c:
        states = c.execute("SELECT loan_id,status FROM bookbridge.loans WHERE copy_id=%s ORDER BY loan_id", (f["copy"],)).fetchall()
        eq(sorted(r[1] for r in states), ["accepted", "requested"])
    return {"disposable_database": db, "separate_connections": 2, "results": results, "final_states": states}


def isolated_concurrent_race(main_dsn, external_test_dsn, main_database):
    if external_test_dsn:
        return concurrent_race(external_test_dsn, main_database)
    # CREATE DATABASE requires a CREATEDB owner. Main connections are closed first.
    # A UUID name plus created flag prevents touching a pre-existing database.
    name = "bookbridge_phase2_test_" + uuid.uuid4().hex[:16]
    maintenance_dsn = psycopg.conninfo.make_conninfo(main_dsn, dbname="postgres")
    clone_dsn = psycopg.conninfo.make_conninfo(main_dsn, dbname=name)
    created = False
    try:
        with psycopg.connect(maintenance_dsn, autocommit=True) as admin:
            admin.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(psycopg.sql.Identifier(name), psycopg.sql.Identifier(main_database)))
            created = True
        result = concurrent_race(clone_dsn, main_database)
        result["clone_dropped_after_test"] = True
        return result
    finally:
        if created:
            with psycopg.connect(maintenance_dsn, autocommit=True) as admin:
                admin.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", "host=127.0.0.1 port=55432 dbname=bookbridge_phase2 user=bookbridge_admin"))
    parser.add_argument("--concurrency-dsn", default=os.environ.get("TEST_DATABASE_URL"))
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "reports" / "tests")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"project": "BookBridge", "executed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "driver": "psycopg " + psycopg.__version__, "tests": []}
    with connect(args.dsn) as c:
        report["database"] = scalar(c, "SELECT current_database()")
        report["server_version"] = scalar(c, "SELECT version()")
        report["timezone"] = scalar(c, "SHOW TIME ZONE")
        export_results(c, args.out, report)
        initial_counts = dict(report["entity_counts"])
        initial_fingerprints = fingerprints(c)
        for test_id, name, rules, test in TESTS:
            def execute(test=test):
                with c.transaction(force_rollback=True):
                    test(c)
                    c.execute("SET CONSTRAINTS ALL IMMEDIATE")
            record(report, test_id, name, rules, execute)
        after_counts = {table: scalar(c, f"SELECT count(*) FROM bookbridge.{table}") for table in TABLES}
        after_fingerprints = fingerprints(c)
        def verify_rollback():
            eq(after_counts, initial_counts, "Row counts after fixture rollback")
            eq(after_fingerprints, initial_fingerprints, "All seed row contents after fixture rollback")
            return {"entity_fingerprints": after_fingerprints, "identity_sequences": "Sequence increments are not transactional in PostgreSQL; gaps are expected and harmless."}
        record(report, "T21", "Alle normalen Testfixtures zurückgerollt; Seed-Zeilen unverändert", ["R20"], verify_rollback)
    record(report, "T22", "Zwei parallele Verbindungen: genau eine Annahme desselben Exemplars", ["R05", "R19", "R20"], lambda: isolated_concurrent_race(args.dsn, args.concurrency_dsn, report["database"]))
    passed = [r for r in report["tests"] if r["status"] == "passed"]
    report["summary"] = {"executed": len(report["tests"]), "passed": len(passed), "failed": len(report["tests"]) - len(passed), "rules_exercised_by_passing_tests": sorted({rule for r in passed for rule in r["rules"]})}
    (args.out / "test-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return int(bool(report["summary"]["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
