# Day 1 – QueryPilot: Schema Intelligence & Infrastructure

**Date:** 5 Feb 2026  
**Project:** QueryPilot – Self-Correcting Multi-Agent Text-to-SQL System  
**Focus:** Infrastructure + Schema Intelligence (no LangGraph yet)

---

## 1. What QueryPilot Is (Day 1 Understanding)

### 1.1 High-Level Vision

QueryPilot is a **Text-to-SQL assistant**:

- User asks:  
  > "What are the top 10 products by revenue this quarter?"
- System:
  1. Understands the question
  2. Figures out which database tables are relevant
  3. Generates SQL
  4. Executes it on a **real PostgreSQL database**
  5. Returns results (tables, charts, natural language summary)
  6. **If SQL fails, it fixes itself and retries** (self-correction loop on later days)

The **unique value** vs typical Text-to-SQL:
- Multi-agent design instead of one giant prompt
- Schema-aware (reduces hallucinations)
- Self-correcting (retries with intelligence)
- Production-focused (Docker, metrics, tests, deployment)

Day 1 is about only one thing:
> “Make the system understand the schema of the database reliably and efficiently.”

This is the **Schema Intelligence Layer**:
- Extract metadata from PostgreSQL
- Turn schema into embeddings (vectors)
- Store in Chroma DB
- Retrieve relevant tables for any natural language question

---

## 2. Day 1 Goals (What Today Was Supposed to Achieve)

From roadmap + execution checklist:

- Get **PostgreSQL + Chroma** running via Docker with persistence
- Build **Schema Metadata Extractor**
- Build **Schema Embedder** using sentence-transformers (local, no API cost)
- Integrate **Chroma DB** as a vector store
- Implement **Schema Linker Agent v1**
- Validate:
  - Schema indexed
  - Recall ≥ 85% on test questions
  - Latency < 500 ms

Additional constraints (PROJECT-RULES):

- No LangGraph complexity yet (no state machines, no self-correction loops)
- Ship a **minimal but working** schema intelligence layer
- Don’t over-focus on metrics, charts, or UI
- Prefer shipping something slightly dumb-but-working over clever-but-broken

---

## 3. Architecture Decisions (Day 1)

### 3.1 Why Docker First?

Usually you code first, containerize later.  
Here we inverted it: **Docker → DB → Code**.

Reason:
- The entire system depends on having a **real database schema**.
- Schema extraction, embeddings, and retrieval all need real tables.
- Mocking the database early would:
  - Hide real-world schema issues
  - Force rewrites when real DB is connected
- By starting with Docker:
  - You get a real PostgreSQL instance
  - You verify persistence on Day 1
  - All code is written **against the real schema**, not guesses

**Key outcome:** No surprises later; everything tested on the actual database structure from day one.

---

### 3.2 Why PostgreSQL (Not MySQL, etc.)?

- Rich SQL dialect with many examples in Text-to-SQL literature
- Strong ecosystem and tooling
- Good default for analytics-style queries (joins, aggregates, window functions)
- Roadmap & quick-start docs already assume PostgreSQL

For this project, PostgreSQL is **the single source of truth** for:
- Tables, columns, and constraints
- Realistic e-commerce domain (customers, orders, products, etc.)

---

### 3.3 Why Chroma DB as Vector Store?

- Simple to run in Docker
- HTTP API + Python client
- Fine for schema-scale embeddings (dozens/hundreds, not millions)
- Built-in persistence with a simple volume

In this project, Chroma stores **schema embeddings**, not document chunks:
- Each table and column becomes a semantic vector
- Natural language questions are embedded and compared against these

This is what allows:
> “Show customer reviews and ratings” → match to `reviews` + `products` tables.

---

### 3.4 Why Sentence-Transformers for Embeddings (Not OpenAI)?

- **Primary reason:** Cost and control
  - No API calls = zero cost for embeddings
  - All local, works offline once models are cached
- `all-MiniLM-L6-v2`:
  - Small and fast
  - Good general-purpose semantic similarity model
  - Perfect for “table/column description ↔ question” matching

Design choice:
- Use sentence-transformers **only for embeddings**.
- Use Groq / OpenAI **only for SQL generation and reasoning** (later days).

---

### 3.5 Why Groq + OpenAI Dual Setup?

You configured:
- **Primary LLM Provider:** Groq (`LLM_PROVIDER=groq`)
  - Free, fast, great for experimentation
- **Backup LLM Provider:** OpenAI (GPT-4o-mini)
  - Paid, but you have credits
  - Used when:
    - Need comparison
    - Want more robust behavior in tricky cases

Design principle:
- Central `get_llm()` factory that returns Groq or OpenAI based on config
- No tight coupling to a single LLM vendor
- You can switch providers via `.env` without touching core logic

