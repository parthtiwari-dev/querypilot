# Use QueryPilot with Your Own Database

QueryPilot works with any PostgreSQL database.  
You bring your LLM key + database URL.  
You get a self-correcting NL-to-SQL API over your own data.

---

## What You Need

- A PostgreSQL database (local or cloud) with tables already created
- A Groq API key — free at https://console.groq.com — or an OpenAI API key
- Docker (recommended) or Python 3.11 if you want to run locally without Docker

---

## Step 1 — Clone and Configure

```bash
git clone https://github.com/your-username/querypilot.git
cd querypilot
cp .env.example .env
```

Edit `.env` — the key lines:

```text
LLM_PROVIDER=groq              # or openai
GROQ_API_KEY=your_groq_key     # if using Groq
OPENAI_API_KEY=your_openai_key # if using OpenAI
DATABASE_URL=postgresql://user:password@host:5432/yourdb
```

`DATABASE_URL` must point at a PostgreSQL instance that already has your tables.

---

## Step 2 — Register Your Schema

Schemas are registered in `backend/app/schema_profiles.json`.
Each entry tells QueryPilot which PostgreSQL schema to use and which Chroma collection to index.

Add a new profile, for example:

```json
{
  "ecommerce": {
    "pg_schema": "public",
    "collection_name": "querypilot_ecommerce_v2"
  },
  "library": {
    "pg_schema": "library",
    "collection_name": "querypilot_library_v2"
  },
  "my_schema": {
    "pg_schema": "public",
    "collection_name": "querypilot_my_schema_v1"
  }
}
```

- `pg_schema`: the PostgreSQL schema name inside your database (often `public`).
- `collection_name`: a unique Chroma collection name for this schema.

You do not need to touch any Python files; `config.py` loads this JSON and injects `db_url` automatically.

---

## Step 3 — Index Your Schema (One Command)

From the `backend` directory:

```bash
cd backend
python scripts/startup_index.py
```

This script:

- Reads all entries from `backend/app/schema_profiles.json`
- Connects to your `DATABASE_URL`
- Extracts table / column / FK metadata for each `pg_schema`
- Builds sentence-transformer embeddings for tables and columns
- Stores them in the corresponding Chroma collections (e.g. `querypilot_my_schema_v1`)

You should see logs like:

```text
=== QueryPilot Startup ===
[1/2] Indexing schemas...
[my_schema] Extracted N tables...
[my_schema] Generated M embeddings...
[my_schema] Added embeddings to collection 'querypilot_my_schema_v1'
[2/2] Indexing complete.
```

---

## Step 4 — Start the API

With Docker (recommended, from project root):

```bash
docker-compose up --build
```

Without Docker (requires Python 3.11 and a running Postgres):

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok","schemas_available":["ecommerce","library","my_schema"]}
```

---

## Step 5 — Ask Questions About Your Data

Basic query:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
        "question": "Who are my top 10 customers by total spend?",
        "schema_name": "my_schema"
      }'
```

Example successful response shape:

```json
{
  "sql": "SELECT customer_id, name, SUM(total_amount) AS total_spent FROM orders GROUP BY customer_id, name ORDER BY total_spent DESC LIMIT 10;",
  "success": true,
  "attempts": 1,
  "first_attempt_success": true,
  "latency_ms": 1875.4,
  "schema_tables_used": ["orders", "customers"],
  "correction_applied": false,
  "rows": [
    [ "c_001", "Alice", "1234.56" ],
    ...
  ],
  "row_count": 10,
  "error_type": null,
  "error_message": null
}
```

---

## Why Configure via `.env` and `schema_profiles.json`, Not Per Request?

QueryPilot is a self-hosted tool, not a multi-tenant SaaS.  
You configure once, then query as much as you like.

Accepting `db_url` or API keys per request would introduce:

- SSRF risk (arbitrary DB connections from untrusted request bodies)
- API key leakage in logs and error traces
- No schema caching (every request would have to re-scan and re-embed your schema)

By keeping configuration in `.env` + `schema_profiles.json`:

- Schema metadata and embeddings are cached and reused.
- Only trusted schemas are reachable.
- Your API keys never appear in user-visible request/response bodies.

---

## Advanced: Manual Schema Setup

If you prefer fully manual control:

1. Add your schema to `backend/app/schema_profiles.json` as in Step 2.
2. Run indexing manually (from `backend`):

```bash
python scripts/startup_index.py
```

3. Start the API (Docker or uvicorn as in Step 4).

4. Query with:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show monthly revenue", "schema_name": "my_schema"}'
```

That’s all you need to get QueryPilot working over your own PostgreSQL schema.

