-- BookBridge Phase 2 | Controlled domain workflows (PostgreSQL 17+).
-- Explicit actor IDs represent identities verified by a trusted application.
-- They are not authentication tokens. Do not expose database access or these
-- functions directly to untrusted clients. PUBLIC execution is revoked below.
-- Functions use SECURITY DEFINER with a fixed trusted search path. The optional role script grants only the public domain API to a trusted backend.
-- p_at supports reproducible fixtures; event chronology is always validated.
BEGIN;
SET LOCAL search_path = bookbridge, pg_catalog;

CREATE FUNCTION _actor(p_actor bigint, p_active boolean DEFAULT false)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE u users%ROWTYPE;
BEGIN
  SELECT * INTO u FROM users WHERE user_id = p_actor FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown actor %', p_actor USING ERRCODE='42501'; END IF;
  IF p_active AND NOT u.is_active THEN
    RAISE EXCEPTION 'Actor % is inactive', p_actor USING ERRCODE='42501';
  END IF;
END $$;

CREATE FUNCTION _event(p_at timestamptz, p_previous timestamptz)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
BEGIN
  IF p_at IS NULL OR NOT isfinite(p_at) THEN
    RAISE EXCEPTION 'A finite event timestamp is required' USING ERRCODE='22023';
  END IF;
  IF p_previous IS NOT NULL AND p_at < p_previous THEN
    RAISE EXCEPTION 'Event % predates previous event %',p_at,p_previous USING ERRCODE='22023';
  END IF;
END $$;

CREATE FUNCTION _lock_loan(p_loan bigint)
RETURNS loans LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE;
BEGIN
  SELECT * INTO l FROM loans WHERE loan_id=p_loan FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown loan %',p_loan USING ERRCODE='22023'; END IF;
  RETURN l;
END $$;

CREATE FUNCTION _loan_event(p_loan bigint, p_at timestamptz)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE last_event timestamptz;
BEGIN
  -- The loan row must already be locked by the caller. Child events therefore
  -- serialize with parent decisions, receipt and cancellation.
  SELECT max(t) INTO last_event FROM (
    SELECT greatest(requested_at,accepted_at,received_at,return_started_at,
                    completed_at,rejected_at,cancelled_at) t FROM loans WHERE loan_id=p_loan
    UNION ALL SELECT greatest(proposed_at,decided_at) FROM loan_proposals WHERE loan_id=p_loan
    UNION ALL SELECT greatest(requested_at,decided_at) FROM loan_extensions WHERE loan_id=p_loan
    UNION ALL SELECT greatest(created_at,reported_at,confirmed_at) FROM payments WHERE loan_id=p_loan
    UNION ALL SELECT greatest(prepared_at,sent_at,received_at) FROM shipments WHERE loan_id=p_loan
  ) events;
  PERFORM _event(p_at,last_event);
END $$;

