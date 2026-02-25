-- ============================================================
-- Library Schema
-- Usage: psql -d querypilot -f database/schemas/library.sql
-- ============================================================

CREATE SCHEMA IF NOT EXISTS library;
SET search_path TO library;

CREATE TABLE books (
    book_id       SERIAL PRIMARY KEY,
    title         VARCHAR(255) NOT NULL,
    author        VARCHAR(255) NOT NULL,
    genre         VARCHAR(100),
    published_year INT,
    copies_available INT DEFAULT 0
);

CREATE TABLE members (
    member_id       SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE,
    joined_date     DATE,
    membership_type VARCHAR(50)   -- 'standard', 'premium'
);

CREATE TABLE loans (
    loan_id     SERIAL PRIMARY KEY,
    book_id     INT REFERENCES books(book_id),
    member_id   INT REFERENCES members(member_id),
    loan_date   DATE NOT NULL,
    return_date DATE,
    status      VARCHAR(50)   -- 'active', 'returned', 'overdue'
);

CREATE TABLE fines (
    fine_id SERIAL PRIMARY KEY,
    loan_id INT REFERENCES loans(loan_id),
    amount  DECIMAL(10,2),
    paid    BOOLEAN DEFAULT FALSE
);
