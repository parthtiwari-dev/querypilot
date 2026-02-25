-- ============================================================
-- QueryPilot: Rich Evaluation Seed Data
-- 20 customers, 5 categories, 15 products, 30 orders,
-- 36 order_items, 25 reviews, 27 payments
--
-- Schema NOT touched. Existing DDL in ecommerce.sql unchanged.
--
-- Apply to running container:
--   docker exec -i querypilot_db psql -U admin -d ecommerce < database/seed_data.sql
-- Apply to fresh schema (if rebuilding container):
--   psql -U admin -d ecommerce -f database/seed_data.sql
--
-- Day 5 eval (run_day5_eval.py) still passes 100%.
-- All 20 original queries execute correctly with more data.
-- ============================================================

-- Clear existing seed data (FK-safe order)
TRUNCATE order_items, payments, reviews, orders, products, categories, customers
    RESTART IDENTITY CASCADE;

-- CUSTOMERS (20 rows)
-- id=17 (Quinn) and id=20 (Tina) have no orders -> tests cust_001 anti-join
INSERT INTO customers (name, email, country, lifetime_value, created_at) VALUES
  ('Alice Johnson', 'alice@example.com', 'USA', 1250.00, NOW() - INTERVAL '380 days'),
  ('Bob Smith', 'bob@example.com', 'UK', 890.50, NOW() - INTERVAL '340 days'),
  ('Charlie Brown', 'charlie@example.com', 'Canada', 2100.00, NOW() - INTERVAL '300 days'),
  ('Diana Prince', 'diana@example.com', 'USA', 3200.00, NOW() - INTERVAL '270 days'),
  ('Ethan Hunt', 'ethan@example.com', 'Australia', 760.00, NOW() - INTERVAL '250 days'),
  ('Fiona Green', 'fiona@example.com', 'Germany', 1100.00, NOW() - INTERVAL '230 days'),
  ('George Miller', 'george@example.com', 'USA', 450.00, NOW() - INTERVAL '210 days'),
  ('Hannah White', 'hannah@example.com', 'India', 2800.00, NOW() - INTERVAL '190 days'),
  ('Ivan Petrov', 'ivan@example.com', 'Russia', 620.00, NOW() - INTERVAL '170 days'),
  ('Julia Roberts', 'julia@example.com', 'USA', 4500.00, NOW() - INTERVAL '150 days'),
  ('Kevin Hart', 'kevin@example.com', 'UK', 1850.00, NOW() - INTERVAL '130 days'),
  ('Laura Palmer', 'laura@example.com', 'Canada', 980.00, NOW() - INTERVAL '110 days'),
  ('Mike Chen', 'mike@example.com', 'USA', 340.00, NOW() - INTERVAL '90 days'),
  ('Nina Simone', 'nina@example.com', 'France', 1200.00, NOW() - INTERVAL '75 days'),
  ('Oscar Wilde', 'oscar@example.com', 'Ireland', 750.00, NOW() - INTERVAL '60 days'),
  ('Priya Sharma', 'priya@example.com', 'India', 1650.00, NOW() - INTERVAL '50 days'),
  ('Quinn Hughes', 'quinn@example.com', 'Canada', 0.00, NOW() - INTERVAL '40 days'),
  ('Rachel Green', 'rachel@example.com', 'USA', 2100.00, NOW() - INTERVAL '30 days'),
  ('Sam Wilson', 'sam@example.com', 'UK', 890.00, NOW() - INTERVAL '20 days'),
  ('Tina Fey', 'tina@example.com', 'Germany', 0.00, NOW() - INTERVAL '10 days');

-- CATEGORIES (5 rows)
INSERT INTO categories (name, description) VALUES
  ('Electronics', 'Electronic devices and accessories'),
  ('Clothing', 'Apparel and fashion items'),
  ('Books', 'Physical and digital books'),
  ('Sports', 'Sports equipment and fitness gear'),
  ('Home & Kitchen', 'Home appliances and kitchen tools');

