-- BookBridge Phase 2: cross-table integrity, immutable history and deferred invariants.
-- Actor authorization lives in the restricted workflow API (03_workflows.sql).
-- A caller-controlled session variable is deliberately not used as authentication.
BEGIN;
SET LOCAL search_path=bookbridge,pg_catalog;
SET LOCAL TIME ZONE 'Europe/Berlin';

CREATE FUNCTION bookbridge.address_snapshot(p_address_id bigint) RETURNS text
LANGUAGE sql STABLE STRICT SET search_path=pg_catalog,bookbridge AS $$
 SELECT u.first_name||' '||u.last_name||E'\n'||a.street||E'\n'||a.postal_code||' '||a.city||E'\n'||a.country_code
 FROM bookbridge.addresses a JOIN bookbridge.users u ON u.user_id=a.user_id
 WHERE a.address_id=p_address_id
$$;
COMMENT ON FUNCTION bookbridge.address_snapshot(bigint) IS 'Formats a private, complete address at agreement/preparation time; stored snapshots never follow profile edits.';

CREATE FUNCTION bookbridge.tg_immutable_fields() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE f text;
BEGIN
 FOREACH f IN ARRAY TG_ARGV LOOP
   IF (to_jsonb(NEW)->f) IS DISTINCT FROM (to_jsonb(OLD)->f) THEN
     RAISE EXCEPTION 'Immutable field %.%',TG_TABLE_NAME,f USING ERRCODE='23514';
   END IF;
 END LOOP;
 RETURN NEW;
END $$;

-- The identity and historical creation time of every entity are immutable.
DO $$
DECLARE t record; args text;
BEGIN
 FOR t IN SELECT c.table_name, string_agg(quote_literal(c.column_name),',' ORDER BY c.ordinal_position) AS names
  FROM information_schema.columns c
  WHERE c.table_schema='bookbridge' AND (c.column_name IN ('created_at') OR c.is_identity='YES')
  GROUP BY c.table_name LOOP
  EXECUTE format('CREATE TRIGGER aa_immutable_identity BEFORE UPDATE ON bookbridge.%I FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields(%s)',t.table_name,t.names);
 END LOOP;
END $$;
CREATE TRIGGER aa_address_owner BEFORE UPDATE ON bookbridge.addresses FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('user_id');
CREATE TRIGGER aa_copy_owner_book BEFORE UPDATE ON bookbridge.book_copies FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('owner_id','book_id');
CREATE TRIGGER aa_slot_copy BEFORE UPDATE ON bookbridge.pickup_slots FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('copy_id');
CREATE TRIGGER aa_author_assignment_identity BEFORE UPDATE ON bookbridge.book_authors FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('book_id','author_id');
CREATE TRIGGER aa_loan_request BEFORE UPDATE ON bookbridge.loans FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('copy_id','borrower_id','handover_mode','requested_days','requested_at');
CREATE TRIGGER aa_proposal_request BEFORE UPDATE ON bookbridge.loan_proposals FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('loan_id','proposed_by_user_id','proposed_days','proposed_at');
CREATE TRIGGER aa_extension_request BEFORE UPDATE ON bookbridge.loan_extensions FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('loan_id','extra_days','requested_at');
CREATE TRIGGER aa_payment_loan BEFORE UPDATE ON bookbridge.payments FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('loan_id');
CREATE TRIGGER aa_shipment_identity BEFORE UPDATE ON bookbridge.shipments FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('loan_id','direction','sender_address_id','recipient_address_id','sender_address_snapshot','recipient_address_snapshot','prepared_at');
CREATE TRIGGER aa_notification_identity BEFORE UPDATE ON bookbridge.notifications FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('recipient_user_id','loan_id','channel','message');
CREATE TRIGGER aa_document_identity BEFORE UPDATE ON bookbridge.generated_documents FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('loan_id','shipment_id','recipient_user_id','document_type');
CREATE TRIGGER aa_review_identity BEFORE UPDATE ON bookbridge.reviews FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_immutable_fields('loan_id','reviewer_id');