**Day 1:** Only config and wiring, **no LLM calls yet**.

---

## 4. Concrete Things Implemented Today

### 4.1 Docker & Database Setup

Files:
- `docker-compose.yml`
- `database/schemas/ecommerce.sql`

What’s inside:
- **PostgreSQL 16 container**
  - DB name: `ecommerce`
  - User: `admin`
  - Password: `devpassword`
  - Volume: `postgres_data:/var/lib/postgresql/data` (persistence)
  - Init script: `ecommerce.sql` mounted to `docker-entrypoint-initdb.d/01-schema.sql`

- **Chroma DB container**
  - Image: `chromadb/chroma:1.4.1`
  - Port: `8000`
  - Volume: `chroma_data:/chroma/chroma`
  - Persistent vector store

**E-commerce schema: 7 core tables**
- `customers`
- `categories`
- `products`
- `orders`
- `order_items`
- `reviews`
- `payments`

They form a realistic relational graph:
- `orders` reference `customers`
- `order_items` reference `orders` & `products`
- `reviews` reference `products` & `customers`
- `payments` reference `orders`

---

### 4.2 Persistence Verification (Critical Safety Check)

Goal: **Ensure Postgres data survives container restarts.**

Steps performed:
1. Created `persistence_test` table.
2. Inserted 3 rows.
3. Stopped containers via `docker-compose down`.
4. Restarted via `docker-compose up -d`.
5. Reconnected and confirmed rows were still there.

Why this matters:
- Prevents “oops everything disappeared” moments later.
- Confirms `postgres_data` volume is correctly mounted.
- You can confidently build features assuming the data won’t vanish.

Later, you optionally dropped `persistence_test` to keep the schema clean.

---

### 4.3 Python Environment & Config

Structure created:
- `backend/venv` (virtual environment)
- `backend/requirements.txt` with updated versions (langchain 1.x, chromadb 1.4.1, etc.)

Config module:
- `backend/app/config.py`

Key features:
- Loads `.env` using `pydantic_settings.BaseSettings`
- Supports:
  - `LLM_PROVIDER` = `"groq"` or `"openai"`
  - `GROQ_API_KEY`, `GROQ_MODEL_NAME`
  - `OPENAI_API_KEY`, `OPENAI_MODEL_NAME`
  - `DATABASE_URL`
  - `CHROMA_URL`
  - `MAX_RETRIES`, `QUERY_TIMEOUT`
- Provides `get_llm()` helper that returns either:
  - `ChatGroq` (via `langchain_groq`)
  - `ChatOpenAI` (via `langchain_openai`)

**Day 1 usage:** Only tested config loading, no LLM calls yet.

---

### 4.4 Schema Metadata Extractor

File:
- `backend/app/schema/extractor.py`

Class: `SchemaMetadataExtractor`

Responsibilities:
- Connect to PostgreSQL using `SQLAlchemy`
- Use `inspect()` to introspect:
  - All table names
  - Columns per table
  - Data types
  - Primary keys
  - Foreign key relationships

Output structure (per table roughly):

```python
{
  "customers": {
    "columns": ["customer_id", "name", "email", "created_at", "country", "lifetime_value"],
    "data_types": {"customer_id": "INTEGER", "name": "VARCHAR(100)", ...},
    "primary_keys": ["customer_id"],
    "foreign_keys": [],
    "column_count": 6
  },
  ...
}
```

Extra helper methods:
- `get_table_description(table_name)` → human-readable summary
- `get_database_summary()` → overall table + column counts

Tested via:
- `python -m app.schema.extractor`

Verified:
- 7 tables detected
- Correct column counts and relationships.

---

### 4.5 Schema Embedder

File:
- `backend/app/schema/embedder.py`

Class: `SchemaEmbedder`

Model:
- `all-MiniLM-L6-v2` via `sentence-transformers`

Responsibilities:
- Convert schema metadata into **text descriptions** + embeddings:
  - Table-level documents:
    - "Table: customers. Columns: customer_id, name, email, created_at, country, lifetime_value"
  - Column-level documents:
    - "Column: email in table customers. Type: VARCHAR(100)"
- Generate:
  - `documents`: list of description strings
  - `embeddings`: list of vectors (lists of floats)
  - `metadatas`: per-embedding metadata dicts with:
    - `type`: `"table"` or `"column"`
    - `table_name`
    - `column_name` (for column embeddings)
    - `data_type`
- Expose `embed_question(question)` to embed user queries.

Key point:
- Embeddings are fully **local** (no external API calls).
- One-time model download from Hugging Face, then cached.

---

### 4.6 Chroma DB Manager

File:
- `backend/app/schema/chroma_manager.py`