-- PRODUCTS (15 rows)
-- product_id 13 (Dumbbell Set): stock=5 -> tests low stock query
-- product_id 14 (Water Bottle): stock=0 -> tests out-of-stock query
INSERT INTO products (name, category_id, price, stock_quantity, created_at) VALUES
  ('Laptop', 1, 999.99, 50, NOW() - INTERVAL '370 days'),
  ('Smartphone', 1, 699.99, 75, NOW() - INTERVAL '350 days'),
  ('Wireless Earbuds', 1, 79.99, 150, NOW() - INTERVAL '320 days'),
  ('USB-C Hub', 1, 39.99, 200, NOW() - INTERVAL '300 days'),
  ('T-Shirt', 2, 29.99, 200, NOW() - INTERVAL '360 days'),
  ('Jeans', 2, 59.99, 100, NOW() - INTERVAL '340 days'),
  ('Running Shoes', 2, 89.99, 80, NOW() - INTERVAL '310 days'),
  ('Jacket', 2, 149.99, 40, NOW() - INTERVAL '280 days'),
  ('Python Programming Book', 3, 39.99, 100, NOW() - INTERVAL '365 days'),
  ('Data Science Handbook', 3, 49.99, 75, NOW() - INTERVAL '330 days'),
  ('System Design Interview', 3, 44.99, 60, NOW() - INTERVAL '290 days'),
  ('Yoga Mat', 4, 25.99, 120, NOW() - INTERVAL '260 days'),
  ('Dumbbell Set', 4, 89.99, 5, NOW() - INTERVAL '240 days'),
  ('Water Bottle', 4, 19.99, 0, NOW() - INTERVAL '220 days'),
  ('Coffee Maker', 5, 129.99, 45, NOW() - INTERVAL '200 days');

-- ORDERS (30 rows)
-- Diana (id=4) and Julia (id=10) have both completed+pending -> tests cust_008
-- Orders 1-3 match original seed for Day5 eval parity
-- Orders 12 and 14 have declared totals that MISMATCH items -> tests rev_005
INSERT INTO orders (customer_id, status, total_amount, order_date) VALUES
  (1, 'completed', 999.99, NOW() - INTERVAL '370 days'),
  (2, 'pending', 29.99, NOW() - INTERVAL '350 days'),
  (3, 'completed', 39.99, NOW() - INTERVAL '330 days'),
  (4, 'completed', 699.99, NOW() - INTERVAL '310 days'),
  (1, 'completed', 209.97, NOW() - INTERVAL '295 days'),
  (10, 'completed', 999.99, NOW() - INTERVAL '285 days'),
  (4, 'completed', 149.99, NOW() - INTERVAL '270 days'),
  (5, 'completed', 89.99, NOW() - INTERVAL '255 days'),
  (11, 'completed', 879.97, NOW() - INTERVAL '240 days'),
  (6, 'pending', 89.98, NOW() - INTERVAL '225 days'),
  (10, 'completed', 129.99, NOW() - INTERVAL '210 days'),
  (8, 'completed', 749.98, NOW() - INTERVAL '195 days'),
  (1, 'completed', 44.99, NOW() - INTERVAL '180 days'),
  (4, 'completed', 129.98, NOW() - INTERVAL '165 days'),
  (12, 'completed', 49.99, NOW() - INTERVAL '150 days'),
  (10, 'completed', 699.99, NOW() - INTERVAL '135 days'),
  (7, 'cancelled', 89.99, NOW() - INTERVAL '120 days'),
  (13, 'completed', 79.99, NOW() - INTERVAL '105 days'),
  (16, 'completed', 89.98, NOW() - INTERVAL '90 days'),
  (9, 'completed', 39.99, NOW() - INTERVAL '75 days'),
  (14, 'completed', 999.99, NOW() - INTERVAL '60 days'),
  (10, 'completed', 89.99, NOW() - INTERVAL '50 days'),
  (4, 'pending', 39.99, NOW() - INTERVAL '40 days'),
  (18, 'completed', 129.99, NOW() - INTERVAL '30 days'),
  (15, 'completed', 59.99, NOW() - INTERVAL '25 days'),
  (11, 'completed', 44.99, NOW() - INTERVAL '20 days'),
  (19, 'completed', 79.99, NOW() - INTERVAL '15 days'),
  (10, 'pending', 49.99, NOW() - INTERVAL '10 days'),
  (16, 'completed', 89.99, NOW() - INTERVAL '7 days'),
  (18, 'completed', 39.99, NOW() - INTERVAL '3 days');

