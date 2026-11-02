-- Phase 3: owner-scoped HTTP editing of addresses and offer logistics.
-- Existing migrations and the original Phase 2 sources remain unchanged.
-- The trusted service enforces ownership; SQL triggers still enforce address
-- ownership, active coordinates, non-overlapping slots and immutable history.
BEGIN;
GRANT UPDATE(street,postal_code,city,country_code,latitude,longitude)
    ON bookbridge.addresses TO bookbridge_web;
GRANT UPDATE(pickup_address_id,allow_pickup,allow_shipping)
    ON bookbridge.book_copies TO bookbridge_web;
-- Replaced windows are deactivated, never removed or rewritten. Accepted
-- loans retain their slot reference and agreement-time address/time snapshots.
GRANT UPDATE(is_active) ON bookbridge.pickup_slots TO bookbridge_web;
COMMIT;
