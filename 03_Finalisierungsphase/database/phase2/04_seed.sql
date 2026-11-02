-- BookBridge Phase 2: reproduzierbare, ausschliesslich fiktive Prozessdaten.
-- Die drei bibliografischen Referenzen entsprechen den bereits dokumentierten
-- Frontend-Covern (frontend/pictures/SOURCES.md). Weitere Titel/Verlage/Personen
-- sind ausdrücklich Testdaten; ISBN bleibt dort unbekannt (NULL).
-- Keine reale Zahlung, E-Mail-Zustellung oder Dokumentdatei wird behauptet.
-- Einmal nach 01_schema.sql, 02_integrity.sql und 03_workflows.sql ausführen.
BEGIN;
SET LOCAL search_path = bookbridge, public;
SET LOCAL TIME ZONE 'Europe/Berlin';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM bookbridge.users) THEN
    RAISE EXCEPTION 'Seed verweigert: Datenbank ist nicht leer. Separate leere Projektdatenbank verwenden.';
  END IF;
END $$;

INSERT INTO users(user_id,first_name,last_name,email,password_hash,role,created_at)
SELECT n,
       (ARRAY['Anna','Ben','Clara','David','Emilia','Felix','Greta','Hannes','Ida','Jonas','Klara','Leon','Mila','Noah','Olivia','Paul','Rosa','Simon','Thea','Vincent','Frida','Lukas','Nora','Emil'])[n],
       (ARRAY['Adler','Berg','Conrad','Dorn','Engel','Falk','Graf','Heller','Imhof','Jansen','Keller','Linde','Mertens','Neumann','Ott','Pfeiffer','Reuter','Sommer','Thiel','Vogel','Wagner','Winter','Wolf','Zimmer'])[n],
       'mitglied' || lpad(n::text,2,'0') || '@bookbridge.test',
       '$argon2id$v=19$m=65536,t=3,p=1$DEMO_ONLY$NO_VALID_LOGIN_HASH',
       CASE WHEN n=24 THEN 'admin' ELSE 'member' END,
       '2026-08-01 10:00:00+02'::timestamptz + n * interval '1 hour'
FROM generate_series(1,24) AS s(n);

INSERT INTO addresses(address_id,user_id,street,postal_code,city,country_code,latitude,longitude,created_at)
SELECT n,n,'Beispielweg ' || (10+n),
       (ARRAY['40213','50667','45127','47051','44135','48143','42103','53111','52062','41061','58095','44787'])[(n-1)%12+1],
       (ARRAY['Düsseldorf','Köln','Essen','Duisburg','Dortmund','Münster','Wuppertal','Bonn','Aachen','Mönchengladbach','Hagen','Bochum'])[(n-1)%12+1],
       'DE',
       (ARRAY[51.227741,50.937531,51.455643,51.434408,51.513587,51.960665,51.256213,50.737430,50.775346,51.180457,51.367078,51.481845])[(n-1)%12+1],
       (ARRAY[6.773456,6.960279,7.011555,6.762329,7.465298,7.626135,7.150764,7.098207,6.083887,6.442804,7.463285,7.216236])[(n-1)%12+1],
       '2026-08-02 12:00:00+02'::timestamptz
FROM generate_series(1,24) AS s(n);

INSERT INTO publishers(publisher_id,name) VALUES
 (1,'Karl Rauch'),(2,'Thienemann'),(3,'Diogenes'),
 (4,'Demoverlag Nord'),(5,'Demoverlag Rhein'),(6,'Demoverlag West'),
 (7,'Demoverlag Garten'),(8,'Demoverlag Brücke'),(9,'Demoverlag Morgen'),
 (10,'Demoverlag Wissen'),(11,'Demoverlag Reise'),(12,'Demoverlag Leselicht');
INSERT INTO genres(genre_id,name) VALUES
 (1,'Erzählung'),(2,'Fantasy'),(3,'Roman'),(4,'Kriminalroman'),
 (5,'Science-Fiction'),(6,'Sachbuch'),(7,'Biografie'),(8,'Kinderbuch'),
 (9,'Lyrik'),(10,'Reisebericht'),(11,'Historischer Roman'),(12,'Ratgeber');