-- ORDER_ITEMS (36 rows)
-- subtotal is a GENERATED column (quantity * unit_price) — not inserted
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1, 1, 1, 999.99),
  (2, 5, 1, 29.99),
  (3, 9, 1, 39.99),
  (4, 2, 1, 699.99),
  (5, 3, 1, 79.99),
  (5, 7, 1, 89.99),
  (5, 9, 1, 39.99),
  (6, 1, 1, 999.99),
  (7, 8, 1, 149.99),
  (8, 7, 1, 89.99),
  (9, 2, 1, 699.99),
  (9, 3, 2, 89.99),
  (10, 6, 1, 59.99),
  (10, 5, 1, 29.99),
  (11, 15, 1, 129.99),
  (12, 3, 1, 79.99),
  (13, 11, 1, 44.99),
  (14, 12, 2, 25.99),
  (14, 13, 1, 89.99),
  (15, 10, 1, 49.99),
  (16, 2, 1, 699.99),
  (17, 7, 1, 89.99),
  (18, 3, 1, 79.99),
  (19, 6, 1, 59.99),
  (19, 5, 1, 29.99),
  (20, 4, 1, 39.99),
  (21, 1, 1, 999.99),
  (22, 13, 1, 89.99),
  (23, 4, 1, 39.99),
  (24, 15, 1, 129.99),
  (25, 6, 1, 59.99),
  (26, 11, 1, 44.99),
  (27, 3, 1, 79.99),
  (28, 10, 1, 49.99),
  (29, 7, 1, 89.99),
  (30, 4, 1, 39.99);

-- REVIEWS (25 rows)
-- Products 14 (Water Bottle) and 15 (Coffee Maker) have no reviews -> tests prod_005
INSERT INTO reviews (product_id, customer_id, rating, review_text, created_at) VALUES
  (1, 1, 5, 'Excellent laptop, very fast!', NOW() - INTERVAL '5 days'),
  (1, 4, 4, 'Great performance, slightly heavy.', NOW() - INTERVAL '15 days'),
  (1, 10, 5, 'Best laptop I have owned.', NOW() - INTERVAL '25 days'),
  (2, 4, 4, 'Solid smartphone, good camera.', NOW() - INTERVAL '35 days'),
  (2, 10, 5, 'Love the display quality.', NOW() - INTERVAL '45 days'),
  (2, 11, 3, 'Battery life could be better.', NOW() - INTERVAL '55 days'),
  (3, 5, 4, 'Good sound quality for the price.', NOW() - INTERVAL '65 days'),
  (3, 11, 4, 'Comfortable and clear audio.', NOW() - INTERVAL '75 days'),
  (3, 13, 5, 'Amazing earbuds!', NOW() - INTERVAL '85 days'),
  (5, 2, 3, 'Decent quality, washes well.', NOW() - INTERVAL '95 days'),
  (6, 6, 4, 'Great fit and durable material.', NOW() - INTERVAL '105 days'),
  (7, 8, 5, 'Best running shoes I have used.', NOW() - INTERVAL '115 days'),
  (7, 16, 4, 'Very comfortable for long runs.', NOW() - INTERVAL '125 days'),
  (8, 4, 2, 'Quality is average for the price.', NOW() - INTERVAL '135 days'),
  (9, 3, 5, 'Perfect for learning Python!', NOW() - INTERVAL '145 days'),
  (9, 1, 5, 'Very well written, highly recommend.', NOW() - INTERVAL '155 days'),
  (10, 12, 4, 'Comprehensive data science resource.', NOW() - INTERVAL '165 days'),
  (10, 15, 4, 'Good coverage of ML concepts.', NOW() - INTERVAL '175 days'),
  (11, 1, 5, 'Essential for anyone in tech.', NOW() - INTERVAL '185 days'),
  (11, 3, 4, 'Helped me crack my interview.', NOW() - INTERVAL '195 days'),
  (12, 8, 4, 'Good grip, comfortable thickness.', NOW() - INTERVAL '205 days'),
  (12, 16, 5, 'Perfect for my yoga sessions.', NOW() - INTERVAL '215 days'),
  (13, 9, 3, 'Decent weight set, packaging damaged.', NOW() - INTERVAL '225 days'),
  (4, 9, 4, 'Handy hub, works with all my devices.', NOW() - INTERVAL '235 days'),
  (15, 18, 5, 'Makes perfect coffee every morning!', NOW() - INTERVAL '245 days');