CREATE FUNCTION bookbridge.tg_minimum_author() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE b bigint;
BEGIN
 FOR b IN SELECT DISTINCT x FROM unnest(CASE WHEN TG_TABLE_NAME='books' THEN ARRAY[COALESCE(NEW.book_id,OLD.book_id)] ELSE ARRAY[CASE WHEN TG_OP<>'DELETE' THEN NEW.book_id END,CASE WHEN TG_OP<>'INSERT' THEN OLD.book_id END] END) x WHERE x IS NOT NULL LOOP
   IF EXISTS(SELECT 1 FROM bookbridge.books WHERE book_id=b)
      AND NOT EXISTS(SELECT 1 FROM bookbridge.book_authors WHERE book_id=b) THEN
     RAISE EXCEPTION 'R03: book % requires at least one author at transaction end',b USING ERRCODE='23514';
   END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE FUNCTION bookbridge.tg_lock_author_book() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
BEGIN
 PERFORM 1 FROM bookbridge.books WHERE book_id IN (CASE WHEN TG_OP<>'DELETE' THEN NEW.book_id END, CASE WHEN TG_OP<>'INSERT' THEN OLD.book_id END) ORDER BY book_id FOR UPDATE;
 RETURN COALESCE(NEW,OLD);
END $$;
CREATE TRIGGER ba_lock_author_book BEFORE INSERT OR UPDATE OR DELETE ON bookbridge.book_authors FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_lock_author_book();
CREATE CONSTRAINT TRIGGER zz_book_minimum_author AFTER INSERT OR UPDATE ON bookbridge.books DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_minimum_author();
CREATE CONSTRAINT TRIGGER zz_assignment_minimum_author AFTER INSERT OR UPDATE OR DELETE ON bookbridge.book_authors DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_minimum_author();

CREATE FUNCTION bookbridge.validate_copy(p_copy bigint) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE c bookbridge.book_copies%ROWTYPE; a bookbridge.addresses%ROWTYPE;
BEGIN
 SELECT * INTO c FROM bookbridge.book_copies WHERE copy_id=p_copy;
 IF NOT FOUND THEN RETURN; END IF;
 IF c.pickup_address_id IS NOT NULL THEN
  SELECT * INTO a FROM bookbridge.addresses WHERE address_id=c.pickup_address_id;
  IF a.user_id IS DISTINCT FROM c.owner_id THEN RAISE EXCEPTION 'R02: copy address must belong to owner' USING ERRCODE='23514'; END IF;
 END IF;
 IF c.is_active THEN
  IF a.latitude IS NULL OR a.longitude IS NULL OR NOT EXISTS(SELECT 1 FROM bookbridge.users WHERE user_id=c.owner_id AND is_active) THEN
   RAISE EXCEPTION 'R02/R03: active copy requires active owner and owned geocoded address' USING ERRCODE='23514';
  END IF;
  IF c.allow_pickup AND NOT EXISTS(SELECT 1 FROM bookbridge.pickup_slots WHERE copy_id=c.copy_id AND is_active) THEN
   RAISE EXCEPTION 'R07: active pickup offer requires an active weekly slot' USING ERRCODE='23514';
  END IF;
 END IF;
END $$;
CREATE FUNCTION bookbridge.tg_validate_copy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE id bigint;
BEGIN
 IF TG_TABLE_NAME='book_copies' THEN PERFORM bookbridge.validate_copy(COALESCE(NEW.copy_id,OLD.copy_id));
 ELSIF TG_TABLE_NAME='pickup_slots' THEN PERFORM bookbridge.validate_copy(COALESCE(NEW.copy_id,OLD.copy_id));
 ELSIF TG_TABLE_NAME='addresses' THEN
  FOR id IN SELECT copy_id FROM bookbridge.book_copies WHERE pickup_address_id=COALESCE(NEW.address_id,OLD.address_id) LOOP PERFORM bookbridge.validate_copy(id); END LOOP;
 ELSIF TG_TABLE_NAME='users' THEN
  FOR id IN SELECT copy_id FROM bookbridge.book_copies WHERE owner_id=COALESCE(NEW.user_id,OLD.user_id) LOOP PERFORM bookbridge.validate_copy(id); END LOOP;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_copy_consistent AFTER INSERT OR UPDATE ON bookbridge.book_copies DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_validate_copy();
