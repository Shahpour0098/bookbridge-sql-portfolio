"""Isolated regressions for authentication, CSRF and protected file boundaries.

These checks never connect to PostgreSQL. The integration suite exercises real
sessions and workflows; these cases cover adversarial HTTP input and file paths.
"""
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime" / "python"))
sys.path.insert(0, str(ROOT))

from flask import g
from backend.app import create_app


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / ".runtime" / "test-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="bookbridge-api-", dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)
        self.app = create_app({"database_dsn": "unused-test-dsn", "TESTING": True,
                               "runtime_directory": str(self.runtime)})
        self.user = {"user_id": 11, "first_name": "Test", "last_name": "Mitglied",
                     "email": "test@example.invalid", "role": "member", "is_active": True}

        def inject_session():
            g.session_data = {"token_hash": "test-session", "user_id": 11,
                              "csrf_token": "a" * 43}
            g.user = self.user

        self.app.before_request_funcs[None].insert(0, inject_session)
        self.client = self.app.test_client()
        connection_patch = patch("backend.app.psycopg.connect")
        self.connect = connection_patch.start()
        self.connect.side_effect = AssertionError("Unexpected database access")
        self.addCleanup(connection_patch.stop)

    def test_application_script_has_a_real_route(self):
        response = self.client.get("/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.mimetype)
        self.assertGreater(len(response.data), 100)
        response.close()
        self.connect.assert_not_called()

    def test_public_gets_do_not_create_or_replace_anonymous_sessions(self):
        # Use the real clean-browser boundary, without the private-route test
        # session. Concurrent public fetches must not race /api/session's cookie.
        self.app.before_request_funcs[None].pop(0)
        self.connect.side_effect = None
        connection = self.connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = {"n": 0}
        connection.execute.return_value.fetchall.return_value = []
        for path in ("/api/meta", "/api/catalog"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Set-Cookie", response.headers)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertFalse(any("bookbridge_app.sessions" in statement for statement in statements))

    def test_explicit_session_get_still_creates_the_anonymous_cookie(self):
        self.app.before_request_funcs[None].pop(0)
        self.connect.side_effect = None
        connection = self.connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = {
            "token_hash": "test-hash", "user_id": None, "csrf_token": "a" * 43}
        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["csrf_token"], "a" * 43)
        self.assertIsNone(response.json["user"])
        self.assertIn("bookbridge_session=", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])

    def test_source_and_runtime_are_not_static_routes(self):
        for path in ("/backend/app.py", "/.runtime/config.json", "/documents/document-1.pdf"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.connect.assert_not_called()

    def test_missing_csrf_fails_before_mutation(self):
        response = self.client.post("/api/loans", json={"copy_id": 1, "days": 7, "mode": "shipping"})
        self.assertEqual(response.status_code, 403)
        self.connect.assert_not_called()

    def test_non_ascii_csrf_is_rejected_as_forbidden(self):
        response = self.client.post("/api/loans", json={}, headers={"X-CSRF-Token": "ungültig"})
        self.assertEqual(response.status_code, 403)
        self.connect.assert_not_called()

    def test_foreign_origin_is_rejected_even_with_correct_csrf(self):
        response = self.client.post("/api/loans", json={},
                                    headers={"X-CSRF-Token": "a" * 43, "Origin": "https://example.invalid"})
        self.assertEqual(response.status_code, 403)
        self.connect.assert_not_called()

    def test_guests_cannot_retrieve_private_data(self):
        self.user = None
        for path in ("/api/addresses", "/api/my-books", "/api/loans", "/api/notifications",
                     "/api/documents/1/download"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.connect.assert_not_called()

    def test_member_cannot_access_admin_lists_or_mutations(self):
        for path, method, payload in (("/api/admin/users", "GET", None), ("/api/admin/offers", "GET", None),
                                      ("/api/admin/users/9", "PATCH", {"is_active": False}),
                                      ("/api/admin/offers/9", "PATCH", {"is_active": False})):
            with self.subTest(path=path):
                response = self.client.open(path, method=method, json=payload,
                                            headers={"X-CSRF-Token": "a" * 43})
                self.assertEqual(response.status_code, 403)
        self.connect.assert_not_called()

    def test_inactive_admin_cannot_moderate(self):
        self.user.update(role="admin", is_active=False)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.connect.assert_not_called()

    def test_admin_mutation_uses_session_actor_and_sql_workflow(self):
        self.user["role"] = "admin"
        self.connect.side_effect = None
        connection = self.connect.return_value.__enter__.return_value
        target = dict(self.user, user_id=9, role="member", is_active=False)
        connection.execute.side_effect = [Result({"user_id": 9}), Result(None), Result(target)]
        response = self.client.patch("/api/admin/users/9", json={"is_active": False},
                                     headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["user"]["is_active"])
        self.assertIn("bookbridge.set_user_active", connection.execute.call_args_list[1].args[0])
        self.assertEqual(connection.execute.call_args_list[1].args[1], (11, 9, False))

    def test_admin_cannot_supply_another_actor(self):
        self.user["role"] = "admin"
        response = self.client.patch("/api/admin/users/9", json={"is_active": False, "actor_id": 99},
                                     headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 400)
        self.connect.assert_not_called()

    def test_deactivation_targets_own_account_and_retains_identity(self):
        self.connect.side_effect = None
        connection = self.connect.return_value.__enter__.return_value
        connection.execute.side_effect = [Result(None), Result(dict(self.user, is_active=False))]
        response = self.client.post("/api/account/deactivate", json={},
                                    headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["user_id"], 11)
        self.assertFalse(response.json["user"]["is_active"])
        self.assertIn("bookbridge.set_user_active", connection.execute.call_args_list[0].args[0])
        self.assertEqual(connection.execute.call_args_list[0].args[1], (11, 11))

    def test_address_owner_cannot_be_changed_from_http(self):
        response = self.client.patch("/api/addresses/8", json={"user_id": 99},
                                     headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 400)
        self.connect.assert_not_called()

    def test_address_coordinate_pair_is_validated_before_writing(self):
        payload = {"street": "Testweg 1", "postal_code": "10115", "city": "Berlin", "country_code": "DE",
                   "latitude": 52.5, "longitude": None}
        response = self.client.patch("/api/addresses/8", json=payload,
                                     headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 400)
        self.connect.assert_not_called()

    def test_address_update_scopes_current_member_and_allows_empty_coordinate_pair(self):
        payload = {"street": "Testweg 1", "postal_code": "10115", "city": "Berlin", "country_code": "DE",
                   "latitude": None, "longitude": None}
        self.connect.side_effect = None
        connection = self.connect.return_value.__enter__.return_value
        connection.execute.return_value = Result(dict(payload, address_id=8))
        response = self.client.patch("/api/addresses/8", json=payload,
                                     headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 200)
        query, parameters = connection.execute.call_args.args
        self.assertIn("WHERE address_id=%s AND user_id=%s", query)
        self.assertEqual(parameters[-4:], (None, None, 8, 11))

    def test_foreign_address_update_returns_not_found(self):
        self.connect.side_effect = None
        connection = self.connect.return_value.__enter__.return_value
        connection.execute.return_value = Result(None)
        response = self.client.patch("/api/addresses/8", json={"street": "Testweg 1", "postal_code": "10115",
                                     "city": "Berlin", "country_code": "DE"},
                                     headers={"X-CSRF-Token": "a" * 43})
        self.assertEqual(response.status_code, 404)

    def document_connection(self, row):
        test = self

        class Connection:
            def execute(self, query, parameters):
                test.assertIn("recipient_user_id=%s", query)
                test.assertEqual(parameters, (23, 11))
                return Result(row)

        @contextmanager
        def connection(*args, **kwargs):
            yield Connection()

        self.connect.side_effect = connection

    def test_document_must_belong_to_current_recipient(self):
        self.document_connection(None)
        response = self.client.get("/api/documents/23/download")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("application/pdf", response.content_type)

    def test_document_cannot_escape_private_document_directory(self):
        (self.runtime / "config.json").write_text("private settings", encoding="utf-8")
        self.document_connection({"status": "created", "storage_path": "documents/../config.json"})
        response = self.client.get("/api/documents/23/download")
        self.assertEqual(response.status_code, 410)
        self.assertNotIn(b"private settings", response.data)

    def test_missing_created_document_is_not_silently_regenerated(self):
        self.document_connection({"status": "created", "storage_path": "documents/missing.pdf"})
        self.assertEqual(self.client.get("/api/documents/23/download").status_code, 410)

    def test_private_document_download_uses_no_store(self):
        folder = self.runtime / "documents"
        folder.mkdir()
        (folder / "document-23.pdf").write_bytes(b"%PDF-1.4\nprotected fixture")
        self.document_connection({"status": "created", "storage_path": "documents/document-23.pdf"})
        response = self.client.get("/api/documents/23/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        response.close()


if __name__ == "__main__":
    unittest.main()
