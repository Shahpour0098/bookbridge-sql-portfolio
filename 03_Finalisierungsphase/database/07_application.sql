-- Phase 3: server-side sessions and the trusted web service's restricted grants.
-- Phase 2 source files are retained byte for byte in database/phase2/.
BEGIN;
CREATE SCHEMA IF NOT EXISTS bookbridge_app;
REVOKE ALL ON SCHEMA bookbridge_app FROM PUBLIC;

CREATE TABLE IF NOT EXISTS bookbridge_app.migrations (
    version TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL CHECK (source_hash ~ '^[a-f0-9]{64}$'),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bookbridge_app.sessions (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[a-f0-9]{64}$'),
    user_id BIGINT REFERENCES bookbridge.users(user_id),
    csrf_token TEXT NOT NULL CHECK (length(csrf_token) >= 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT sessions_lifetime_ck CHECK (expires_at > created_at)
);
CREATE INDEX sessions_expiry_idx ON bookbridge_app.sessions(expires_at);
CREATE INDEX sessions_user_idx ON bookbridge_app.sessions(user_id);
COMMENT ON TABLE bookbridge_app.sessions IS 'Serverseitige Sitzungen; nur SHA-256 des zufaelligen Sitzungscookies wird gespeichert.';

GRANT bookbridge_backend TO bookbridge_web;
GRANT USAGE ON SCHEMA bookbridge,bookbridge_app TO bookbridge_web;
GRANT SELECT ON ALL TABLES IN SCHEMA bookbridge TO bookbridge_web;
GRANT INSERT ON bookbridge.users,bookbridge.addresses,bookbridge.publishers,
    bookbridge.authors,bookbridge.books,bookbridge.book_authors,
    bookbridge.book_copies,bookbridge.pickup_slots TO bookbridge_web;
GRANT UPDATE(first_name,last_name,password_hash) ON bookbridge.users TO bookbridge_web;
GRANT UPDATE(condition,max_loan_days,notes) ON bookbridge.book_copies TO bookbridge_web;
GRANT UPDATE(status,delivered_at,read_at) ON bookbridge.notifications TO bookbridge_web;
GRANT UPDATE(status,storage_path,generated_at) ON bookbridge.generated_documents TO bookbridge_web;
GRANT USAGE ON SEQUENCE bookbridge.users_user_id_seq,
    bookbridge.addresses_address_id_seq,bookbridge.publishers_publisher_id_seq,
    bookbridge.authors_author_id_seq,bookbridge.books_book_id_seq,
    bookbridge.book_copies_copy_id_seq,bookbridge.pickup_slots_slot_id_seq TO bookbridge_web;
GRANT SELECT,INSERT,UPDATE,DELETE ON bookbridge_app.sessions TO bookbridge_web;

-- CHECK expressions and deferred copy consistency call these invoker functions.
GRANT EXECUTE ON FUNCTION bookbridge.isbn_valid(text),
    bookbridge.validate_copy(bigint) TO bookbridge_web;

-- Invoker triggers need row locks on their related rows. Running only the
-- trigger functions as the schema owner avoids granting direct state updates
-- on loans or shared bibliographic rows to the web login. Their Phase 2 fixed
-- search paths contain pg_catalog and the owner-controlled bookbridge schema.
ALTER FUNCTION bookbridge.tg_lock_author_book() SECURITY DEFINER;
ALTER FUNCTION bookbridge.tg_copy_guard() SECURITY DEFINER;
ALTER FUNCTION bookbridge.tg_slot_overlap() SECURITY DEFINER;
ALTER FUNCTION bookbridge.tg_loan_child_guard() SECURITY DEFINER;

REVOKE ALL ON ALL TABLES IN SCHEMA bookbridge_app FROM PUBLIC;
REVOKE ALL ON bookbridge_app.migrations FROM bookbridge_web;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
COMMIT;
