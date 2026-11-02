"""Focused HTTP-boundary and Europe/Berlin appointment regression checks."""
import sys
import unittest
from datetime import datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime" / "python"))
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify
from backend.domain import next_pickup_occurrence, register_routes


class BerlinAppointmentTests(unittest.TestCase):
    def test_next_whole_window_is_future(self):
        start, end = next_pickup_occurrence(
            1, time(17), time(18), datetime.fromisoformat("2026-10-19T17:30:00+02:00"))
        self.assertEqual(start.isoformat(), "2026-10-26T17:00:00+01:00")
        self.assertEqual(end.isoformat(), "2026-10-26T18:00:00+01:00")

    def test_spring_clock_gap_is_skipped(self):
        start, end = next_pickup_occurrence(
            7, time(2, 15), time(2, 45), datetime.fromisoformat("2027-03-27T12:00:00+01:00"))
        self.assertEqual(start.isoformat(), "2027-04-04T02:15:00+02:00")
        self.assertGreater(end.astimezone(timezone.utc), start.astimezone(timezone.utc))

    def test_repeated_autumn_time_can_use_second_occurrence(self):
        start, end = next_pickup_occurrence(
            7, time(2, 15), time(2, 45), datetime.fromisoformat("2026-10-25T02:30:00+02:00"))
        self.assertEqual(start.isoformat(), "2026-10-25T02:15:00+01:00")
        self.assertEqual(end.isoformat(), "2026-10-25T02:45:00+01:00")


class MutationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.database_calls = 0
        self.csrf_calls = 0
        app = Flask(__name__)
        app.config["TESTING"] = True

        def connection():
            self.database_calls += 1
            raise AssertionError("Invalid input must not reach the database")

        def csrf():
            self.csrf_calls += 1

        @app.errorhandler(ValueError)
        def validation_error(exc):
            return jsonify(error=str(exc)), 400

        register_routes(app, connection, lambda: {"user_id": 1}, csrf)
        self.client = app.test_client()

    def test_cannot_supply_domain_actor(self):
        response = self.client.post("/api/loans", json={
            "copy_id": 4, "days": 7, "mode": "shipping", "actor_id": 99})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.csrf_calls, 1)
        self.assertEqual(self.database_calls, 0)

    def test_cannot_supply_event_timestamp(self):
        response = self.client.post("/api/loans/8/actions", json={
            "action": "receive_pickup", "at": "2099-01-01T10:00:00+01:00"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_calls, 0)

    def test_cannot_rewrite_shared_bibliography_via_copy_patch(self):
        response = self.client.patch("/api/books/4", json={"title": "Unzulässige Änderung"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_calls, 0)

    def test_nonfinite_origin_is_rejected(self):
        response = self.client.get("/api/catalog?radius=10&latitude=NaN&longitude=13")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_calls, 0)

    def test_partial_origin_is_rejected(self):
        response = self.client.get("/api/catalog?radius=10&latitude=52")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_calls, 0)

    def test_replacement_pickup_windows_must_not_overlap(self):
        response = self.client.patch("/api/books/4", json={"pickup_slots": [
            {"weekday": 1, "start_time": "16:00", "end_time": "18:00"},
            {"weekday": 1, "start_time": "17:00", "end_time": "19:00"}]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_calls, 0)


class ParticipantBoundaryTests(unittest.TestCase):
    """Keep current contact details separate from the immutable loan history."""

    def setUp(self):
        self.actor = 7
        self.active = True
        self.status = "active"
        self.child_exists = True
        self.address_owned = True
        self.address_coordinates = True
        self.calls = []
        test = self

        class Result:
            def __init__(self, rows):
                self.rows = rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return self.rows

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, params):
                test.calls.append((query, params))
                loan = {"loan_id": 33, "copy_id": 20, "owner_id": 7, "borrower_id": 9,
                        "handover_mode": "shipping", "status": test.status,
                        "accepted_at": datetime.fromisoformat("2026-10-01T10:00:00+02:00"),
                        "pickup_address_snapshot": None}
                if query.startswith("SELECT l.*"):
                    return Result([loan])
                if query.startswith("SELECT owner_id,allow_pickup"):
                    return Result([{"owner_id": 7, "allow_pickup": True, "allow_shipping": True, "is_active": True}])
                if query.startswith("SELECT latitude,longitude"):
                    return Result([{"latitude": 52.5 if test.address_coordinates else None,
                                    "longitude": 13.4 if test.address_coordinates else None}] if test.address_owned else [])
                if query.startswith("SELECT 1 FROM bookbridge.pickup_slots"):
                    return Result([{"exists": 1}])
                if "FROM bookbridge.addresses" in query:
                    return Result([{"address_id": 8, "user_id": 9, "street": "Aktuelle Anschrift 5",
                                    "postal_code": "10115", "city": "Berlin", "country_code": "DE"}])
                if query.startswith("SELECT proposal_id") or query.startswith("SELECT extension_id"):
                    return Result([{"id": 55}] if test.child_exists else [])
                if query.startswith("SELECT bookbridge."):
                    return Result([{"id": 55}])
                return Result([])

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.errorhandler(ValueError)
        def invalid(exc):
            return jsonify(error=str(exc)), 400

        @app.errorhandler(PermissionError)
        def forbidden(exc):
            return jsonify(error=str(exc)), 403

        @app.errorhandler(LookupError)
        def missing(exc):
            return jsonify(error=str(exc)), 404

        register_routes(app, Connection, lambda: {"user_id": self.actor, "is_active": self.active}, lambda: None)
        self.client = app.test_client()

    def test_ongoing_shipping_exposes_needed_recipient_addresses(self):
        response = self.client.get("/api/loans")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"][0]["recipient_addresses"][0]["address_id"], 8)

    def test_completed_shipping_does_not_expose_later_address_additions(self):
        self.status = "completed"
        response = self.client.get("/api/loans")
        self.assertEqual(response.status_code, 200)
        item = response.json["items"][0]
        self.assertEqual(item["sender_addresses"], [])
        self.assertEqual(item["recipient_addresses"], [])
        self.assertFalse(any("FROM bookbridge.addresses" in query for query, _ in self.calls))

    def test_outsider_cannot_trigger_a_loan_workflow(self):
        self.actor = 99
        response = self.client.post("/api/loans/33/actions", json={"action": "confirm_return"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(any(query.startswith("SELECT bookbridge.") for query, _ in self.calls))

    def test_cross_loan_child_is_rejected_before_workflow(self):
        self.child_exists = False
        response = self.client.post("/api/loans/33/actions", json={
            "action": "decide_extension", "extension_id": 55, "decision": "approved"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(any(query.startswith("SELECT bookbridge.decide_") for query, _ in self.calls))

    def test_owner_can_pass_proposal_withdrawal_to_authoritative_workflow(self):
        response = self.client.post("/api/loans/33/actions", json={
            "action": "decide_proposal", "proposal_id": 55, "decision": "withdrawn"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1][1], [7, 55, "withdrawn"])

    def test_borrower_can_pass_extension_withdrawal_to_authoritative_workflow(self):
        self.actor = 9
        response = self.client.post("/api/loans/33/actions", json={
            "action": "decide_extension", "extension_id": 55, "decision": "withdrawn"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1][1], [9, 55, "withdrawn"])

    def test_inactive_member_cannot_begin_new_work(self):
        self.active = False
        requests = [("/api/books", {}), ("/api/loans", {"copy_id": 20, "days": 7, "mode": "shipping"}),
                    ("/api/loans/33/actions", {"action": "accept"}),
                    ("/api/loans/33/actions", {"action": "propose", "days": 7}),
                    ("/api/loans/33/actions", {"action": "decide_proposal", "proposal_id": 55, "decision": "accepted"})]
        for path, payload in requests:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(path, json=payload).status_code, 403)
        self.assertEqual(self.calls, [])

    def test_inactive_member_can_complete_an_existing_loan(self):
        self.active = False
        self.status = "returning"
        response = self.client.post("/api/loans/33/actions", json={"action": "confirm_return"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("bookbridge.confirm_return", self.calls[-1][0])
        self.assertEqual(self.calls[-1][1], [7, 33])

    def test_offer_location_must_remain_an_own_address(self):
        self.address_owned = False
        response = self.client.patch("/api/books/20", json={"address_id": 99})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(any(query.startswith("UPDATE") for query, _ in self.calls))

    def test_replacement_slots_preserve_historical_rows(self):
        response = self.client.patch("/api/books/20", json={"pickup_slots": [
            {"weekday": 2, "start_time": "17:00", "end_time": "18:00"}]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("FOR UPDATE", self.calls[0][0])
        writes = [(query, params) for query, params in self.calls if query.startswith(("UPDATE", "INSERT", "DELETE"))]
        self.assertEqual(len(writes), 2)
        self.assertTrue(writes[0][0].startswith("UPDATE bookbridge.pickup_slots SET is_active=false"))
        self.assertTrue(writes[1][0].startswith("INSERT INTO bookbridge.pickup_slots"))
        self.assertEqual(writes[1][1], (20, 2, time(17), time(18)))

    def test_pause_precedes_moving_offer_to_address_without_coordinates(self):
        self.address_coordinates = False
        response = self.client.patch("/api/books/20", json={"is_active": False, "address_id": 88})
        self.assertEqual(response.status_code, 200)
        writes = [(query, params) for query, params in self.calls if query.startswith(("UPDATE", "SELECT bookbridge.set_offer_active"))]
        self.assertIn("set_offer_active", writes[0][0])
        self.assertIn("false", writes[0][0])
        self.assertTrue(writes[1][0].startswith("UPDATE bookbridge.book_copies"))


if __name__ == "__main__":
    unittest.main()
