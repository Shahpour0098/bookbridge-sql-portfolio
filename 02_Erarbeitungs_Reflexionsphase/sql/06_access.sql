-- BookBridge: Rechte für vertrauenswürdiges Backend und öffentliche Lesesicht.
-- Das Backend authentifiziert die Person und übergibt deren actor_id an die APIs.
-- actor_id ist kein Ersatz für eine Anwendungsanmeldung.
BEGIN;
SET search_path=pg_catalog,bookbridge;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='bookbridge_reader') THEN
   CREATE ROLE bookbridge_reader NOLOGIN;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='bookbridge_backend') THEN
   CREATE ROLE bookbridge_backend NOLOGIN;
 END IF;
END $$;
REVOKE ALL ON SCHEMA bookbridge FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA bookbridge FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA bookbridge FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA bookbridge FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA bookbridge REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
CREATE VIEW bookbridge.public_catalog WITH (security_barrier=true) AS
SELECT c.copy_id,b.title,b.subtitle,b.isbn,
 (SELECT string_agg(a.display_name,', ' ORDER BY ba.author_order)
  FROM bookbridge.book_authors ba JOIN bookbridge.authors a ON a.author_id=ba.author_id
  WHERE ba.book_id=b.book_id) AS authors,
 g.name AS genre,lg.name AS language,c.condition,c.max_loan_days,
 c.allow_pickup,c.allow_shipping,ad.city,ad.postal_code,ad.country_code,
 NOT EXISTS(SELECT 1 FROM bookbridge.loans l WHERE l.copy_id=c.copy_id
   AND l.status IN('accepted','outbound','active','returning')) AS available
FROM bookbridge.book_copies c
JOIN bookbridge.books b ON b.book_id=c.book_id
JOIN bookbridge.users u ON u.user_id=c.owner_id
JOIN bookbridge.addresses ad ON ad.address_id=c.pickup_address_id
JOIN bookbridge.genres g ON g.genre_id=b.genre_id
JOIN bookbridge.languages lg ON lg.language_id=b.language_id
WHERE c.is_active AND u.is_active;
COMMENT ON VIEW bookbridge.public_catalog IS 'Öffentliche Angebote ohne private Namen, E-Mail, Straße, genaue Koordinaten oder Dokumentpfade.';
GRANT USAGE ON SCHEMA bookbridge TO bookbridge_reader,bookbridge_backend;
GRANT SELECT ON bookbridge.public_catalog TO bookbridge_reader,bookbridge_backend;
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT p.oid::regprocedure AS signature
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='bookbridge' AND p.prokind='f' AND p.proname=ANY(ARRAY[
  'create_request','accept_request','propose_days','decide_proposal',
  'request_extension','decide_extension','receive_pickup','start_return',
  'confirm_return','cancel_request','reject_request','create_postage',
  'report_postage','confirm_postage','prepare_shipment','send_shipment',
  'receive_shipment','review_loan','set_offer_active','set_user_active'])
 LOOP EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO bookbridge_backend',r.signature); END LOOP;
END $$;
COMMIT;
