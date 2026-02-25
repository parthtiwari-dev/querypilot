# QueryPilot API Reference

Base URL (local): `http://127.0.0.1:8002`

---

## POST /query

Runs a natural language question through the full QueryPilot pipeline:
schema linking → SQL generation → critic validation → execution → self-correction (up to 3 attempts).

### Request body

```json
{
  "question": "Show monthly revenue for the last 6 months",
  "schema_name": "ecommerce",
  "max_attempts": 3
}
```

| Field         | Type   | Required | Description |
|--------------|--------|----------|------------|
| question     | string | ✅       | Natural language question to answer with SQL |
| schema_name  | string | ❌       | Which schema to query. Must be a key in SCHEMA_PROFILES. Default: "ecommerce". Currently supported: "ecommerce", "library" |
| max_attempts | int    | ❌       | Accepted for API compatibility. Currently fixed at 3 at agent creation time. Runtime override is not yet supported. |

### Response body

```json
{
  "sql": "SELECT DATE_TRUNC('month', order_date) AS month, SUM(total_amount) AS revenue FROM orders WHERE order_date >= CURRENT_DATE - INTERVAL '6 months' GROUP BY month ORDER BY month",
  "success": true,
  "attempts": 1,
  "first_attempt_success": true,
  "latency_ms": 1568.14,
  "schema_tables_used": ["orders", "payments", "customers", "order_items", "products"],
  "correction_applied": false,
  "rows": [[...]],
  "row_count": 6,
  "error_type": null,
  "error_message": null
}
```

| Field                  | Type              | Description |
|------------------------|-------------------|------------|
| sql                    | string or null    | Final SQL query after correction (if any). Null if blocked before generation (e.g. unsafe intent) |
| success                | bool              | Whether SQL executed successfully and returned rows |
| attempts               | int               | Number of pipeline attempts made (1–3) |
| first_attempt_success  | bool              | True if SQL succeeded without any correction |
| latency_ms             | float             | Total wall-clock time for the full pipeline in milliseconds |
| schema_tables_used     | list[string]      | Tables retrieved by the schema linker as context for the LLM. This reflects what the system was given as input context — not what tables appear in the final SQL. A table here does not mean it was used in the query |
| correction_applied     | bool              | True when attempts > 1. The system retried after a critic or execution failure |
| rows                   | list or null      | Raw result rows from the database. Currently returned as arrays (not named dicts). Null on failure |
| row_count              | int               | Number of rows returned. 0 on failure |
| error_type             | string or null    | Error class on failure: syntax_error, column_not_found, table_not_found, unsafe_operation, timeout, runtime_error, etc. Null on success |
| error_message          | string or null    | Human-readable error detail from the executor or safety guard. Null on success |

---

## Error responses

| HTTP code | Cause |
|----------|-------|
| 400      | schema_name not found in SCHEMA_PROFILES |
| 500      | Unexpected server error (check uvicorn logs) |

---

## GET /health

Returns server status and available schemas. Use this to confirm the server is up and verify which schema names are valid before sending /query requests.

### Response

```json
{
  "status": "ok",
  "schemas_available": ["ecommerce", "library"]
}
```

---

## Examples

### Example 1 — Success on first attempt

```bash
curl -X POST http://127.0.0.1:8001/query \
  -H "Content-Type: application/json" \
  -d '{"question": "how many customers?", "schema_name": "ecommerce"}'
```

Response:

```json
{
  "sql": "SELECT COUNT(customer_id) AS total_customers FROM customers;",
  "success": true,
  "attempts": 1,
  "first_attempt_success": true,
  "latency_ms": 1279.0,
  "schema_tables_used": ["customers", "orders", "reviews", "products"],
  "correction_applied": false,
  "rows": [[...],[1]],
  "row_count": 1,
  "error_type": null,
  "error_message": null
}
```

### Example 2 — Correction applied

```bash
curl -X POST http://127.0.0.1:8001/query \
  -H "Content-Type: application/json" \
  -d '{"question": "find customers who placed more orders than the average customer", "schema_name": "ecommerce"}'
```

Response:

```json
{
  "sql": "WITH customer_order_counts AS (SELECT customer_id, COUNT(order_id) AS order_count FROM orders GROUP BY customer_id) SELECT c.customer_id, c.name, c.email, coc.order_count FROM customers c JOIN customer_order_counts coc ON c.customer_id = coc.customer_id WHERE coc.order_count > (SELECT AVG(order_count) FROM customer_order_counts) LIMIT 1000",
  "success": true,
  "attempts": 3,
  "first_attempt_success": false,
  "latency_ms": 6770.0,
  "schema_tables_used": ["orders", "customers", "order_items", "products"],
  "correction_applied": true,
  "rows": [[...]],
  "row_count": 8,
  "error_type": null,
  "error_message": null
}
```

---

## Known Limitations

- max_attempts override not supported. The field is accepted but ignored. Agents are cached at creation with max_attempts=3.

- Single-threaded dev server only. self_correction.py uses module-level global references for LangGraph node functions. Concurrent requests targeting different schemas on the same worker process are unsafe. Use `--workers 1` (default) in development.

- rows returned as arrays, not dicts. Column names are not included in the row data. Clients must infer column names from the sql field or request the schema separately.

- schema_tables_used is linker context, not SQL parse. It reflects the tables retrieved for LLM context. The final SQL may use a subset of these tables.