INSERT INTO languages(language_id,code,name) VALUES
 (1,'de','Deutsch'),(2,'en','Englisch'),(3,'fr','Französisch'),
 (4,'es','Spanisch'),(5,'it','Italienisch'),(6,'fa','Persisch'),
 (7,'ar','Arabisch'),(8,'nl','Niederländisch'),(9,'pl','Polnisch'),
 (10,'tr','Türkisch'),(11,'pt','Portugiesisch'),(12,'uk','Ukrainisch');
INSERT INTO authors(author_id,display_name) VALUES
 (1,'Antoine de Saint-Exupéry'),(2,'Michael Ende'),(3,'Bernhard Schlink');
INSERT INTO authors(author_id,display_name)
SELECT n,'Demoautorin ' || (ARRAY['Lena Auen','Mara Birke','Sina Elster','Nele Felde','Jana Hain','Lara Kirsch','Mona Licht','Tina Moor','Enna Nord','Alma Park','Ria Quell','Nina Rain','Ella Stein','Ada Tann','Eva Ufer','Ulla Wald','Anni Zeis','Dora Bach','Lea Dahl','Mia Eibe','Lina Flur'])[n-3]
FROM generate_series(4,24) AS s(n);
INSERT INTO books(book_id,title,isbn,publisher_id,publication_year,genre_id,language_id,description,created_at) VALUES
 (1,'Der kleine Prinz','9783792000571',1,NULL,1,1,'Reale Referenzausgabe des dokumentierten Frontend-Covers.','2026-08-03 10:00+02'),
 (2,'Momo','9783522202756',2,NULL,2,1,'Reale Referenzausgabe des dokumentierten Frontend-Covers.','2026-08-03 10:00+02'),
 (3,'Der Vorleser','9783257229530',3,NULL,3,1,'Reale Referenzausgabe des dokumentierten Frontend-Covers.','2026-08-03 10:00+02');
INSERT INTO books(book_id,title,isbn,publisher_id,publication_year,genre_id,language_id,description,created_at)
SELECT n,
       (ARRAY['Abend am Fluss','Die stille Bibliothek','Ein Garten im Regen','Lichter über dem Rhein','Das letzte Lesezeichen','Briefe aus dem Norden','Unterwegs nach Morgen','Sterne hinter Glas','Die Karte der Wege','Kleine Schritte','Geschichten am Fenster','Im Schatten der Brücke','Ein Jahr im Grünen','Der Klang der Seiten','Nachrichten aus der Zukunft','Die verlorene Stunde','Ein Haus voller Bücher','Zwischen zwei Städten','Wege durch den Herbst','Die offene Tür','Der nächste Sommer'])[n-3],
       NULL,4+(n-4)%9,2018+(n%8),1+(n-1)%12,
       CASE WHEN n IN (8,12,16,20,24) THEN 2 ELSE 1 END,
       'Fiktiver bibliografischer Testdatensatz; keine reale Ausgabe und keine zugewiesene ISBN.',
       '2026-08-03 10:00:00+02'::timestamptz
FROM generate_series(4,24) AS s(n);
INSERT INTO book_authors(book_id,author_id,author_order)
SELECT n,n,1 FROM generate_series(1,24) AS s(n);
-- Mehrere Autoren zeigen die echte N:M-Auflösung und definierte Reihenfolge.
INSERT INTO book_authors(book_id,author_id,author_order) VALUES (10,11,2),(11,10,2),(20,21,2);

INSERT INTO book_copies(copy_id,book_id,owner_id,pickup_address_id,condition,max_loan_days,allow_pickup,allow_shipping,is_active,notes,created_at)
SELECT n,n,n,n,(ARRAY['new','very_good','good','used'])[(n-1)%4+1],42,true,true,false,
       'Fiktives Testangebot; persönliche Abholung oder Versand nach Vereinbarung.',
       '2026-08-04 12:00:00+02'::timestamptz