CREATE CONSTRAINT TRIGGER zz_slot_copy_consistent AFTER INSERT OR UPDATE OR DELETE ON bookbridge.pickup_slots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_validate_copy();
CREATE CONSTRAINT TRIGGER zz_address_copy_consistent AFTER UPDATE ON bookbridge.addresses DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_validate_copy();
CREATE CONSTRAINT TRIGGER zz_user_copy_consistent AFTER UPDATE ON bookbridge.users DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_validate_copy();

CREATE FUNCTION bookbridge.tg_deactivate_user_offers() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
BEGIN
 IF OLD.is_active AND NOT NEW.is_active THEN UPDATE bookbridge.book_copies SET is_active=false WHERE owner_id=NEW.user_id AND is_active; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ba_deactivate_offers AFTER UPDATE OF is_active ON bookbridge.users FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_deactivate_user_offers();

CREATE FUNCTION bookbridge.tg_copy_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE active_owner boolean; address_owner bigint; lat numeric; lon numeric;
BEGIN
 IF NEW.pickup_address_id IS NOT NULL THEN
  SELECT user_id,latitude,longitude INTO address_owner,lat,lon FROM bookbridge.addresses WHERE address_id=NEW.pickup_address_id FOR SHARE;
  IF address_owner IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'R02: copy address must belong to owner' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.is_active THEN
  -- Share locks make activation serialize with account/address changes. The
  -- deferred validator alone would otherwise admit a write-skew race.
  SELECT is_active INTO active_owner FROM bookbridge.users WHERE user_id=NEW.owner_id FOR SHARE;
  IF active_owner IS DISTINCT FROM true OR lat IS NULL OR lon IS NULL THEN RAISE EXCEPTION 'R02/R03: activation needs active owner and owned geocoded address' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ba_copy_guard BEFORE INSERT OR UPDATE ON bookbridge.book_copies FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_copy_guard();

CREATE FUNCTION bookbridge.tg_slot_overlap() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
BEGIN
 -- Parent lock serializes competing slot inserts even when neither row existed.
 PERFORM 1 FROM bookbridge.book_copies WHERE copy_id=NEW.copy_id FOR UPDATE;
 IF NEW.is_active AND EXISTS(SELECT 1 FROM bookbridge.pickup_slots s WHERE s.copy_id=NEW.copy_id AND s.weekday=NEW.weekday AND s.is_active AND s.slot_id<>NEW.slot_id AND s.start_time<NEW.end_time AND NEW.start_time<s.end_time) THEN
  RAISE EXCEPTION 'R07: active pickup slots overlap' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ba_slot_overlap BEFORE INSERT OR UPDATE ON bookbridge.pickup_slots FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_slot_overlap();