Class: `ChromaManager`

Responsibilities:
- Connect to Chroma HTTP server
- Create or reset a collection: `querypilot_schema`
- Add embeddings:
  - Generates IDs: `schema_0`, `schema_1`, ...
  - Stores documents, embeddings, metadatas
- Query embeddings:
  - `search_schema(query_embedding, n_results=10)`

Test:
- Added dummy embeddings
- Queried them back
- Verified Chroma connectivity and basic operations

---

### 4.7 Schema Linker Agent

File:
- `backend/app/agents/schema_linker.py`

Class: `SchemaLinker`

Responsibilities:
1. At startup:
   - Extract schema from DB
   - Generate embeddings (via `SchemaEmbedder`)
   - Store them in Chroma (via `ChromaManager`)
   - Cache raw schema metadata for later use
2. At query time:
   - Embed the question with `SchemaEmbedder`
   - Query Chroma for top-k closest schema elements
   - Group results by `table_name`
   - Return a **filtered schema dict** mapping:

```python
{
  "products": [...columns...],
  "order_items": [...columns...],
  ...
}
```

This is the Day 1 **core capability**:
> “Given a question, return the most relevant tables/columns from the database.”

---

### 4.8 Retrieval Quality Evaluation

File:
- `backend/tests/test_schema_retrieval.py`

Tested questions:
1. “What are the top 10 products by revenue?”
2. “Show me customer information”
3. “Find orders from last month”
4. “Which products have low stock?”
5. “Show customer reviews and ratings”

For each:
- Defined ground-truth expected tables
- Compared actual retrieved tables
- Computed:
  - **Recall** = relevant_retrieved / relevant_total
  - **Precision** = relevant_retrieved / retrieved_total

Results:
- Average Recall: **90%** (Target ≥ 85%) ✅
- Average Precision: **38.33%** (Target ≥ 70%) ⚠️

Interpretation:
- Recall is excellent → we are not missing important tables
- Precision is low → we include extra but semantically related tables:
  - e.g., question about customers brings in `orders` and `reviews`
- This is acceptable and even **desirable** at this stage:
  - LLM can ignore unused tables
  - Missing a table is much worse than including an extra one

Decision:
- **Do NOT over-optimize precision on Day 1.**
- Trust later agents + prompts to focus on necessary tables.

---

## 5. What Worked Well vs. What Didn’t

### 5.1 What Worked Well

- Docker + volumes worked after minor tweaking.
- Persistence test confirmed stable Postgres setup.
- sentence-transformers integrated smoothly; model downloaded and ran on CPU fine.
- Chroma DB HTTP client worked well with the 1.4.1 API.
- Schema Linker retrieval was fast (tens of ms) with good recall.

### 5.2 What Didn’t / Trade-offs

- Precision is significantly below the 70% target:
  - But this is **not a blocker** today.
  - Over-precise retrieval can hurt if it misses related tables for follow-ups.
- Could add more synthetic data to make retrieval patterns richer.
- Some noise from logs (httpx, Chroma, HF) but that’s acceptable for dev.

---

## 6. Why Day 1 Matters for the Overall System

This day laid the **foundation for hallucination prevention**:

- Without schema intelligence:
  - LLM might invent `user_profiles` or `transactions` tables that don’t exist.
- With schema intelligence:
  - LLM will be constrained to **only known tables/columns**.
  - It drastically lowers the chance of referencing non-existent fields.

Everything built later (SQL generator, critic, executor, self-correction loop) will **depend on this layer** to:
- Provide accurate schema context
- Avoid unnecessary trial-and-error with unknown tables

Today’s work is the **“schema brain”** of QueryPilot.

---

## 7. Summary of Day 1 Status

You can truthfully say:

> “On Day 1 of QueryPilot, I built a complete schema intelligence layer on top of a Dockerized PostgreSQL e-commerce database. The system now extracts schema metadata, generates local embeddings with sentence-transformers, stores them in Chroma DB, and retrieves relevant tables for natural language questions with 90% recall.”

---

## 8. Plan for Day 2 (Preview)

Next step: **SQL Generation Agent** (using Groq primarily).

High-level Day 2 tasks:
- Design SQL prompt template (schema + question + instructions)
- Implement SQL Generator:
  - Uses `get_llm()` (Groq by default)
  - Takes question + filtered schema from Schema Linker
  - Returns candidate SQL string
- Build a small evaluation set (20 questions)
- Run them through:
  - question → schema linker → SQL generator → (manual/automatic execution)
- Measure:
  - Basic execution success rate (even without self-correction)
  - Common error patterns to inform critic/executor later

Day 2 will start turning today’s **schema intelligence** into actual **SQL generation.**