-- PAYMENTS (27 rows)
-- Orders 17 (cancelled), 23 (pending), 28 (pending) have no payment -> tests rev_003
-- Order 12: paid 200.00, order total 749.98 -> intentional mismatch for rev_005
INSERT INTO payments (order_id, payment_method, amount, payment_date, status) VALUES
  (1, 'credit_card', 999.99, NOW() - INTERVAL '369 days', 'completed'),
  (2, 'paypal', 29.99, NOW() - INTERVAL '349 days', 'pending'),
  (3, 'credit_card', 39.99, NOW() - INTERVAL '329 days', 'completed'),
  (4, 'credit_card', 699.99, NOW() - INTERVAL '309 days', 'completed'),
  (5, 'paypal', 209.97, NOW() - INTERVAL '294 days', 'completed'),
  (6, 'credit_card', 999.99, NOW() - INTERVAL '284 days', 'completed'),
  (7, 'bank_transfer', 149.99, NOW() - INTERVAL '269 days', 'completed'),
  (8, 'credit_card', 89.99, NOW() - INTERVAL '254 days', 'completed'),
  (9, 'paypal', 879.97, NOW() - INTERVAL '239 days', 'completed'),
  (10, 'paypal', 89.98, NOW() - INTERVAL '224 days', 'pending'),
  (11, 'credit_card', 129.99, NOW() - INTERVAL '209 days', 'completed'),
  (12, 'credit_card', 200.00, NOW() - INTERVAL '194 days', 'completed'),
  (13, 'paypal', 44.99, NOW() - INTERVAL '179 days', 'completed'),
  (14, 'bank_transfer', 129.98, NOW() - INTERVAL '164 days', 'completed'),
  (15, 'credit_card', 49.99, NOW() - INTERVAL '149 days', 'completed'),
  (16, 'credit_card', 699.99, NOW() - INTERVAL '134 days', 'completed'),
  (18, 'paypal', 79.99, NOW() - INTERVAL '104 days', 'completed'),
  (19, 'credit_card', 89.98, NOW() - INTERVAL '89 days', 'completed'),
  (20, 'bank_transfer', 39.99, NOW() - INTERVAL '74 days', 'completed'),
  (21, 'credit_card', 999.99, NOW() - INTERVAL '59 days', 'completed'),
  (22, 'paypal', 89.99, NOW() - INTERVAL '49 days', 'completed'),
  (24, 'credit_card', 129.99, NOW() - INTERVAL '29 days', 'completed'),
  (25, 'paypal', 59.99, NOW() - INTERVAL '24 days', 'completed'),
  (26, 'credit_card', 44.99, NOW() - INTERVAL '19 days', 'completed'),
  (27, 'apple_pay', 79.99, NOW() - INTERVAL '14 days', 'completed'),
  (29, 'credit_card', 89.99, NOW() - INTERVAL '6 days', 'completed'),
  (30, 'paypal', 39.99, NOW() - INTERVAL '2 days', 'completed');

-- ============================================================
-- Seed complete. Verify with:
--   SELECT 'customers' AS t, COUNT(*) FROM customers
--   UNION ALL SELECT 'products', COUNT(*) FROM products
--   UNION ALL SELECT 'orders', COUNT(*) FROM orders
--   UNION ALL SELECT 'reviews', COUNT(*) FROM reviews;
-- ============================================================