FROM generate_series(1,24) AS s(n);
INSERT INTO pickup_slots(slot_id,copy_id,weekday,start_time,end_time,is_active)
SELECT n,n,1,'18:00'::time,'20:00'::time,true FROM generate_series(1,24) AS s(n);
INSERT INTO pickup_slots(slot_id,copy_id,weekday,start_time,end_time,is_active)
SELECT 24+n,n,4,'17:00'::time,'19:00'::time,true FROM generate_series(1,24) AS s(n);
UPDATE book_copies SET is_active=true;

-- Alle Prozesszustände entstehen über dieselben Funktionen wie die Anwendung.
DO $$
DECLARE
  n integer; owner_id bigint; borrower_id bigint; loan_id bigint;
  proposal_id bigint; extension_id bigint; payment_id bigint; outbound_id bigint; return_id bigint;
  is_shipping boolean; mode text;
BEGIN
  -- Historische Runde: 24 abgeschlossene Ausleihen mit Gegenangebot,
  -- genehmigter Verlängerung und zwei Teilnehmerbewertungen.
  FOR n IN 1..24 LOOP
    owner_id:=n; borrower_id:=n%24+1;
    is_shipping:=(n%2=0); mode:=CASE WHEN is_shipping THEN 'shipping' ELSE 'pickup' END;
    loan_id:=create_request(borrower_id,n,10,mode,'2026-09-01 10:00+02');
    proposal_id:=propose_days(owner_id,loan_id,14,'2026-09-01 12:00+02');
    IF is_shipping THEN
      PERFORM decide_proposal(borrower_id,proposal_id,'accepted',NULL,NULL,NULL,'2026-09-02 10:00+02');
      payment_id:=create_postage(owner_id,loan_id,2.90,2.90,'2026-09-02 11:00+02');
      PERFORM report_postage(borrower_id,payment_id,'2026-09-02 12:00+02');
      PERFORM confirm_postage(owner_id,payment_id,'2026-09-02 13:00+02');
      outbound_id:=prepare_shipment(owner_id,loan_id,'outbound',owner_id,borrower_id,'DHL Demo','BB-DEMO-H-'||n,'2026-09-02 14:00+02');
      PERFORM send_shipment(owner_id,outbound_id,'2026-09-03 09:00+02');
      PERFORM receive_shipment(borrower_id,outbound_id,'2026-09-05 15:00+02');
    ELSE
      PERFORM decide_proposal(borrower_id,proposal_id,'accepted',n,'2026-09-07 18:15+02','2026-09-07 18:45+02','2026-09-02 10:00+02');
      PERFORM receive_pickup(borrower_id,loan_id,'2026-09-07 18:20+02');
    END IF;
    extension_id:=request_extension(borrower_id,loan_id,7,'2026-09-10 10:00+02');
    PERFORM decide_extension(owner_id,extension_id,'approved','2026-09-10 11:00+02');
    IF is_shipping THEN
      return_id:=prepare_shipment(borrower_id,loan_id,'return',borrower_id,owner_id,'DHL Demo','BB-DEMO-R-'||n,'2026-09-14 10:00+02');
      PERFORM send_shipment(borrower_id,return_id,'2026-09-15 09:00+02');
      PERFORM receive_shipment(owner_id,return_id,'2026-09-17 14:00+02');
    ELSE
      PERFORM start_return(borrower_id,loan_id,'2026-09-14 17:00+02');
      PERFORM confirm_return(owner_id,loan_id,'2026-09-15 18:00+02');
    END IF;
    PERFORM review_loan(borrower_id,loan_id,4+(n%2),'Freundlicher Kontakt und verlässliche Übergabe. Fiktive Testbewertung.','2026-09-18 12:00+02');
    PERFORM review_loan(owner_id,loan_id,5,'Das Buch wurde sorgfältig behandelt. Fiktive Testbewertung.','2026-09-18 13:00+02');
  END LOOP;

  -- Zweite Runde: offene und laufende Fälle, beide Übergabearten,
  -- verspätete aktive Ausleihen sowie Storno mit/ohne bestätigtes Porto.
  FOR n IN 1..24 LOOP
    owner_id:=n; borrower_id:=n%24+1;
    is_shipping:=(n BETWEEN 5 AND 8 OR n BETWEEN 11 AND 16 OR n>=23);
    mode:=CASE WHEN is_shipping THEN 'shipping' ELSE 'pickup' END;
    loan_id:=create_request(borrower_id,n,14,mode,'2026-09-19 10:00+02');
    IF n IN (19,20) THEN
      CONTINUE; -- requested reserviert das Exemplar nicht.
    ELSIF n IN (21,22) THEN
      PERFORM reject_request(owner_id,loan_id,'2026-09-19 11:00+02');
      CONTINUE;
    END IF;
    IF is_shipping THEN
      PERFORM accept_request(owner_id,loan_id,NULL,NULL,NULL,'2026-09-20 10:00+02');
      payment_id:=create_postage(owner_id,loan_id,2.90,3.20,'2026-09-20 11:00+02');
      PERFORM report_postage(borrower_id,payment_id,'2026-09-20 12:00+02');
      IF n<>23 THEN
        PERFORM confirm_postage(owner_id,payment_id,'2026-09-20 13:00+02');
      END IF;
      IF n>=23 THEN
        PERFORM cancel_request(borrower_id,loan_id,'2026-09-20 14:00+02');
        CONTINUE;
      END IF;
      IF n IN (11,12) THEN CONTINUE; END IF; -- accepted
      outbound_id:=prepare_shipment(owner_id,loan_id,'outbound',owner_id,borrower_id,'DHL Demo','BB-DEMO-H2-'||n,'2026-09-20 14:00+02');
      PERFORM send_shipment(owner_id,outbound_id,'2026-09-21 09:00+02');
      IF n IN (13,14) THEN CONTINUE; END IF; -- outbound
      PERFORM receive_shipment(borrower_id,outbound_id,'2026-09-23 15:00+02');
    ELSE
      PERFORM accept_request(owner_id,loan_id,n,'2026-09-21 18:15+02','2026-09-21 18:45+02','2026-09-20 10:00+02');
      IF n IN (9,10) THEN CONTINUE; END IF; -- accepted
      PERFORM receive_pickup(borrower_id,loan_id,'2026-09-21 18:20+02');
    END IF;
    IF n BETWEEN 15 AND 18 THEN
      IF is_shipping THEN
        return_id:=prepare_shipment(borrower_id,loan_id,'return',borrower_id,owner_id,'DHL Demo','BB-DEMO-R2-'||n,'2026-09-30 09:00+02');
        PERFORM send_shipment(borrower_id,return_id,'2026-09-30 12:00+02');
      ELSE
        PERFORM start_return(borrower_id,loan_id,'2026-09-30 18:00+02');
      END IF;
    ELSE
      extension_id:=request_extension(borrower_id,loan_id,7,'2026-09-25 10:00+02');
      IF n%2=0 THEN
        PERFORM decide_extension(owner_id,extension_id,'rejected','2026-09-25 12:00+02');
      END IF;
    END IF;
  END LOOP;
END $$;

-- Auch nicht verwendete Katalogschlüssel bleiben nach expliziten Fixture-IDs korrekt.
SELECT setval(pg_get_serial_sequence('users','user_id'),(SELECT max(user_id) FROM users));
SELECT setval(pg_get_serial_sequence('addresses','address_id'),(SELECT max(address_id) FROM addresses));
SELECT setval(pg_get_serial_sequence('publishers','publisher_id'),(SELECT max(publisher_id) FROM publishers));
SELECT setval(pg_get_serial_sequence('genres','genre_id'),(SELECT max(genre_id) FROM genres));
SELECT setval(pg_get_serial_sequence('languages','language_id'),(SELECT max(language_id) FROM languages));
SELECT setval(pg_get_serial_sequence('authors','author_id'),(SELECT max(author_id) FROM authors));
SELECT setval(pg_get_serial_sequence('books','book_id'),(SELECT max(book_id) FROM books));
SELECT setval(pg_get_serial_sequence('book_copies','copy_id'),(SELECT max(copy_id) FROM book_copies));
SELECT setval(pg_get_serial_sequence('pickup_slots','slot_id'),(SELECT max(slot_id) FROM pickup_slots));
SET CONSTRAINTS ALL IMMEDIATE;
COMMIT;