CREATE FUNCTION bookbridge.tg_loan_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE c bookbridge.book_copies%ROWTYPE; s bookbridge.pickup_slots%ROWTYPE; f text; local_start timestamp; local_end timestamp;
BEGIN
 IF TG_OP='INSERT' AND NEW.status<>'requested' THEN RAISE EXCEPTION 'R16: new loans must start requested' USING ERRCODE='23514'; END IF;
 SELECT * INTO c FROM bookbridge.book_copies WHERE copy_id=NEW.copy_id;
 IF c.owner_id=NEW.borrower_id THEN RAISE EXCEPTION 'R05: self-borrowing is forbidden' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF OLD.status<>NEW.status AND NOT (
   (OLD.status='requested' AND NEW.status IN ('accepted','rejected','cancelled')) OR
   (OLD.status='accepted' AND NEW.status IN ('outbound','active','cancelled')) OR
   (OLD.status='outbound' AND NEW.status='active') OR
   (OLD.status='active' AND NEW.status='returning') OR
   (OLD.status='returning' AND NEW.status='completed')) THEN
    RAISE EXCEPTION 'R16: illegal loan transition % -> %',OLD.status,NEW.status USING ERRCODE='23514';
  END IF;
  IF OLD.status IN ('rejected','cancelled','completed') AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'R20: terminal loan history is immutable' USING ERRCODE='23514'; END IF;
  FOREACH f IN ARRAY ARRAY['accepted_at','agreed_days','max_loan_days_snapshot','pickup_slot_id','pickup_start_at','pickup_end_at','pickup_address_snapshot','received_at','return_started_at','completed_at','rejected_at','cancelled_at','cancelled_by_user_id'] LOOP
   IF to_jsonb(OLD)->f<>'null'::jsonb AND (to_jsonb(NEW)->f) IS DISTINCT FROM (to_jsonb(OLD)->f) THEN RAISE EXCEPTION 'R20: confirmed loan field % is immutable',f USING ERRCODE='23514'; END IF;
  END LOOP;
  IF OLD.status='accepted' AND NEW.status='active' AND NEW.handover_mode<>'pickup' THEN RAISE EXCEPTION 'Shipping receipt requires outbound state' USING ERRCODE='23514'; END IF;
  IF NEW.status='cancelled' AND NEW.cancelled_by_user_id NOT IN (c.owner_id,NEW.borrower_id) THEN RAISE EXCEPTION 'Cancellation actor must be a participant' USING ERRCODE='23514'; END IF;
  IF OLD.status='requested' AND NEW.status='cancelled' AND NEW.cancelled_by_user_id<>NEW.borrower_id THEN RAISE EXCEPTION 'Only borrower withdraws an open request' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='INSERT' OR (TG_OP='UPDATE' AND OLD.status='requested' AND NEW.status='accepted') THEN
  SELECT * INTO c FROM bookbridge.book_copies WHERE copy_id=NEW.copy_id FOR UPDATE;
  PERFORM bookbridge.validate_copy(c.copy_id);
  IF NOT c.is_active OR NOT EXISTS(SELECT 1 FROM bookbridge.users WHERE user_id=c.owner_id AND is_active) OR NOT EXISTS(SELECT 1 FROM bookbridge.users WHERE user_id=NEW.borrower_id AND is_active) THEN RAISE EXCEPTION 'R01/R05: active offer and active participants required' USING ERRCODE='23514'; END IF;
  IF (NEW.handover_mode='pickup' AND NOT c.allow_pickup) OR (NEW.handover_mode='shipping' AND NOT c.allow_shipping) THEN RAISE EXCEPTION 'R05: handover mode not offered' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' AND EXISTS(SELECT 1 FROM bookbridge.loans WHERE copy_id=NEW.copy_id AND status IN ('accepted','outbound','active','returning')) THEN RAISE EXCEPTION 'R05: new requests require an available copy' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' AND NEW.requested_days>c.max_loan_days THEN RAISE EXCEPTION 'R05: requested duration exceeds offer maximum' USING ERRCODE='23514'; END IF;
  IF NEW.status='accepted' THEN
   IF NEW.max_loan_days_snapshot IS DISTINCT FROM c.max_loan_days OR NEW.agreed_days>c.max_loan_days THEN RAISE EXCEPTION 'R06: acceptance must snapshot current offer maximum' USING ERRCODE='23514'; END IF;
   IF NEW.handover_mode='pickup' THEN
    SELECT * INTO s FROM bookbridge.pickup_slots WHERE slot_id=NEW.pickup_slot_id FOR SHARE;
    local_start:=NEW.pickup_start_at AT TIME ZONE 'Europe/Berlin'; local_end:=NEW.pickup_end_at AT TIME ZONE 'Europe/Berlin';
    IF s.slot_id IS NULL OR s.copy_id<>NEW.copy_id OR NOT s.is_active OR extract(isodow FROM local_start)<>s.weekday OR local_start::date<>local_end::date OR local_start::time<s.start_time OR local_end::time>s.end_time THEN RAISE EXCEPTION 'R07: pickup appointment must fit an active slot of the copy' USING ERRCODE='23514'; END IF;
    IF NEW.pickup_address_snapshot IS DISTINCT FROM bookbridge.address_snapshot(c.pickup_address_id) THEN RAISE EXCEPTION 'R08: pickup address snapshot must match agreement-time address' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ba_loan_guard BEFORE INSERT OR UPDATE ON bookbridge.loans FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_loan_guard();

