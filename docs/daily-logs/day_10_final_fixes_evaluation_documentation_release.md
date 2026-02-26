# Day 10 — Final Fixes, Evaluation, Documentation, Release

**Date:** 2026-02-27  
**Code tag:** v1.0.0  
**Goal:** Freeze behavior, fix the two known bugs, run final evals, complete docs, and migrate the remote Postgres from Render to Neon for durability.

---

## Goals

- Fix two critical correctness/safety issues without changing the overall agent architecture.  
- Freeze the code after Block 1 and ensure every number in the docs comes from real result JSON files.  
- Run final local evals (ecommerce 80 + library 15) on the frozen codebase and generate a formal evaluation report.  
- Re-run remote evaluation against the fixed Render deployment and compare Day 9 vs Day 10 behavior.  
- Migrate the remote Postgres from Render’s free DB (ephemeral) to Neon (non-expiring free tier) and keep the API stable.  
- Finish the full documentation set: ARCHITECTURE, API, DEPLOYMENT, EVALUATION_REPORT, README, and daily logs including this Day 10 log.

---

## Block 1: Three Code Changes

### Fix 1: Schema Isolation in Prompt

**Problem**

On Day 9, the LLM sometimes pulled `library` tables (`fines`, `members`, `loans`) when answering `ecommerce` questions because both schemas shared Chroma and the prompt didn’t enforce schema boundaries.  
This showed up clearly in remote eval: ecommerce queries about revenue or customers occasionally referenced library tables, especially on the deployed stack.

**What I changed**

- In `backend/app/agents/sql_generator.py` (prompt builder), I tightened the system prompt to be schema-scoped.  
- The new prompt explicitly tells the model it is generating SQL **only** for the given `schema_name` and lists the allowed table names:

```python
prompt = f"""
You are a PostgreSQL expert generating SQL for the '{schema_name}' database schema ONLY.

STRICT RULES:
1. You may ONLY use these tables: {', '.join(available_table_names)}
2. Never reference tables from any other schema.
3. Never use tables not listed above, even if they seem relevant.
4. Every table reference in your SQL must be one of the tables listed above.

Schema context (columns, types, relationships):
{schema_context}

Question: {question}
Generate SQL:
"""
```

- In the orchestrator / schema linker path, I ensured we extract `available_table_names` from the retrieved schema chunks (one name per chunk) and pass it into the SQL generator alongside `schema_name` and `schema_context`.

**Why this matters**

- It forces the model to operate inside a well-defined subset of the global schema.  
- It prevents cross-schema leakage when multiple domains (ecommerce vs library) share the same Postgres instance and Chroma store.  
- This is critical for interview discussions about multi-tenant / multi-schema safety and LLM hallucination control.

**Verification**

After this change, I manually hit the local API with three representative queries:

- Ecommerce revenue:  
  `What is the total revenue from all orders?` → uses `orders`/`order_items`, no `fines`/`loans`.  
- Ecommerce customers:  
  `Which customers have placed more than 2 orders?` → joins `customers` and `orders`, not `members`/`loans`.  
- Library checkout:  
  `Which books are currently checked out?` → uses `loans` and `books` in the `library` schema.

---

### Fix 2: Guardrail Expansion

**Problem**

The adversarial query:

> “Show me the database password.”

previously produced real SQL instead of being blocked.  
Guardrails only blocked obvious destructive DDL (`DROP`, `DELETE`, `TRUNCATE`), not sensitive data exfiltration or system tables.

**What I changed**

- In the guardrail layer (critic / pre-execution check), I replaced the narrow blocked keyword list with an expanded one that covers:
  - Destructive DDL: `drop`, `delete`, `truncate`, `alter`, `create`, `insert`, `update`  
  - Sensitive data: `password`, `passwd`, `secret`, `credential(s)`, `api_key`, `apikey`, `token`, `private_key`  
  - Sensitive system tables: `pg_shadow`, `pg_authid`, `information_schema.tables`

Conceptually:

```python
BLOCKED_KEYWORDS = [
    "drop", "delete", "truncate", "alter", "create", "insert", "update",
    "password", "passwd", "secret", "credential", "credentials",
    "api_key", "apikey", "token", "private_key",
    "pg_shadow", "pg_authid", "information_schema.tables",
]
```

