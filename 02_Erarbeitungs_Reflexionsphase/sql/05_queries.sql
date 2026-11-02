-- BookBridge Phase 2: reproduzierbare Ergebnisabfragen, PostgreSQL.
SET search_path = bookbridge, public;
SET TIME ZONE 'Europe/Berlin';

-- Q01: drei Tabellen: Ausgabe, physisches Exemplar, Eigentümer.
SELECT c.copy_id,b.title,u.first_name || ' ' || u.last_name AS owner,
       c.condition,c.max_loan_days
FROM book_copies c
JOIN books b ON b.book_id=c.book_id
JOIN users u ON u.user_id=c.owner_id
ORDER BY c.copy_id;

-- Q02: drei Tabellen: Ausleihe, Exemplar, ausleihende Person.
SELECT l.loan_id,c.copy_id,u.first_name || ' ' || u.last_name AS borrower,
       l.handover_mode,l.status,l.due_date
FROM loans l
JOIN book_copies c ON c.copy_id=l.copy_id
JOIN users u ON u.user_id=l.borrower_id
ORDER BY l.loan_id;

-- Q03: drei Tabellen mit LEFT JOIN, damit auch unbestätigtes Porto sichtbar bleibt.
SELECT p.payment_id,l.loan_id,l.status AS loan_status,p.status AS payment_status,
       p.outbound_fee+p.return_fee AS total_eur,
       u.first_name || ' ' || u.last_name AS confirmed_by,p.confirmed_at
FROM payments p
JOIN loans l ON l.loan_id=p.loan_id
LEFT JOIN users u ON u.user_id=p.confirmed_by_user_id
ORDER BY p.payment_id;

-- Q04: Ausleihhäufigkeit: auch nie ausgeliehene Ausgaben bleiben sichtbar.
SELECT b.book_id,b.title,count(l.loan_id) AS requests,
       count(l.loan_id) FILTER (WHERE l.status='completed') AS completed_loans
FROM books b LEFT JOIN book_copies c ON c.book_id=b.book_id
LEFT JOIN loans l ON l.copy_id=c.copy_id
GROUP BY b.book_id,b.title ORDER BY completed_loans DESC,b.book_id;

-- Q05: verfügbare Angebote; requested ist bewusst keine Reservierung.
SELECT c.copy_id,b.title,a.city,a.postal_code
FROM book_copies c JOIN books b ON b.book_id=c.book_id
JOIN users u ON u.user_id=c.owner_id
JOIN addresses a ON a.address_id=c.pickup_address_id
WHERE c.is_active AND u.is_active
AND NOT EXISTS(SELECT 1 FROM loans l WHERE l.copy_id=c.copy_id
               AND l.status IN ('accepted','outbound','active','returning'))
ORDER BY c.copy_id;

-- Q06: reproduzierbarer Stichtag statt abhängigem Screenshot-Datum.
SELECT l.loan_id,b.title,l.handover_mode,l.status,l.due_date,
       DATE '2026-10-18'-l.due_date AS days_overdue
FROM loans l JOIN book_copies c ON c.copy_id=l.copy_id
JOIN books b ON b.book_id=c.book_id
WHERE l.status IN ('active','returning') AND l.due_date<DATE '2026-10-18'
ORDER BY l.due_date,l.loan_id;

-- Q07: aktuelle Frist ist aus Erhalt + Dauer + genehmigten Zusatztagen erklärbar.
SELECT l.loan_id,l.due_date,
       (l.received_at AT TIME ZONE 'Europe/Berlin')::date+l.agreed_days+
       coalesce(sum(e.extra_days) FILTER(WHERE e.status='approved'),0)::integer AS recomputed_due_date
FROM loans l LEFT JOIN loan_extensions e ON e.loan_id=l.loan_id
WHERE l.received_at IS NOT NULL
GROUP BY l.loan_id ORDER BY l.loan_id;

-- Q08: alle 18 Tabellen mit mindestens zehn sinnvoll belegten Datensätzen.
SELECT 'users' AS entity,count(*) AS rows FROM users
UNION ALL SELECT 'addresses',count(*) FROM addresses
UNION ALL SELECT 'publishers',count(*) FROM publishers
UNION ALL SELECT 'genres',count(*) FROM genres
UNION ALL SELECT 'languages',count(*) FROM languages
UNION ALL SELECT 'authors',count(*) FROM authors
UNION ALL SELECT 'books',count(*) FROM books
UNION ALL SELECT 'book_authors',count(*) FROM book_authors
UNION ALL SELECT 'book_copies',count(*) FROM book_copies
UNION ALL SELECT 'pickup_slots',count(*) FROM pickup_slots
UNION ALL SELECT 'loans',count(*) FROM loans
UNION ALL SELECT 'loan_proposals',count(*) FROM loan_proposals
UNION ALL SELECT 'loan_extensions',count(*) FROM loan_extensions
UNION ALL SELECT 'payments',count(*) FROM payments
UNION ALL SELECT 'shipments',count(*) FROM shipments
UNION ALL SELECT 'notifications',count(*) FROM notifications
UNION ALL SELECT 'generated_documents',count(*) FROM generated_documents
UNION ALL SELECT 'reviews',count(*) FROM reviews
ORDER BY entity;