CREATE FUNCTION bookbridge.tg_loan_child_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE l bookbridge.loans%ROWTYPE; owner bigint; sender bigint; recipient bigint; maximum integer; f text;
BEGIN
 IF TG_TABLE_NAME='notifications' AND COALESCE(NEW.loan_id,OLD.loan_id) IS NULL THEN RETURN COALESCE(NEW,OLD); END IF;
 SELECT * INTO l FROM bookbridge.loans WHERE loan_id=COALESCE(NEW.loan_id,OLD.loan_id) FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Referenced loan does not exist' USING ERRCODE='23503'; END IF;
 SELECT owner_id,max_loan_days INTO owner,maximum FROM bookbridge.book_copies WHERE copy_id=l.copy_id;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'R20: loan child history cannot be deleted' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='loan_proposals' THEN
  IF NEW.proposed_by_user_id<>owner THEN RAISE EXCEPTION 'R09: only owner proposes an alternative duration' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' AND (l.status<>'requested' OR NEW.status<>'pending' OR NEW.proposed_days>maximum OR NEW.proposed_at<l.requested_at) THEN RAISE EXCEPTION 'R09: invalid new duration proposal' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN
   IF OLD.status<>'pending' OR NEW.status='pending' THEN RAISE EXCEPTION 'R20: decided proposals are immutable' USING ERRCODE='23514'; END IF;
   IF NEW.decided_by_user_id NOT IN (owner,l.borrower_id) OR (NEW.status IN ('accepted','rejected') AND NEW.decided_by_user_id<>l.borrower_id) THEN RAISE EXCEPTION 'R09: invalid proposal decision participant' USING ERRCODE='23514'; END IF;
   IF NEW.status='accepted' AND NEW.proposed_days>maximum THEN RAISE EXCEPTION 'R05: proposed duration exceeds current offer maximum' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='loan_extensions' THEN
  IF TG_OP='INSERT' AND (l.status<>'active' OR NEW.status<>'pending' OR NEW.requested_at<l.received_at) THEN RAISE EXCEPTION 'R10: extensions start pending during an active loan' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN
   IF OLD.status<>'pending' OR NEW.status='pending' THEN RAISE EXCEPTION 'R20: decided extensions are immutable' USING ERRCODE='23514'; END IF;
   IF NEW.decided_by_user_id NOT IN (owner,l.borrower_id) OR (NEW.status IN ('approved','rejected') AND NEW.decided_by_user_id<>owner) OR (NEW.status='withdrawn' AND NEW.decided_by_user_id<>l.borrower_id) THEN RAISE EXCEPTION 'R10: invalid extension decision participant' USING ERRCODE='23514'; END IF;
   IF NEW.status IN ('approved','rejected') AND l.status<>'active' THEN RAISE EXCEPTION 'R10: extension decision requires active loan' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='payments' THEN
  IF l.handover_mode<>'shipping' OR l.accepted_at IS NULL THEN RAISE EXCEPTION 'R11: postage belongs to an accepted shipping loan' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' AND (l.status<>'accepted' OR NEW.status<>'pending' OR NEW.created_at<l.accepted_at) THEN RAISE EXCEPTION 'R11: postage starts pending before shipment' USING ERRCODE='23514'; END IF;
  IF NEW.confirmed_by_user_id IS NOT NULL AND NEW.confirmed_by_user_id<>owner THEN RAISE EXCEPTION 'R11: only owner confirms postage' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN
   IF OLD.status IN ('confirmed','cancelled') THEN RAISE EXCEPTION 'R20: confirmed/cancelled postage is immutable' USING ERRCODE='23514'; END IF;
   IF NOT ((OLD.status='pending' AND NEW.status IN ('reported','cancelled')) OR (OLD.status='reported' AND NEW.status IN ('confirmed','cancelled'))) THEN RAISE EXCEPTION 'R11: illegal postage transition' USING ERRCODE='23514'; END IF;
   IF OLD.outbound_fee<>NEW.outbound_fee OR OLD.return_fee<>NEW.return_fee OR OLD.currency<>NEW.currency OR (OLD.reported_at IS NOT NULL AND OLD.reported_at IS DISTINCT FROM NEW.reported_at) THEN RAISE EXCEPTION 'R20: postage amounts and recorded report are immutable' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='shipments' THEN
  IF l.handover_mode<>'shipping' THEN RAISE EXCEPTION 'R13: shipment requires shipping loan' USING ERRCODE='23514'; END IF;
  sender:=CASE WHEN NEW.direction='outbound' THEN owner ELSE l.borrower_id END;
  recipient:=CASE WHEN NEW.direction='outbound' THEN l.borrower_id ELSE owner END;
  IF TG_OP='INSERT' THEN
   IF NEW.status<>'prepared' OR (NEW.direction='outbound' AND l.status<>'accepted') OR (NEW.direction='return' AND l.status<>'active') OR NEW.prepared_at<COALESCE(l.received_at,l.accepted_at) THEN RAISE EXCEPTION 'R14: shipment preparation requires accepted outbound/active return' USING ERRCODE='23514'; END IF;
   IF NOT EXISTS(SELECT 1 FROM bookbridge.addresses WHERE address_id=NEW.sender_address_id AND user_id=sender) OR NOT EXISTS(SELECT 1 FROM bookbridge.addresses WHERE address_id=NEW.recipient_address_id AND user_id=recipient) THEN RAISE EXCEPTION 'R13: shipment addresses must belong to sender and recipient' USING ERRCODE='23514'; END IF;
   IF NEW.sender_address_snapshot IS DISTINCT FROM bookbridge.address_snapshot(NEW.sender_address_id) OR NEW.recipient_address_snapshot IS DISTINCT FROM bookbridge.address_snapshot(NEW.recipient_address_id) THEN RAISE EXCEPTION 'R13: immutable shipment snapshots must match preparation-time addresses' USING ERRCODE='23514'; END IF;
  ELSIF NEW IS DISTINCT FROM OLD THEN
   IF NOT ((OLD.status='prepared' AND NEW.status='sent') OR (OLD.status='sent' AND NEW.status='received')) THEN RAISE EXCEPTION 'R14: illegal shipment transition' USING ERRCODE='23514'; END IF;
   FOREACH f IN ARRAY ARRAY['sent_at','received_at','receipt_confirmed_by'] LOOP
    IF to_jsonb(OLD)->f<>'null'::jsonb AND (to_jsonb(NEW)->f) IS DISTINCT FROM (to_jsonb(OLD)->f) THEN RAISE EXCEPTION 'R20: confirmed shipment events are immutable' USING ERRCODE='23514'; END IF;
   END LOOP;
  END IF;
  IF NEW.status='received' AND NEW.receipt_confirmed_by<>recipient THEN RAISE EXCEPTION 'R14: only recipient confirms shipment receipt' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='reviews' THEN
  IF l.status<>'completed' OR NEW.reviewer_id NOT IN(owner,l.borrower_id) OR NEW.created_at<l.completed_at THEN RAISE EXCEPTION 'R17: review requires completed loan and a participant' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='notifications' THEN
  IF NEW.recipient_user_id NOT IN(owner,l.borrower_id) THEN RAISE EXCEPTION 'R18: notification recipient must be a participant' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='generated_documents' THEN
  IF NEW.recipient_user_id NOT IN(owner,l.borrower_id) THEN RAISE EXCEPTION 'R18: document recipient must be a participant' USING ERRCODE='23514'; END IF;
  IF NEW.shipment_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM bookbridge.shipments WHERE shipment_id=NEW.shipment_id AND loan_id=NEW.loan_id) THEN RAISE EXCEPTION 'R18: document shipment belongs to another loan' USING ERRCODE='23514'; END IF;
  IF (NEW.document_type='loan_confirmation' AND l.accepted_at IS NULL) OR (NEW.document_type='shipment_summary' AND NEW.shipment_id IS NULL) OR (NEW.document_type='return_confirmation' AND l.status<>'completed') THEN RAISE EXCEPTION 'R18: document prerequisite not fulfilled' USING ERRCODE='23514'; END IF;
  IF NEW.status='created' AND (NEW.storage_path~'(^/|^[A-Za-z]:|(^|/)\.\.(/|$)|(^|/)(public|frontend|wwwroot)(/|$))') THEN RAISE EXCEPTION 'R18: use a relative document key outside the public web directory' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='created' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'R20: created document history is immutable' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['loan_proposals','loan_extensions','payments','shipments','reviews','generated_documents'] LOOP
  EXECUTE format('CREATE TRIGGER ba_loan_child_guard BEFORE INSERT OR UPDATE OR DELETE ON bookbridge.%I FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_loan_child_guard()',t);
 END LOOP;
