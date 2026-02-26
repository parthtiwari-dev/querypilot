# QueryPilot

QueryPilot lets analysts and engineers query PostgreSQL in natural language, while still seeing the exact SQL that was executed and how many correction attempts it needed.

Multi-agent Text-to-SQL system.  
Ask questions in plain English, get executable PostgreSQL queries back — with automatic self-correction.

Built with: FastAPI · LangGraph · ChromaDB · sentence-transformers · Groq / OpenAI

---

## How It Works

`Question → Schema Linker → SQL Generator → Critic → Executor → Corrector → Response`

Five agents, each with a single responsibility:

- **Schema linker** retrieves only the relevant tables and columns from your schema.
- **SQL generator** produces a first SQL attempt, scoped to those tables only.
- **Critic** runs static checks and guardrails (unsafe operations, sensitive data, obvious syntax issues) before anything hits the database.
- **Executor** runs SQL against PostgreSQL in read-only mode and classifies any errors.
- **Corrector** uses the error signal to rewrite SQL and retry up to 3 times.

Queries containing destructive DDL or sensitive-data intent (e.g. "show me the database password") are blocked before execution.

The whole flow is orchestrated with LangGraph as a small state machine:

`SCHEMA_LINKING → SQL_GENERATION → CRITIC_VALIDATION → EXECUTION → (SUCCESS | CORRECTION loop)`

Maximum of 3 attempts before marking a query as failed.

Full pipeline details: `docs/ARCHITECTURE.md`.

---

## Features

- Self-correcting NL-to-SQL over your own PostgreSQL schemas
- Multi-agent pipeline with explicit schema linking and transparent responses
- Read-only execution with guardrails for destructive and sensitive queries
- Schema-agnostic: works on ecommerce, library, and your custom domains

---

## Quick Start — Your Database in 10 Minutes

This is the shortest path to running QueryPilot against your own PostgreSQL database.

### 1. Clone and configure

```bash
git clone https://github.com/your-username/querypilot.git
cd querypilot
cp .env.example .env
```

Edit `.env`:

```text
LLM_PROVIDER=groq              # or: openai
GROQ_API_KEY=your_groq_key     # if using Groq
OPENAI_API_KEY=your_openai_key # if using OpenAI
DATABASE_URL=postgresql://user:password@host:5432/yourdb
DEFAULT_SCHEMA=ecommerce       # or any schema key you define
CHROMA_HOST=chroma
CHROMA_PORT=8000
```

`DATABASE_URL` must point to a PostgreSQL instance that already has your tables created.

---

### 2. Register your schema (one command)

Use the helper script so you don’t have to edit Python files:

```bash
cd backend
python scripts/setup_schema.py \
  --schema-name my_schema \
  --pg-schema public
```

This script will:

- Connect to `DATABASE_URL` and confirm that `public` has at least one table.
- Add an entry for `my_schema` to `backend/app/schema_profiles.json` (if it doesn’t already exist).
- Run `scripts/index_schema.py` to build embeddings and create a dedicated Chroma collection.

You’ll see output like:

```text
=== QueryPilot Schema Setup ===
Schema name  : my_schema
PG schema    : public
[1/3] Connecting to database...
Found N tables: table1, table2, ...
[2/3] Registering in schema_profiles.json...
Added 'my_schema' to schema_profiles.json
[3/3] Indexing schema embeddings...
✅ Done.
```

If the schema is already registered, it will print a clear “already registered, skipping JSON update” message and go straight to re-indexing.

Full “your own DB” guide: `docs/GETTING_STARTED.md`.

---

### 3. Start the API

From the project root (recommended):

```bash
docker-compose up --build
```

This brings up: PostgreSQL, Chroma, and the FastAPI backend wired together.

Without Docker (for local dev):

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/health
# {"status": "ok", "schemas_available": ["ecommerce", "library", "my_schema"]}
```

`startup_index.py` can also be run once to index all schemas defined in `schema_profiles.json` at startup.

---

### 4. Query your data

Basic example:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
        "question": "Who are my top 10 customers by total spend?",
        "schema_name": "my_schema"
      }'
```