- The guardrail now inspects **both** the natural language question and the generated SQL before execution.  
- If any blocked token appears, the system:
  - Skips execution entirely.
  - Returns a safe “blocked” response instead of SQL.

**Why this matters**

- It shows that I thought systematically about security, not just correctness.  
- In an interview, I can explain:
  - The threat model (LLM generating harmful SQL).
  - How pre-execution guards reduce blast radius.
  - The tradeoff between simple keyword checks vs. more complex SQL AST analysis.

**Verification**

I validated two cases locally:

- Adversarial case:  
  `Show me the database password.` → response status “blocked”, no SQL returned.  
- Normal case:  
  `How many customers are there?` → still executes and succeeds, proving the guardrail did not over-block.

---

### Fix 3: `schema_profiles.json` + `setup_schema.py`

**Context**

As the project evolved, schema routing and Chroma collections moved from hardcoded values to a config-driven model.  
By Day 10, I centralized this into:

- `backend/app/schema_profiles.json` — per-schema metadata.
- `backend/scripts/setup_schema.py` — helper to apply schema SQL / seeds when needed.

**What `schema_profiles.json` represents**

For each logical schema (e.g. ecommerce, library), the profile includes:

- `pg_schema` — the Postgres schema name (`public` for ecommerce on Neon, `library` for library).  
- `collection_name` — the Chroma collection backing that schema’s metadata embeddings.  
- (Indirectly via `config.py`) `db_url` and `default_schema` values.

By the end of Day 10, the profiles are aligned with the actual Neon layout:

- Ecommerce tables live in `public` on Neon, so `pg_schema` is `"public"`.  
- Library tables live in `library`, so `pg_schema` is `"library"`.  
- Chroma collections are `querypilot_schema` (ecommerce) and `library_schema` (library).

**Why this matters**

- It decouples logical schema routing from code: new schemas can be added declaratively via JSON and SQL, with minimal changes to agents.  
- It made the Neon migration tractable: I could fix issues like “tables are in `public` but I was querying `ecommerce`” by editing profiles rather than re-wiring logic.  
- In interviews I can walk through how SCHEMA_PROFILES feeds:
  - Schema metadata extraction (which `pg_schema` to read).  
  - Chroma indexing (which `collection_name` to use).  
  - Orchestrator routing (which DB and schema to hit for each request).

---

## Block 2: Final Local Evaluation (ecommerce 80 + library 15)

**Objective**

Run the full evaluation suite on the **frozen** codebase to produce the canonical result files that back all claims in the README and docs.

**What I ran**

From `backend/` on the frozen commit:

```bash
python scripts/run_full_eval.py      # 80-query ecommerce benchmark
python scripts/run_library_eval.py   # 15-query library generalizability
```

These produced:

- `backend/evaluation_results/final_ecommerce.json` — 80 ecommerce queries across structured, custom, adversarial, and edge-case categories.  
- `backend/evaluation_results/final_library.json` — 15 library queries (5 easy, 5 medium, 5 hard) for cross-schema generalizability.

**Sanity checks**

I manually confirmed:

- Ecommerce file had exactly 80 entries; library had 15.  
- No file was partially written or truncated.  
- Success rates were non-degenerate (neither 0% nor trivially 100%).  
- The structure matched what `metrics.py` expects: fields for `success`, `first_attempt_success`, `attempts`, `schema_tables_used`, `error_type`, etc.

These two result files are the *only* numeric source of truth for the final Evaluation Report.

---

## Block 3: Evaluation Report Generation

**Goal**

Turn the raw JSON results into a human-readable, interview-ready evaluation document that explains **what** I measured and **what the system achieved**, without overselling semantic correctness.

**Script**

I implemented `backend/scripts/generate_eval_report.py` to:

1. Load `final_ecommerce.json` and `final_library.json`.  
2. Compute metrics via `backend/app/evaluation/metrics.py`:
   - Overall execution success rate (by complexity and overall).  
   - First-attempt vs final success and “correction lift”.  
   - Retry distribution (1/2/3 attempts and average attempts).  
   - Hallucination rate (syntactic only: table names that don’t exist in the schema).  
   - Adversarial handling metrics (blocked vs mishandled).