CREATE FUNCTION _emit(p_loan bigint,p_message text,p_document text DEFAULT NULL,
                      p_shipment bigint DEFAULT NULL,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE owner_actor bigint; borrower_actor bigint;
BEGIN
  SELECT c.owner_id,l.borrower_id INTO owner_actor,borrower_actor
  FROM loans l JOIN book_copies c USING(copy_id) WHERE l.loan_id=p_loan;
  INSERT INTO notifications(recipient_user_id,loan_id,channel,message,status,created_at)
  VALUES (owner_actor,p_loan,'in_app',p_message,'queued',p_at),
         (borrower_actor,p_loan,'in_app',p_message,'queued',p_at);
  IF p_document IS NOT NULL THEN
    INSERT INTO generated_documents(loan_id,shipment_id,recipient_user_id,document_type,status,created_at)
    VALUES(p_loan,p_shipment,owner_actor,p_document,'planned',p_at),
          (p_loan,p_shipment,borrower_actor,p_document,'planned',p_at);
  END IF;
END $$;

CREATE FUNCTION create_request(p_actor bigint,p_copy bigint,p_days integer,p_mode text,
                               p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE c book_copies%ROWTYPE; result bigint;
BEGIN
  PERFORM _actor(p_actor,true);
  SELECT * INTO c FROM book_copies WHERE copy_id=p_copy FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown copy %',p_copy USING ERRCODE='22023'; END IF;
  PERFORM _actor(c.owner_id,true);
  PERFORM _event(p_at,c.created_at);
  IF c.owner_id=p_actor THEN RAISE EXCEPTION 'Self borrowing is prohibited' USING ERRCODE='42501'; END IF;
  IF NOT c.is_active OR EXISTS(SELECT 1 FROM loans WHERE copy_id=p_copy AND status IN('accepted','outbound','active','returning')) THEN
    RAISE EXCEPTION 'Copy % is unavailable',p_copy USING ERRCODE='55000';
  END IF;
  IF p_days IS NULL OR p_days<1 OR p_days>c.max_loan_days THEN
    RAISE EXCEPTION 'Requested days must be between 1 and %',c.max_loan_days USING ERRCODE='22023';
  END IF;
  IF p_mode IS NULL OR p_mode NOT IN('pickup','shipping') OR
     (p_mode='pickup' AND NOT c.allow_pickup) OR (p_mode='shipping' AND NOT c.allow_shipping) THEN
    RAISE EXCEPTION 'Handover mode is not offered' USING ERRCODE='22023';
  END IF;
  INSERT INTO loans(copy_id,borrower_id,handover_mode,requested_days,status,requested_at)
  VALUES(p_copy,p_actor,p_mode,p_days,'requested',p_at) RETURNING loan_id INTO result;
  PERFORM _emit(result,'Neue Ausleihanfrage',NULL,NULL,p_at);
  RETURN result;
END $$;

CREATE FUNCTION _accept_locked(p_actor bigint,p_loan bigint,p_days integer,p_slot bigint,
                               p_start timestamptz,p_end timestamptz,p_at timestamptz)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; c book_copies%ROWTYPE; s pickup_slots%ROWTYPE;
        local_start timestamp; local_end timestamp; snap text;
BEGIN
  l:=_lock_loan(p_loan);
  SELECT * INTO c FROM book_copies WHERE copy_id=l.copy_id FOR UPDATE;
  PERFORM _actor(p_actor,true); PERFORM _actor(c.owner_id,true); PERFORM _actor(l.borrower_id,true);
  IF p_actor NOT IN(c.owner_id,l.borrower_id) THEN RAISE EXCEPTION 'Actor is not a participant' USING ERRCODE='42501'; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.status<>'requested' THEN RAISE EXCEPTION 'Only requested loans can be accepted' USING ERRCODE='55000'; END IF;
  IF NOT c.is_active OR EXISTS(SELECT 1 FROM loans WHERE copy_id=c.copy_id AND status IN('accepted','outbound','active','returning')) THEN
    RAISE EXCEPTION 'Copy % is unavailable',c.copy_id USING ERRCODE='55000';
  END IF;
  IF p_days IS NULL OR p_days NOT BETWEEN 1 AND c.max_loan_days THEN
    RAISE EXCEPTION 'Agreed days exceed current offer limit' USING ERRCODE='22023';
  END IF;
  IF (l.handover_mode='pickup' AND NOT c.allow_pickup) OR (l.handover_mode='shipping' AND NOT c.allow_shipping) THEN
    RAISE EXCEPTION 'Handover mode is no longer offered' USING ERRCODE='55000';
  END IF;
  IF l.handover_mode='pickup' THEN
    SELECT * INTO s FROM pickup_slots WHERE slot_id=p_slot FOR SHARE;
    IF NOT FOUND OR NOT s.is_active OR s.copy_id<>c.copy_id THEN
      RAISE EXCEPTION 'An active pickup slot of this copy is required' USING ERRCODE='22023';
    END IF;
    IF p_start IS NULL OR p_end IS NULL OR NOT isfinite(p_start) OR NOT isfinite(p_end) OR
       p_start<=p_at OR p_end<=p_start THEN
      RAISE EXCEPTION 'A future, positive pickup appointment is required' USING ERRCODE='22023';
    END IF;
    local_start:=p_start AT TIME ZONE 'Europe/Berlin'; local_end:=p_end AT TIME ZONE 'Europe/Berlin';
    IF local_start::date<>local_end::date OR extract(isodow FROM local_start)<>s.weekday OR
       local_start::time<s.start_time OR local_end::time>s.end_time THEN
      RAISE EXCEPTION 'Appointment does not fit the local weekly pickup window' USING ERRCODE='22023';
    END IF;
    snap:=address_snapshot(c.pickup_address_id);
  ELSE
    IF p_slot IS NOT NULL OR p_start IS NOT NULL OR p_end IS NOT NULL THEN
      RAISE EXCEPTION 'Shipping cannot have pickup fields' USING ERRCODE='22023';
    END IF;
  END IF;
  UPDATE loans SET status='accepted',agreed_days=p_days,max_loan_days_snapshot=c.max_loan_days,
    accepted_at=p_at,pickup_slot_id=p_slot,pickup_start_at=p_start,pickup_end_at=p_end,
    pickup_address_snapshot=snap WHERE loan_id=p_loan;
  PERFORM _emit(p_loan,'Ausleihanfrage angenommen','loan_confirmation',NULL,p_at);
  RETURN p_loan;
END $$;

CREATE FUNCTION accept_request(p_actor bigint,p_loan bigint,p_slot bigint DEFAULT NULL,
                               p_start timestamptz DEFAULT NULL,p_end timestamptz DEFAULT NULL,
                               p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,true);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor<>owner_actor THEN RAISE EXCEPTION 'Only the owner accepts an original request' USING ERRCODE='42501'; END IF;
  IF l.accepted_at IS NOT NULL AND l.agreed_days=l.requested_days AND
     l.pickup_slot_id IS NOT DISTINCT FROM p_slot AND l.pickup_start_at IS NOT DISTINCT FROM p_start AND
     l.pickup_end_at IS NOT DISTINCT FROM p_end THEN RETURN p_loan; END IF;
  IF EXISTS(SELECT 1 FROM loan_proposals WHERE loan_id=p_loan AND status='pending') THEN
    RAISE EXCEPTION 'Resolve the pending counterproposal first' USING ERRCODE='55000';
  END IF;
  RETURN _accept_locked(p_actor,p_loan,l.requested_days,p_slot,p_start,p_end,p_at);
END $$;

CREATE FUNCTION propose_days(p_actor bigint,p_loan bigint,p_days integer,
                             p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; c book_copies%ROWTYPE; result bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,true);
  SELECT * INTO c FROM book_copies WHERE copy_id=l.copy_id FOR SHARE;
  IF p_actor<>c.owner_id THEN RAISE EXCEPTION 'Only the owner can propose days' USING ERRCODE='42501'; END IF;
  PERFORM _actor(l.borrower_id,true); PERFORM _loan_event(p_loan,p_at);
  IF l.status<>'requested' OR NOT c.is_active THEN RAISE EXCEPTION 'A live requested offer is required' USING ERRCODE='55000'; END IF;
  IF p_days IS NULL OR p_days NOT BETWEEN 1 AND c.max_loan_days THEN RAISE EXCEPTION 'Invalid proposed days' USING ERRCODE='22023'; END IF;
  INSERT INTO loan_proposals(loan_id,proposed_by_user_id,proposed_days,status,proposed_at)
  VALUES(p_loan,p_actor,p_days,'pending',p_at) RETURNING proposal_id INTO result;
  PERFORM _emit(p_loan,'Gegenvorschlag zur Leihdauer',NULL,NULL,p_at);
  RETURN result;
END $$;

CREATE FUNCTION decide_proposal(p_actor bigint,p_proposal bigint,p_decision text,
                                p_slot bigint DEFAULT NULL,p_start timestamptz DEFAULT NULL,
                                p_end timestamptz DEFAULT NULL,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; p loan_proposals%ROWTYPE; owner_actor bigint; loan_ref bigint;
BEGIN
  SELECT loan_id INTO loan_ref FROM loan_proposals WHERE proposal_id=p_proposal;
  l:=_lock_loan(loan_ref); PERFORM _actor(p_actor,false);
  SELECT * INTO p FROM loan_proposals WHERE proposal_id=p_proposal FOR UPDATE;
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_decision IS NULL OR p_decision NOT IN('accepted','rejected','withdrawn') THEN RAISE EXCEPTION 'Invalid proposal decision' USING ERRCODE='22023'; END IF;
  IF (p_decision='withdrawn' AND p_actor<>owner_actor) OR
     (p_decision IN('accepted','rejected') AND p_actor<>l.borrower_id) THEN
    RAISE EXCEPTION 'Actor cannot make this proposal decision' USING ERRCODE='42501';
  END IF;
  IF p.status=p_decision AND p.decided_by_user_id=p_actor THEN RETURN p_proposal; END IF;
  PERFORM _loan_event(l.loan_id,p_at);
  IF p.status<>'pending' OR l.status<>'requested' THEN RAISE EXCEPTION 'Proposal is no longer pending' USING ERRCODE='55000'; END IF;
  UPDATE loan_proposals SET status=p_decision,decided_by_user_id=p_actor,decided_at=p_at WHERE proposal_id=p_proposal;
  IF p_decision='accepted' THEN
    PERFORM _accept_locked(p_actor,l.loan_id,p.proposed_days,p_slot,p_start,p_end,p_at);
  ELSE
    PERFORM _emit(l.loan_id,'Gegenvorschlag entschieden: '||p_decision,NULL,NULL,p_at);
  END IF;
  RETURN p_proposal;
END $$;

CREATE FUNCTION request_extension(p_actor bigint,p_loan bigint,p_days integer,
                                  p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; result bigint; used integer;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false); PERFORM _loan_event(p_loan,p_at);
  IF p_actor<>l.borrower_id THEN RAISE EXCEPTION 'Only the borrower requests an extension' USING ERRCODE='42501'; END IF;
  IF l.status<>'active' THEN RAISE EXCEPTION 'Extensions require an active loan' USING ERRCODE='55000'; END IF;
  SELECT coalesce(sum(extra_days),0) INTO used FROM loan_extensions WHERE loan_id=p_loan AND status='approved';
  IF p_days IS NULL OR p_days<1 OR l.agreed_days+used+p_days>l.max_loan_days_snapshot THEN
    RAISE EXCEPTION 'Extension exceeds frozen total duration' USING ERRCODE='22023';
  END IF;
  INSERT INTO loan_extensions(loan_id,extra_days,status,requested_at)
  VALUES(p_loan,p_days,'pending',p_at) RETURNING extension_id INTO result;
  PERFORM _emit(p_loan,'Verlängerung angefragt',NULL,NULL,p_at);
  RETURN result;
END $$;

CREATE FUNCTION decide_extension(p_actor bigint,p_extension bigint,p_decision text,
                                 p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; e loan_extensions%ROWTYPE; owner_actor bigint; loan_ref bigint; used integer;
BEGIN
  SELECT loan_id INTO loan_ref FROM loan_extensions WHERE extension_id=p_extension;
  l:=_lock_loan(loan_ref); PERFORM _actor(p_actor,false);
  SELECT * INTO e FROM loan_extensions WHERE extension_id=p_extension FOR UPDATE;
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_decision IS NULL OR p_decision NOT IN('approved','rejected','withdrawn') THEN RAISE EXCEPTION 'Invalid extension decision' USING ERRCODE='22023'; END IF;
  IF (p_decision='withdrawn' AND p_actor<>l.borrower_id) OR
     (p_decision IN('approved','rejected') AND p_actor<>owner_actor) THEN
    RAISE EXCEPTION 'Actor cannot make this extension decision' USING ERRCODE='42501';
  END IF;
  IF e.status=p_decision AND e.decided_by_user_id=p_actor THEN RETURN p_extension; END IF;
  PERFORM _loan_event(l.loan_id,p_at);
  IF e.status<>'pending' OR l.status<>'active' THEN RAISE EXCEPTION 'Extension is no longer pending' USING ERRCODE='55000'; END IF;
  IF p_decision='approved' THEN
    SELECT coalesce(sum(extra_days),0) INTO used FROM loan_extensions WHERE loan_id=l.loan_id AND status='approved';
    IF l.agreed_days+used+e.extra_days>l.max_loan_days_snapshot THEN RAISE EXCEPTION 'Frozen duration exceeded' USING ERRCODE='22023'; END IF;
    UPDATE loan_extensions SET status=p_decision,decided_by_user_id=p_actor,decided_at=p_at,
      old_due_date=l.due_date,new_due_date=l.due_date+e.extra_days WHERE extension_id=p_extension;
    UPDATE loans SET due_date=l.due_date+e.extra_days WHERE loan_id=l.loan_id;
  ELSE
    UPDATE loan_extensions SET status=p_decision,decided_by_user_id=p_actor,decided_at=p_at WHERE extension_id=p_extension;
  END IF;
  PERFORM _emit(l.loan_id,'Verlängerung entschieden: '||p_decision,NULL,NULL,p_at);
  RETURN p_extension;
END $$;

CREATE FUNCTION _close_extensions(p_loan bigint,p_actor bigint,p_at timestamptz)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
BEGIN
  UPDATE loan_extensions SET status='withdrawn',decided_by_user_id=p_actor,decided_at=p_at
  WHERE loan_id=p_loan AND status='pending';
END $$;

CREATE FUNCTION receive_pickup(p_actor bigint,p_loan bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  IF p_actor<>l.borrower_id THEN RAISE EXCEPTION 'Only the borrower confirms pickup' USING ERRCODE='42501'; END IF;
  IF l.handover_mode<>'pickup' THEN RAISE EXCEPTION 'Not a pickup loan' USING ERRCODE='55000'; END IF;
  IF l.received_at IS NOT NULL THEN RETURN p_loan; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.status<>'accepted' THEN RAISE EXCEPTION 'Pickup requires accepted status' USING ERRCODE='55000'; END IF;
  UPDATE loans SET status='active',received_at=p_at,
    due_date=(p_at AT TIME ZONE 'Europe/Berlin')::date+agreed_days WHERE loan_id=p_loan;
  PERFORM _emit(p_loan,'Persönliche Übergabe bestätigt',NULL,NULL,p_at);
  RETURN p_loan;
END $$;

CREATE FUNCTION start_return(p_actor bigint,p_loan bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  IF p_actor<>l.borrower_id THEN RAISE EXCEPTION 'Only the borrower starts return' USING ERRCODE='42501'; END IF;
  IF l.handover_mode<>'pickup' THEN RAISE EXCEPTION 'Use send_shipment for postal returns' USING ERRCODE='55000'; END IF;
  IF l.return_started_at IS NOT NULL THEN RETURN p_loan; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.status<>'active' THEN RAISE EXCEPTION 'Return requires active status' USING ERRCODE='55000'; END IF;
  PERFORM _close_extensions(p_loan,p_actor,p_at);
  UPDATE loans SET status='returning',return_started_at=p_at WHERE loan_id=p_loan;
  PERFORM _emit(p_loan,'Persönliche Rückgabe begonnen',NULL,NULL,p_at);
  RETURN p_loan;
END $$;

CREATE FUNCTION confirm_return(p_actor bigint,p_loan bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor<>owner_actor THEN RAISE EXCEPTION 'Only the owner confirms return' USING ERRCODE='42501'; END IF;
  IF l.handover_mode<>'pickup' THEN RAISE EXCEPTION 'Use receive_shipment for postal returns' USING ERRCODE='55000'; END IF;
  IF l.completed_at IS NOT NULL THEN RETURN p_loan; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.status<>'returning' THEN RAISE EXCEPTION 'Return must first be started' USING ERRCODE='55000'; END IF;
  UPDATE loans SET status='completed',completed_at=p_at WHERE loan_id=p_loan;
  PERFORM _emit(p_loan,'Rückerhalt bestätigt','return_confirmation',NULL,p_at);
  RETURN p_loan;
END $$;

CREATE FUNCTION cancel_request(p_actor bigint,p_loan bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor NOT IN(owner_actor,l.borrower_id) THEN RAISE EXCEPTION 'Only participants can cancel' USING ERRCODE='42501'; END IF;
  IF l.status='cancelled' AND l.cancelled_by_user_id=p_actor THEN RETURN p_loan; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF (l.status='requested' AND p_actor<>l.borrower_id) OR l.status NOT IN('requested','accepted') OR
     EXISTS(SELECT 1 FROM shipments WHERE loan_id=p_loan AND status IN('sent','received')) THEN
    RAISE EXCEPTION 'Loan cannot be cancelled by this actor in this state' USING ERRCODE='55000';
  END IF;
  UPDATE loan_proposals SET status='withdrawn',decided_by_user_id=p_actor,decided_at=p_at
    WHERE loan_id=p_loan AND status='pending';
  UPDATE payments SET status='cancelled' WHERE loan_id=p_loan AND status IN('pending','reported');
  UPDATE loans SET status='cancelled',cancelled_at=p_at,cancelled_by_user_id=p_actor WHERE loan_id=p_loan;
  PERFORM _emit(p_loan,'Ausleihanfrage storniert',NULL,NULL,p_at);
  RETURN p_loan;
END $$;

CREATE FUNCTION reject_request(p_actor bigint,p_loan bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor<>owner_actor THEN RAISE EXCEPTION 'Only the owner rejects a request' USING ERRCODE='42501'; END IF;
  IF l.status='rejected' THEN RETURN p_loan; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.status<>'requested' THEN RAISE EXCEPTION 'Only requested loans can be rejected' USING ERRCODE='55000'; END IF;
  UPDATE loan_proposals SET status='withdrawn',decided_by_user_id=p_actor,decided_at=p_at
    WHERE loan_id=p_loan AND status='pending';
  UPDATE loans SET status='rejected',rejected_at=p_at WHERE loan_id=p_loan;
  PERFORM _emit(p_loan,'Ausleihanfrage abgelehnt',NULL,NULL,p_at);
  RETURN p_loan;
END $$;

CREATE FUNCTION create_postage(p_actor bigint,p_loan bigint,p_outbound numeric,p_return numeric,
                               p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint; pay payments%ROWTYPE; result bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor<>owner_actor THEN RAISE EXCEPTION 'Only the owner sets postage' USING ERRCODE='42501'; END IF;
  SELECT * INTO pay FROM payments WHERE loan_id=p_loan;
  IF FOUND THEN
    IF pay.outbound_fee=p_outbound AND pay.return_fee=p_return THEN RETURN pay.payment_id; END IF;
    RAISE EXCEPTION 'Postage already exists with different amounts' USING ERRCODE='55000';
  END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.handover_mode<>'shipping' OR l.status<>'accepted' THEN RAISE EXCEPTION 'Postage requires an accepted shipping loan' USING ERRCODE='55000'; END IF;
  IF p_outbound IS NULL OR p_return IS NULL OR
     p_outbound::text IN('NaN','Infinity','-Infinity') OR p_return::text IN('NaN','Infinity','-Infinity') OR
     p_outbound<0 OR p_return<0 OR
     p_outbound<>round(p_outbound,2) OR p_return<>round(p_return,2) THEN
    RAISE EXCEPTION 'Postage requires nonnegative EUR amounts with at most 2 decimals' USING ERRCODE='22023';
  END IF;
  INSERT INTO payments(loan_id,outbound_fee,return_fee,currency,status,created_at)
  VALUES(p_loan,p_outbound,p_return,'EUR','pending',p_at) RETURNING payment_id INTO result;
  PERFORM _emit(p_loan,'Hin- und Rückporto festgelegt',NULL,NULL,p_at);
  RETURN result;
END $$;

CREATE FUNCTION report_postage(p_actor bigint,p_payment bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; pay payments%ROWTYPE; loan_ref bigint;
BEGIN
  SELECT loan_id INTO loan_ref FROM payments WHERE payment_id=p_payment;
  l:=_lock_loan(loan_ref); PERFORM _actor(p_actor,false);
  SELECT * INTO pay FROM payments WHERE payment_id=p_payment FOR UPDATE;
  IF p_actor<>l.borrower_id THEN RAISE EXCEPTION 'Only the borrower reports postage payment' USING ERRCODE='42501'; END IF;
  IF pay.status IN('reported','confirmed') THEN RETURN p_payment; END IF;
  PERFORM _loan_event(l.loan_id,p_at);
  IF pay.status<>'pending' OR l.status<>'accepted' THEN RAISE EXCEPTION 'Postage cannot be reported now' USING ERRCODE='55000'; END IF;
  UPDATE payments SET status='reported',reported_at=p_at WHERE payment_id=p_payment;
  PERFORM _emit(l.loan_id,'Portozahlung gemeldet (Demonstration)',NULL,NULL,p_at);
  RETURN p_payment;
END $$;

CREATE FUNCTION confirm_postage(p_actor bigint,p_payment bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; pay payments%ROWTYPE; owner_actor bigint; loan_ref bigint;
BEGIN
  SELECT loan_id INTO loan_ref FROM payments WHERE payment_id=p_payment;
  l:=_lock_loan(loan_ref); PERFORM _actor(p_actor,false);
  SELECT * INTO pay FROM payments WHERE payment_id=p_payment FOR UPDATE;
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor<>owner_actor THEN RAISE EXCEPTION 'Only the owner confirms postage payment' USING ERRCODE='42501'; END IF;
  IF pay.status='confirmed' THEN RETURN p_payment; END IF;
  PERFORM _loan_event(l.loan_id,p_at);
  IF pay.status<>'reported' OR l.status<>'accepted' THEN RAISE EXCEPTION 'Postage confirmation requires reported payment and accepted loan' USING ERRCODE='55000'; END IF;
  UPDATE payments SET status='confirmed',confirmed_at=p_at,confirmed_by_user_id=p_actor WHERE payment_id=p_payment;
  PERFORM _emit(l.loan_id,'Portoeingang bestätigt (Demonstration)',NULL,NULL,p_at);
  RETURN p_payment;
END $$;

CREATE FUNCTION prepare_shipment(p_actor bigint,p_loan bigint,p_direction text,
                                 p_sender_address bigint,p_recipient_address bigint,
                                 p_carrier text DEFAULT NULL,p_tracking text DEFAULT NULL,
                                 p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint; sender_actor bigint; recipient_actor bigint;
        sh shipments%ROWTYPE; result bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_direction IS NULL OR p_direction NOT IN('outbound','return') THEN RAISE EXCEPTION 'Invalid shipment direction' USING ERRCODE='22023'; END IF;
  sender_actor:=CASE p_direction WHEN 'outbound' THEN owner_actor ELSE l.borrower_id END;
  recipient_actor:=CASE p_direction WHEN 'outbound' THEN l.borrower_id ELSE owner_actor END;
  IF p_actor<>sender_actor THEN RAISE EXCEPTION 'Only the sender prepares a shipment' USING ERRCODE='42501'; END IF;
  SELECT * INTO sh FROM shipments WHERE loan_id=p_loan AND direction=p_direction;
  IF FOUND THEN
    IF sh.sender_address_id=p_sender_address AND sh.recipient_address_id=p_recipient_address AND
       sh.carrier IS NOT DISTINCT FROM p_carrier AND sh.tracking_number IS NOT DISTINCT FROM p_tracking THEN RETURN sh.shipment_id; END IF;
    RAISE EXCEPTION 'Shipment already exists with different details' USING ERRCODE='55000';
  END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF l.handover_mode<>'shipping' OR
     (p_direction='outbound' AND l.status<>'accepted') OR (p_direction='return' AND l.status<>'active') THEN
    RAISE EXCEPTION 'Shipment cannot be prepared in this loan state' USING ERRCODE='55000';
  END IF;
  PERFORM 1 FROM addresses WHERE address_id=p_sender_address AND user_id=sender_actor FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Sender address belongs to another user or is missing' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM addresses WHERE address_id=p_recipient_address AND user_id=recipient_actor FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Recipient address belongs to another user or is missing' USING ERRCODE='42501'; END IF;
  INSERT INTO shipments(loan_id,direction,status,sender_address_id,recipient_address_id,
     sender_address_snapshot,recipient_address_snapshot,carrier,tracking_number,prepared_at)
  VALUES(p_loan,p_direction,'prepared',p_sender_address,p_recipient_address,
     address_snapshot(p_sender_address),address_snapshot(p_recipient_address),p_carrier,p_tracking,p_at)
  RETURNING shipment_id INTO result;
  PERFORM _emit(p_loan,'Sendung vorbereitet: '||p_direction,'shipment_summary',result,p_at);
  RETURN result;
END $$;

CREATE FUNCTION send_shipment(p_actor bigint,p_shipment bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; sh shipments%ROWTYPE; owner_actor bigint; sender_actor bigint; loan_ref bigint;
BEGIN
  SELECT loan_id INTO loan_ref FROM shipments WHERE shipment_id=p_shipment;
  l:=_lock_loan(loan_ref); PERFORM _actor(p_actor,false);
  SELECT * INTO sh FROM shipments WHERE shipment_id=p_shipment FOR UPDATE;
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  sender_actor:=CASE sh.direction WHEN 'outbound' THEN owner_actor ELSE l.borrower_id END;
  IF p_actor<>sender_actor THEN RAISE EXCEPTION 'Only the sender confirms dispatch' USING ERRCODE='42501'; END IF;
  IF sh.status IN('sent','received') THEN RETURN p_shipment; END IF;
  PERFORM _loan_event(l.loan_id,p_at);
  IF sh.status<>'prepared' OR (sh.direction='outbound' AND l.status<>'accepted') OR
     (sh.direction='return' AND l.status<>'active') THEN RAISE EXCEPTION 'Shipment cannot be dispatched now' USING ERRCODE='55000'; END IF;
  IF sh.direction='outbound' AND NOT EXISTS(SELECT 1 FROM payments WHERE loan_id=l.loan_id AND status='confirmed') THEN
    RAISE EXCEPTION 'Confirmed postage is required before outbound dispatch' USING ERRCODE='55000';
  END IF;
  IF sh.direction='return' THEN PERFORM _close_extensions(l.loan_id,p_actor,p_at); END IF;
  UPDATE shipments SET status='sent',sent_at=p_at WHERE shipment_id=p_shipment;
  UPDATE loans SET status=CASE sh.direction WHEN 'outbound' THEN 'outbound' ELSE 'returning' END,
    return_started_at=CASE sh.direction WHEN 'return' THEN p_at ELSE return_started_at END WHERE loan_id=l.loan_id;
  PERFORM _emit(l.loan_id,'Versand bestätigt: '||sh.direction,NULL,NULL,p_at);
  RETURN p_shipment;
END $$;

CREATE FUNCTION receive_shipment(p_actor bigint,p_shipment bigint,p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; sh shipments%ROWTYPE; owner_actor bigint; recipient_actor bigint; loan_ref bigint;
BEGIN
  SELECT loan_id INTO loan_ref FROM shipments WHERE shipment_id=p_shipment;
  l:=_lock_loan(loan_ref); PERFORM _actor(p_actor,false);
  SELECT * INTO sh FROM shipments WHERE shipment_id=p_shipment FOR UPDATE;
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  recipient_actor:=CASE sh.direction WHEN 'outbound' THEN l.borrower_id ELSE owner_actor END;
  IF p_actor<>recipient_actor THEN RAISE EXCEPTION 'Only the recipient confirms delivery' USING ERRCODE='42501'; END IF;
  IF sh.status='received' THEN RETURN p_shipment; END IF;
  PERFORM _loan_event(l.loan_id,p_at);
  IF sh.status<>'sent' OR (sh.direction='outbound' AND l.status<>'outbound') OR
     (sh.direction='return' AND l.status<>'returning') THEN RAISE EXCEPTION 'Shipment cannot be received now' USING ERRCODE='55000'; END IF;
  UPDATE shipments SET status='received',received_at=p_at,receipt_confirmed_by=p_actor WHERE shipment_id=p_shipment;
  IF sh.direction='outbound' THEN
    UPDATE loans SET status='active',received_at=p_at,
      due_date=(p_at AT TIME ZONE 'Europe/Berlin')::date+agreed_days WHERE loan_id=l.loan_id;
    PERFORM _emit(l.loan_id,'Postempfang bestätigt',NULL,NULL,p_at);
  ELSE
    UPDATE loans SET status='completed',completed_at=p_at WHERE loan_id=l.loan_id;
    PERFORM _emit(l.loan_id,'Rücksendung eingegangen','return_confirmation',NULL,p_at);
  END IF;
  RETURN p_shipment;
END $$;

CREATE FUNCTION review_loan(p_actor bigint,p_loan bigint,p_rating integer,p_comment text DEFAULT NULL,
                            p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE l loans%ROWTYPE; owner_actor bigint; result bigint;
BEGIN
  l:=_lock_loan(p_loan); PERFORM _actor(p_actor,false);
  SELECT owner_id INTO owner_actor FROM book_copies WHERE copy_id=l.copy_id;
  IF p_actor NOT IN(owner_actor,l.borrower_id) THEN RAISE EXCEPTION 'Only participants review a loan' USING ERRCODE='42501'; END IF;
  IF l.status<>'completed' THEN RAISE EXCEPTION 'Reviews require a completed loan' USING ERRCODE='55000'; END IF;
  PERFORM _loan_event(p_loan,p_at);
  IF p_rating IS NULL OR p_rating NOT BETWEEN 1 AND 5 THEN RAISE EXCEPTION 'Rating must be from 1 to 5' USING ERRCODE='22023'; END IF;
  INSERT INTO reviews(loan_id,reviewer_id,rating,comment,created_at)
  VALUES(p_loan,p_actor,p_rating,p_comment,p_at) RETURNING review_id INTO result;
  RETURN result;
END $$;

CREATE FUNCTION set_offer_active(p_actor bigint,p_copy bigint,p_active boolean,
                                 p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE c book_copies%ROWTYPE; actor_role text;
BEGIN
  PERFORM _actor(p_actor,true);
  SELECT role INTO actor_role FROM users WHERE user_id=p_actor;
  SELECT * INTO c FROM book_copies WHERE copy_id=p_copy FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown copy %',p_copy USING ERRCODE='22023'; END IF;
  IF p_actor<>c.owner_id AND actor_role<>'admin' THEN RAISE EXCEPTION 'Only owner or admin moderates offers' USING ERRCODE='42501'; END IF;
  IF p_active IS NULL THEN RAISE EXCEPTION 'Active flag is required' USING ERRCODE='22023'; END IF;
  PERFORM _event(p_at,c.created_at);
  IF p_active THEN PERFORM _actor(c.owner_id,true); END IF;
  UPDATE book_copies SET is_active=p_active WHERE copy_id=p_copy;
  RETURN p_copy;
END $$;

CREATE FUNCTION set_user_active(p_actor bigint,p_user bigint,p_active boolean,
                                p_at timestamptz DEFAULT CURRENT_TIMESTAMP)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, bookbridge, pg_temp AS $$
DECLARE actor_role text; target users%ROWTYPE;
BEGIN
  PERFORM _actor(p_actor,true);
  SELECT role INTO actor_role FROM users WHERE user_id=p_actor;
  SELECT * INTO target FROM users WHERE user_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown user %',p_user USING ERRCODE='22023'; END IF;
  IF p_active IS NULL THEN RAISE EXCEPTION 'Active flag is required' USING ERRCODE='22023'; END IF;
  IF actor_role<>'admin' AND (p_actor<>p_user OR p_active) THEN
    RAISE EXCEPTION 'Only an admin can reactivate or moderate other users' USING ERRCODE='42501';
  END IF;
  PERFORM _event(p_at,target.created_at);
  IF NOT p_active THEN UPDATE book_copies SET is_active=false WHERE owner_id=p_user AND is_active; END IF;
  UPDATE users SET is_active=p_active WHERE user_id=p_user;
  RETURN p_user;
END $$;

-- Keep all internal helpers and domain functions inaccessible to anonymous
-- roles. Run installation/seeding as owner. Selective trusted-service grants
-- belong to deployment, never to browser clients supplying their own actor ID.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA bookbridge FROM PUBLIC;
COMMIT;
