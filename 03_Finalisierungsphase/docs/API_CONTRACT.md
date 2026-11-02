# BookBridge Phase 3 API

Local German Flask/PostgreSQL application. JSON requests/responses. Server sessions use an opaque HttpOnly cookie; all mutations require X-CSRF-Token returned by GET /api/session. The actor always comes from the server session, never request JSON. Errors: {error: German text, code: string}. Success responses use the shapes below.

## Public and account
- GET /api/session -> {user: {user_id,first_name,last_name,email,role,is_active}|null, csrf_token, addresses: []}. Inactive members may sign in and finish existing workflows; new offers, requests, proposals and acceptance remain blocked.
- POST /api/register {first_name,last_name,email,password} -> same session shape
- POST /api/login {email,password} -> same session shape
- POST /api/logout {} -> same session shape with null user
- PATCH /api/profile {first_name,last_name} -> {user}
- POST /api/account/deactivate {} -> {user}; own offers deactivate atomically. Session remains available for existing loans. Reactivation requires an active administrator and does not reactivate offers automatically.
- POST /api/password {current_password,new_password} -> {ok:true} (other sessions revoked)
- GET /api/addresses -> {addresses:[address_id,street,postal_code,city,country_code,latitude,longitude]}
- POST /api/addresses {street,postal_code,city,country_code,latitude?,longitude?} -> {address}
- PATCH /api/addresses/<address_id> {street,postal_code,city,country_code,latitude?,longitude?} -> {address}; replaces the current fields of an own address only, never its owner. Historical pickup/shipment snapshots remain unchanged. Clearing coordinates on an active offer's address is rejected by database consistency checks.
- GET /api/meta -> {genres:[{genre_id,name}],languages:[{language_id,code,name}]}

## Catalogue and offers (domain.py)
- GET /api/catalog?query=&genre_id=&language_id=&city=&available_only=true&page=1&radius=&latitude=&longitude= -> {items:[],total,page,page_size:12}. The city field matches a city name (case insensitive) or an exact postal code. Radius optional, requires both origin coordinates. Never expose private street/contact or exact copy coordinates. Items: copy_id,book_id,title,authors,genre,language,condition,max_loan_days,allow_pickup,allow_shipping,is_active,available,city,postal_code,owner_id (only ownership identifier),cover_url,description,distance_km?
- GET /api/catalog/<copy_id> -> {item:catalogue item,pickup_slots:[{slot_id,weekday,start_time,end_time,next_start_at,next_end_at}],reviews:[{rating,comment,first_name}]}
- GET /api/my-books -> {items:[]}; includes own inactive offers, their address_id and current active pickup_slots. Private address IDs are not included in public catalogue items.
- POST /api/books {title,author,publisher?,publication_year?,isbn?,genre_id,language_id,condition,max_loan_days,address_id,allow_pickup,allow_shipping,notes?,description?,pickup_slots:[{weekday,start_time,end_time}]} -> {copy_id}
- PATCH /api/books/<copy_id> {condition?,max_loan_days?,notes?,is_active?,address_id?,allow_pickup?,allow_shipping?,pickup_slots?:[{weekday,start_time,end_time}]} -> {copy_id}. Owner only; at least one field. Use set_offer_active for active flag; never rewrite shared bibliographic records/history. New locations must be own addresses; active offers require coordinates. A new weekly plan deactivates old slots and inserts replacements atomically, preserving historical IDs, times and accepted appointments.

## Loans and controlled actions (domain.py)
- GET /api/loans -> {items:[]}, current member's owner+borrower loans only. Each item has loan columns, title,owner_id,max_loan_days (current offer limit),owner_name,borrower_name,role (owner|borrower), pickup_slots as above, proposals:[],extensions:[],payments:[],shipments:[],reviews:[],documents:[]. All child arrays; participant live private addresses exposed only during ongoing accepted shipping (accepted/outbound/active/returning; recipient_addresses/sender_addresses). Completed loans retain immutable shipment address snapshots, without exposing later address additions. pickup_address_snapshot is exposed only after acceptance.
- POST /api/loans {copy_id,days,mode:'pickup'|'shipping'} -> {loan_id}
- POST /api/loans/<loan_id>/actions {action,...fields} -> {id}. All functions use authenticated actor. Allowed actions/fields:
  - accept {slot_id?,start_at?,end_at?} (shipping omit pickup)
  - reject, cancel, receive_pickup, start_return, confirm_return
  - propose {days}; decide_proposal {proposal_id,decision:'accepted'|'rejected'|'withdrawn',slot_id?,start_at?,end_at?}; the owner may withdraw a pending proposal, and the borrower may accept/reject it. Pickup fields apply only to acceptance.
  - request_extension {days}; decide_extension {extension_id,decision:'approved'|'rejected'|'withdrawn'}; the borrower may withdraw a pending extension, and the owner may approve/reject it.
  - create_postage {outbound_fee,return_fee}; report_postage {payment_id}; confirm_postage {payment_id}
  - prepare_shipment {direction:'outbound'|'return',sender_address_id,recipient_address_id,carrier?,tracking_number?}
  - send_shipment {shipment_id}; receive_shipment {shipment_id}
  - review {rating,comment?}
  Validate child ID belongs to this loan BEFORE calling SQL. No client timestamps for domain event times. Appointment timestamps must have timezone offsets. SQL remains authoritative for roles/transitions.

## Notifications and documents (root backend app)
- GET /api/notifications -> {items:[]}; only current recipient, in_app only, delivery marked on retrieval
- POST /api/notifications/<id>/read -> {ok:true}
- GET /api/documents/<id>/download -> authenticated actual PDF, recipient only. Generated on demand, server-private storage.

## Moderation (active administrators only)
- GET /api/admin/users -> {items:[{user_id,first_name,last_name,email,role,is_active}]}
- GET /api/admin/offers -> {items:[{copy_id,title,owner_id,owner_name,is_active}]}
- PATCH /api/admin/users/<user_id> {is_active:bool} -> {user}; uses set_user_active. No role assignment endpoint exists.
- PATCH /api/admin/offers/<copy_id> {is_active:bool} -> {copy_id,is_active}; uses set_offer_active. An inactive owner's offer cannot be activated.
- Admin permissions do not allow acting on another member's loans, payments or shipments. Those routes remain participant-only.

## Domain module integration
Implement backend/domain.py. Exports register_routes(app, connection_factory, require_user, require_csrf). connection_factory() returns psycopg connection (transactional context, dict_row, search_path=bookbridge,bookbridge_app,public; grants for app service). require_user() -> user dict or raises an HTTP error. require_csrf() -> None or raises. Domain errors may raise ValueError (400), PermissionError (403), LookupError (404); root global handlers translate psycopg errors. GETs return Flask jsonify; mutations call both guards. No auth tables or account routes in domain module.

Use /pictures paths for retained covers; never invent real covers. Unknown books use a neutral text placeholder in UI. Session/UI do not log in as Phase 2 fictitious users. Seed optional new demo accounts explicitly via setup with real password hashes, separate from Phase 2 users.