END $$;
-- General notifications without a loan reference have no participant restriction.
CREATE TRIGGER ba_notification_loan_guard BEFORE INSERT OR UPDATE OR DELETE ON bookbridge.notifications FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_loan_child_guard();

CREATE FUNCTION bookbridge.validate_loan(p_loan bigint) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
DECLARE l bookbridge.loans%ROWTYPE; extra integer; base date; s bookbridge.shipments%ROWTYPE; p bookbridge.payments%ROWTYPE;
BEGIN
 SELECT * INTO l FROM bookbridge.loans WHERE loan_id=p_loan FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT COALESCE(sum(extra_days),0)::integer INTO extra FROM bookbridge.loan_extensions WHERE loan_id=p_loan AND status='approved';
 IF l.agreed_days+extra>l.max_loan_days_snapshot THEN RAISE EXCEPTION 'R06/R10: total agreed duration exceeds frozen maximum' USING ERRCODE='23514'; END IF;
 IF l.received_at IS NOT NULL THEN
  base:=(l.received_at AT TIME ZONE 'Europe/Berlin')::date+l.agreed_days;
  IF l.due_date IS DISTINCT FROM base+extra THEN RAISE EXCEPTION 'R06: due date must equal Berlin receipt date plus approved total duration' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM (SELECT old_due_date,base+COALESCE(sum(extra_days) OVER (ORDER BY old_due_date,extension_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)::integer AS expected FROM bookbridge.loan_extensions WHERE loan_id=p_loan AND status='approved') x WHERE old_due_date<>expected) THEN RAISE EXCEPTION 'R10: approved extension history must form an unbroken due-date chain' USING ERRCODE='23514'; END IF;
 END IF;
 IF l.status<>'requested' AND EXISTS(SELECT 1 FROM bookbridge.loan_proposals WHERE loan_id=p_loan AND status='pending') THEN RAISE EXCEPTION 'R09: closed request retains pending proposal' USING ERRCODE='23514'; END IF;
 IF l.status<>'active' AND EXISTS(SELECT 1 FROM bookbridge.loan_extensions WHERE loan_id=p_loan AND status='pending') THEN RAISE EXCEPTION 'R10: only active loans may retain pending extensions' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM bookbridge.loan_proposals WHERE loan_id=p_loan AND status='accepted' AND (l.accepted_at IS NULL OR proposed_days<>l.agreed_days OR decided_at<>l.accepted_at)) THEN RAISE EXCEPTION 'R09: accepted proposal and loan agreement must match atomically' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM bookbridge.loan_proposals WHERE loan_id=p_loan AND status='withdrawn' AND decided_by_user_id=l.borrower_id AND (l.status<>'cancelled' OR decided_at IS DISTINCT FROM l.cancelled_at)) THEN RAISE EXCEPTION 'R09: borrower closes a proposal only by withdrawing the whole request' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM bookbridge.loan_proposals WHERE loan_id=p_loan AND status='accepted')>1 THEN RAISE EXCEPTION 'R09: at most one proposal can be accepted' USING ERRCODE='23514'; END IF;
 IF l.accepted_at IS NOT NULL AND l.agreed_days<>l.requested_days AND NOT EXISTS(SELECT 1 FROM bookbridge.loan_proposals WHERE loan_id=p_loan AND status='accepted' AND proposed_days=l.agreed_days) THEN RAISE EXCEPTION 'R09: changed agreement duration requires an accepted counterproposal' USING ERRCODE='23514'; END IF;
 SELECT * INTO p FROM bookbridge.payments WHERE loan_id=p_loan;
 IF l.status='cancelled' AND p.status IN ('pending','reported') THEN RAISE EXCEPTION 'R12: pending/reported postage must be cancelled atomically' USING ERRCODE='23514'; END IF;
 IF p.status='cancelled' AND l.status<>'cancelled' THEN RAISE EXCEPTION 'R12: postage cancellation requires cancelled loan' USING ERRCODE='23514'; END IF;
 IF l.status='cancelled' AND EXISTS(SELECT 1 FROM bookbridge.shipments WHERE loan_id=p_loan AND status<>'prepared') THEN RAISE EXCEPTION 'R12: dispatched loans cannot be cancelled' USING ERRCODE='23514'; END IF;
 IF l.handover_mode='shipping' THEN
  SELECT * INTO s FROM bookbridge.shipments WHERE loan_id=p_loan AND direction='outbound';
  IF l.status='outbound' AND (s.shipment_id IS NULL OR s.status<>'sent') THEN RAISE EXCEPTION 'R14: outbound loan needs a sent outbound shipment' USING ERRCODE='23514'; END IF;
  IF l.status IN ('active','returning','completed') AND (s.shipment_id IS NULL OR s.status<>'received' OR s.received_at IS DISTINCT FROM l.received_at) THEN RAISE EXCEPTION 'R14: shipping loan receipt and shipment receipt must match' USING ERRCODE='23514'; END IF;
  IF s.status IN ('sent','received') AND (p.payment_id IS NULL OR p.status<>'confirmed' OR p.confirmed_at>s.sent_at) THEN RAISE EXCEPTION 'R11: postage must be confirmed before outbound dispatch' USING ERRCODE='23514'; END IF;
  IF s.status='sent' AND l.status<>'outbound' THEN RAISE EXCEPTION 'R14: sent outbound shipment requires outbound loan' USING ERRCODE='23514'; END IF;
  IF s.status='received' AND l.status NOT IN ('active','returning','completed') THEN RAISE EXCEPTION 'R14: received outbound shipment requires received loan' USING ERRCODE='23514'; END IF;
  SELECT * INTO s FROM bookbridge.shipments WHERE loan_id=p_loan AND direction='return';
  IF l.status='returning' AND (s.shipment_id IS NULL OR s.status<>'sent' OR s.sent_at IS DISTINCT FROM l.return_started_at) THEN RAISE EXCEPTION 'R14: return dispatch and loan return start must match' USING ERRCODE='23514'; END IF;
  IF l.status='completed' AND (s.shipment_id IS NULL OR s.status<>'received' OR s.sent_at IS DISTINCT FROM l.return_started_at OR s.received_at IS DISTINCT FROM l.completed_at) THEN RAISE EXCEPTION 'R14: return receipt and completion must match' USING ERRCODE='23514'; END IF;
  IF s.status='sent' AND l.status<>'returning' THEN RAISE EXCEPTION 'R14: sent return requires returning loan' USING ERRCODE='23514'; END IF;
  IF s.status='received' AND l.status<>'completed' THEN RAISE EXCEPTION 'R14: received return requires completed loan' USING ERRCODE='23514'; END IF;
 END IF;
END $$;
CREATE FUNCTION bookbridge.tg_validate_loan() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
BEGIN PERFORM bookbridge.validate_loan(COALESCE(NEW.loan_id,OLD.loan_id)); RETURN NULL; END $$;
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['loans','loan_proposals','loan_extensions','payments','shipments'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER zz_loan_consistent AFTER INSERT OR UPDATE OR DELETE ON bookbridge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_validate_loan()',t);
 END LOOP;
END $$;
CREATE FUNCTION bookbridge.tg_preserve_loan() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,bookbridge AS $$
BEGIN RAISE EXCEPTION 'R04/R20: loan history cannot be deleted' USING ERRCODE='23514'; END $$;
CREATE TRIGGER aa_preserve_loan BEFORE DELETE ON bookbridge.loans FOR EACH ROW EXECUTE FUNCTION bookbridge.tg_preserve_loan();

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA bookbridge FROM PUBLIC;
COMMIT;