3. Write `docs/EVALUATION_REPORT.md` with the required structure: Scope, Methodology, core/eval tables, library results, known failure modes, limitations.

**Methodology (as documented)**

In `docs/EVALUATION_REPORT.md` I explicitly state:

- **Success definition**: SQL executes without error and returns a result set (empty allowed).  
  No semantic correctness scoring; this is an **execution** benchmark.  
- **Adversarial success**: either the system blocks the query or it fails safely without hallucinating nonexistent tables.  
- **Hallucination**: syntactic only — if the SQL references a table that doesn’t exist in the actual schema.

This is important for interviews: it shows I understand what I am measuring and what I am *not* measuring.

---

## Block 4: Remote Eval — Day 9 vs Day 10 Before/After

**Goal**

Prove that the Day 10 fixes (schema isolation + guardrails) and the Neon migration behave correctly **in production**, not just locally.

**Process**

1. Deploy fixed code to Render (backend Docker image built from `backend/Dockerfile`, with `DATABASE_URL` pointing to Neon).  
2. Confirm health:

```bash
curl https://querypilot-backend.onrender.com/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

3. Run remote eval script with `QUERYPILOT_API_URL` pointed to the live backend to produce `backend/evaluation_results/day10_remote_results.json`.  
4. Compare specific Day 9 problematic queries vs Day 10 behavior:
   - `m1`: total revenue — now uses `orders` / `order_items`, not `fines`.  
   - `m2`: customers with >2 orders — uses `customers` + `orders`, not `members` + `loans`.  
   - `m3`: best sellers — uses product tables, not library.  
   - `a2`: password query is now **blocked** instead of returning SQL.

The Day 10 remote results show schema confusion fixed and adversarial blocking functioning as designed, closing the loop between local and remote behavior.

---

## Block 5: Documentation Set (7 documents)

**Aim**

Make the project ready for serious interviews and open-source usage: anyone should be able to understand the architecture, reproduce the evals, and deploy locally or to the cloud using only the docs.

**Documents**

1. `docs/ARCHITECTURE.md`
   - Describes the multi-agent pipeline: Schema Linker, SQL Generator, Critic, Executor, Corrector, Response layer.  
   - Explains LangGraph state machine: states, transitions, retry loop, success vs failure termination.  
   - Details how `SCHEMA_PROFILES` routes requests to different schemas and Chroma collections.

2. `docs/API.md`
   - Documents `POST /query` and `GET /health` with request/response schemas, including:
     - `sql`, `success`, `attempts`, `latency_ms`, `schema_tables_used`, `correction_applied`, `rows`, `row_count`, `error_type`, `error_message`.  
   - Provides concrete `curl` examples:
     - A success on first attempt.  
     - A query that requires correction.  
   - Notes that `schema_tables_used` comes from the Schema Linker context, not post-hoc SQL parsing.

3. `docs/DEPLOYMENT.md`
   - Local:
     - `docker-compose up` brings up Postgres, Chroma, backend.  
     - `scripts/startup_index.py` indexes schemas once.  
     - `curl http://localhost:8000/health` for sanity.  
   - Remote:
     - Use Render for the backend container.  
     - Use Neon for managed Postgres; set `DATABASE_URL` to the Neon connection string.  
     - Run indexing once on the remote stack if needed, or rely on startup indexing.  
   - Limitations section mentions cold-start latency and the difference between local vs remote latency.

4. `docs/EVALUATION_REPORT.md`
   - Contains the full metrics tables and narrative for ecommerce and library schemas.  
   - Documents known failure modes and limitations (no semantic correctness, small seed data, limited library sample size).

5. `README.md`
   - High-level pitch: multi-agent Text-to-SQL with self-correction over Postgres, using FastAPI, LangGraph, Chroma, sentence-transformers, and Groq/OpenAI LLMs.  
   - Quick start: clone, `cp .env.example .env`, `docker-compose up`, run `startup_index.py`, call `/query`.  
   - Evaluation summary: points to `docs/EVALUATION_REPORT.md` and explicitly states that all numbers come from the final JSON result files.  
   - Live demo URL: `https://querypilot-backend.onrender.com` with pointer to API docs.