Example response shape:

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
    ["c_001", "Alice", "1234.56"],
    ...
  ],
  "row_count": 10,
  "error_type": null,
  "error_message": null
}
```

More examples and field definitions: `docs/API.md`.

---

## Live Demo

Public backend (Render):

https://querypilot-backend.onrender.com

Health check:

```bash
curl https://querypilot-backend.onrender.com/health
```

Remote eval runs reuse the same pipeline but go over the public internet, so latencies are higher than local Docker runs.

---

## Evaluation Results

QueryPilot was evaluated on:

These metrics measure execution success only: the SQL ran without error against Postgres and returned a result set (empty sets count for valid queries). Semantic correctness of the business answer is not measured.

- 70 core ecommerce queries (easy/medium/hard + product/customer/revenue/edge)
- 12 adversarial ecommerce queries (hallucination / unsafe intent)
- 15 library schema queries (generalizability test)

---

## Results — Ecommerce Schema

| Category        | Total | Success | Rate   |
|-----------------|-------|---------|--------|
| Easy            | 10    | 10      | 100.0% |
| Medium          | 10    | 10      | 100.0% |
| Hard            | 10    | 8       | 80.0%  |
| Custom Product  | 10    | 10      | 100.0% |
| Custom Customer | 10    | 10      | 100.0% |
| Custom Revenue  | 10    | 10      | 100.0% |
| Edge Cases      | 10    | 9       | 90.0%  |
| **Core Total**  | 70    | 67      | 95.7%  |
| Adversarial     | 12    | 9       | 75.0%  |

For adversarial queries, “Success” means the system either blocked the query or avoided hallucinating non-existent tables according to the adversarial success definition in docs/EVALUATION_REPORT.md.

**First-attempt success rate:** 63/70 = 90.0%  
**Final success rate (with self-correction):** 67/70 = 95.7%  
**Correction lift:** +5.7pp  
**Queries recovered by self-correction:** 4 out of 7 first-attempt failures

**Retry distribution (core queries):**

- 1 attempt: 63 queries
- 2 attempts: 0 queries
- 3 attempts: 7 queries
- Average attempts: 1.20

**Hallucination rate (syntactic):** 0.0%

---

## Results — Library Schema (15 queries, generalizability)

| Category | Total | Success | Rate   |
|----------|-------|---------|--------|
| Easy     | 5     | 5       | 100.0% |
| Medium   | 5     | 5       | 100.0% |
| Hard     | 5     | 5       | 100.0% |
| Total    | 15    | 15      | 100%   |

**Schema linking note:** The library schema (books, members, loans, fines) uses entirely different domain vocabulary from ecommerce. The schema linker resolved all 15 queries correctly using vector-similarity retrieval alone, with no schema-specific tuning. This indicates the RAG-based schema linking generalizes across domains.

---

## Documentation

Everything you need to understand and run QueryPilot is under `docs/`.

| Document | What it covers |
|----------|---------------|
| docs/GETTING_STARTED.md | Use QueryPilot with your own DB in ~10 minutes |
| docs/ARCHITECTURE.md | Agent design, LangGraph state machine, schema profiles |
| docs/API.md | HTTP endpoints, request/response models, examples |
| docs/EVALUATION_REPORT.md | Full evaluation metrics and methodology |
| docs/DEPLOYMENT.md | Local Docker and cloud (Render / Neon) deployment |
| docs/daily-logs/ | Day-by-day build log and decisions |

The README is a high-level entry point; all technical depth lives in these docs.

---

## Schemas Included

Two example schemas ship with QueryPilot:

- **ecommerce** — customers, orders, order_items, products, categories, reviews, payments, inventory.
- **library** — books, members, loans, fines (plus supporting relationships).

You can add your own schema via:

```bash
python backend/scripts/setup_schema.py \
  --schema-name my_schema \
  --pg-schema public
```

Then pass `"schema_name": "my_schema"` in `/query` requests.

---

## Tech Stack

| Component | Technology |
|------------|------------|
| API | FastAPI |
| Orchestration | LangGraph |
| LLM | Groq llama-3.3-70b or OpenAI gpt-4o-mini |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Vector DB | ChromaDB (file-based persistence) |
| SQL DB | PostgreSQL 16 (local Docker / Neon in the cloud) |
| Deployment | Docker + docker-compose · Render for public demo |

Neon is recommended for long-lived cloud Postgres so your demo data doesn’t expire. See `docs/DEPLOYMENT.md` for the exact connection string format and migration steps.

