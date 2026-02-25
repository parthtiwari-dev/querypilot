-- ============================================================
-- Library Seed Data
-- Run AFTER library.sql
-- Usage: psql -d querypilot -f database/schemas/library_seed.sql
-- ============================================================

SET search_path TO library;

-- ============================================================
-- BOOKS (18 rows)
-- Multiple books per author: Orwell (2), Christie (2), Asimov (2),
--   Tolkien (2), Rowling (2), Dostoevsky (2)
-- Multiple books per genre: fiction (6), sci-fi (4), mystery (3),
--   classic (3), fantasy (2)
-- ============================================================

INSERT INTO books (title, author, genre, published_year, copies_available) VALUES
('1984',                              'George Orwell',         'fiction',   1949, 3),
('Animal Farm',                       'George Orwell',         'fiction',   1945, 2),
('Murder on the Orient Express',      'Agatha Christie',       'mystery',   1934, 4),
('And Then There Were None',          'Agatha Christie',       'mystery',   1939, 2),
('Foundation',                        'Isaac Asimov',          'sci-fi',    1951, 5),
('I, Robot',                          'Isaac Asimov',          'sci-fi',    1950, 3),
('The Lord of the Rings',             'J.R.R. Tolkien',        'fantasy',   1954, 2),
('The Hobbit',                        'J.R.R. Tolkien',        'fantasy',   1937, 4),
('Harry Potter and the Sorcerer''s Stone', 'J.K. Rowling',    'fiction',   1997, 6),
('Harry Potter and the Chamber of Secrets','J.K. Rowling',    'fiction',   1998, 4),
('Crime and Punishment',              'Fyodor Dostoevsky',     'classic',   1866, 2),
('The Brothers Karamazov',            'Fyodor Dostoevsky',     'classic',   1880, 1),
('Dune',                              'Frank Herbert',         'sci-fi',    1965, 3),
('The Hitchhiker''s Guide to the Galaxy','Douglas Adams',     'sci-fi',    1979, 5),
('The Great Gatsby',                  'F. Scott Fitzgerald',   'classic',   1925, 3),
('To Kill a Mockingbird',             'Harper Lee',            'fiction',   1960, 4),
('The Catcher in the Rye',            'J.D. Salinger',         'fiction',   1951, 2),
('The ABC Murders',                   'Agatha Christie',       'mystery',   1936, 3);


-- ============================================================
-- MEMBERS (16 rows)
-- Mix: 8 standard, 8 premium
-- member_id 16 (Sara Khan) has NO loans — needed for hard queries
-- ============================================================

INSERT INTO members (name, email, joined_date, membership_type) VALUES
('Alice Johnson',   'alice@example.com',   '2022-03-15', 'premium'),
('Bob Smith',       'bob@example.com',     '2021-07-22', 'standard'),
('Carol White',     'carol@example.com',   '2023-01-10', 'premium'),
('David Brown',     'david@example.com',   '2020-11-05', 'standard'),
('Eva Martinez',    'eva@example.com',     '2022-06-30', 'premium'),
('Frank Lee',       'frank@example.com',   '2021-09-18', 'standard'),
('Grace Kim',       'grace@example.com',   '2023-04-02', 'premium'),
('Henry Taylor',    'henry@example.com',   '2020-08-14', 'standard'),
('Isla Chen',       'isla@example.com',    '2022-12-20', 'premium'),
('James Wilson',    'james@example.com',   '2021-03-07', 'standard'),
('Karen Davis',     'karen@example.com',   '2023-07-19', 'premium'),
('Liam Moore',      'liam@example.com',    '2020-05-25', 'standard'),
('Mia Thomas',      'mia@example.com',     '2022-10-11', 'premium'),
('Noah Garcia',     'noah@example.com',    '2021-01-30', 'standard'),
('Olivia Hall',     'olivia@example.com',  '2023-09-08', 'standard'),
('Sara Khan',       'sara@example.com',    '2023-11-01', 'standard');  -- Never borrowed


-- ============================================================
-- LOANS (20 rows)
-- Statuses:
--   returned (10): loan completed, return_date set
--   overdue  (6) : return_date in the past, status = 'overdue'
--   active   (4) : no return_date, currently borrowed
-- ============================================================

INSERT INTO loans (book_id, member_id, loan_date, return_date, status) VALUES
-- Returned loans
(1,  1,  '2024-01-05', '2024-01-19', 'returned'),
(3,  2,  '2024-02-10', '2024-02-24', 'returned'),
(5,  3,  '2024-03-01', '2024-03-15', 'returned'),
(7,  4,  '2024-04-12', '2024-04-26', 'returned'),
(9,  5,  '2024-05-20', '2024-06-03', 'returned'),
(11, 6,  '2024-06-15', '2024-06-29', 'returned'),
(13, 7,  '2024-07-08', '2024-07-22', 'returned'),
(15, 8,  '2024-08-01', '2024-08-15', 'returned'),
(2,  9,  '2024-09-10', '2024-09-24', 'returned'),
(4,  10, '2024-10-05', '2024-10-19', 'returned'),
-- Overdue loans (return_date in the past, not returned)
(6,  1,  '2024-11-01', '2024-11-15', 'overdue'),
(8,  2,  '2024-11-20', '2024-12-04', 'overdue'),
(10, 3,  '2024-12-10', '2024-12-24', 'overdue'),
(12, 11, '2025-01-05', '2025-01-19', 'overdue'),
(14, 12, '2025-01-15', '2025-01-29', 'overdue'),
(16, 13, '2025-02-01', '2025-02-15', 'overdue'),
-- Active loans (currently borrowed, no return date)
(17, 4,  '2026-02-01', NULL, 'active'),
(18, 5,  '2026-02-10', NULL, 'active'),
(1,  14, '2026-02-15', NULL, 'active'),
(5,  15, '2026-02-20', NULL, 'active');


-- ============================================================
-- FINES (17 rows)
-- All fines tied to overdue loans (loan_id 11-16)
-- and a few returned-late loans (loan_id 5, 9)
-- Mix: 9 paid, 8 unpaid
-- ============================================================

INSERT INTO fines (loan_id, amount, paid) VALUES
-- Fines on overdue loans
(11, 5.50,  FALSE),   -- Alice, overdue    → unpaid
(12, 8.00,  FALSE),   -- Bob, overdue      → unpaid
(13, 6.75,  TRUE),    -- Carol, overdue    → paid
(14, 12.00, FALSE),   -- Karen, overdue    → unpaid
(15, 9.50,  FALSE),   -- Liam, overdue     → unpaid
(16, 7.25,  TRUE),    -- Mia, overdue      → paid
-- Fines on returned loans (returned late)
(5,  3.00,  TRUE),
(9,  2.50,  FALSE),
(3,  4.00,  TRUE),
(7,  1.50,  TRUE),
(1,  2.00,  FALSE),
(6,  5.00,  TRUE),    -- (loan_id 6 is returned)
(10, 3.75,  FALSE),
(2,  1.00,  TRUE),
(4,  2.25,  FALSE),
(8,  4.50,  TRUE),
(13, 1.75,  FALSE);   -- second fine on same overdue loan