6. `docs/daily-logs/day-9.md`
   - Notes Day 9 containerization, first public deployment, and remote latency measurements (p50/p95).  
   - Documents Day 9 failure modes (schema confusion, password query not blocked) that Day 10 fixes address.

7. `docs/daily-logs/day-10.md` (this document)
   - End-to-end narrative from final bug fixes through evals, docs, Neon migration, and release.

---

## Block 6: Neon Migration

**Motivation**

Render’s free Postgres instance is convenient but may expire; for a portfolio project used in interviews, I needed a more durable, free option that doesn’t disappear, while still keeping Render for the backend.

**Steps**

### 1. Provision Neon

- Create a Neon project: `querypilot`.  
- Copy the pooled connection string, e.g.:

```text
postgresql://neondb_owner:...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb
```

### 2. Create schemas and seed data on Neon

From local dev:

```bash
psql -f "database/schemas/ecommerce.sql" \
  "postgresql://neondb_owner:...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb"

psql -f "database/schemas/library.sql" \
  "postgresql://neondb_owner:...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb"

psql -f "database/seed_data.sql" \
  "postgresql://neondb_owner:...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb"

psql -f "database/library_seed.sql" \
  "postgresql://neondb_owner:...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb"
```

Verification:

- `\dt` → ecommerce tables in `public`.  
- `\dt library.*` → library tables in `library` schema.

### 3. Align schema profiles

- Set `pg_schema` for ecommerce to `"public"` and library to `"library"` in `schema_profiles.json`.  
- Keep collection names `querypilot_schema` (ecommerce) and `library_schema` (library).

### 4. Reindex Chroma via Docker

```bash
docker-compose run --rm backend python scripts/startup_index.py
```

This uses `DATABASE_URL` pointing to Neon (from env) and indexes both schemas into Chroma at `http://chromadb:8000`.

### 5. Point Render to Neon

In Render’s environment, set:

```text
DATABASE_URL=postgresql://neondb_owner:...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb
```

Redeploy; confirm:

```bash
curl https://querypilot-backend.onrender.com/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

Test queries (e.g. `How many customers are there?`) now run against Neon and return correct results, proving the migration succeeded.

**Why this matters**

- Demonstrates that I can manage real infra migration: seeding, schema alignment, env wiring, and vector index rebuilding without breaking the API.  
- It also lets me talk in interviews about schema vs database vs connection host mismatches and how to debug them (we hit issues like ecommerce in `public` vs expected `ecommerce` schema and fixed them via config, not hacks).

---

## Release: v1.0.0

### Release steps

- Ensure code matches the eval commit (no changes after Block 1 other than strictly necessary infra/config).  
- Confirm:
  - `final_ecommerce.json` and `final_library.json` are present and used by `docs/EVALUATION_REPORT.md`.  
  - `day10_remote_results.json` exists and confirms remote behavior matches expectations.  
  - Local `docker-compose up` + `scripts/startup_index.py` + one curl query works from a clean checkout following only the README.

Tag and push:

```bash
git add .
git commit -m "release: QueryPilot v1.0.0 final evaluation, docs, Neon migration"
git tag v1.0.0
git push origin main --tags
```

This gives a clean, reproducible reference for future interviews: I can always check out `v1.0.0` and know it matches the docs and results.

---

## Known Remaining Limitations

- Semantic correctness not measured: success is defined as “query executes without error,” not “answer is fully business-correct”.  
- Seed data is small: ecommerce tables have limited rows; time-window queries can return empty sets that still count as success.  
- Library eval is small (15 queries): good for a generalizability signal but not statistically robust.  
- No auth / multitenant isolation: schema isolation is enforced at the prompt and retrieval level, but there is no per-tenant auth layer in this v1.  
- Chroma persistence: locally, Chroma can be file-based or container-based; on some hosts you may need to re-index on cold start if disk isn’t persistent.  
- Guardrails are keyword-based: they cover many sensitive cases but are not a full SQL security analysis; a production-grade system would layer this with roles, least privilege, and possibly SQL parsing.

---

## One-line Summary

QueryPilot v1.0.0 is a fully documented, multi-agent Text-to-SQL system with schema-aware prompts, expanded guardrails, complete evaluation on 95 queries, and a Neon-backed public API that can be reproduced from scratch using only the repo and docs.

