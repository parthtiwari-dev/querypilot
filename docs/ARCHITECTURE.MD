# QueryPilot Architecture

---

## Overview

QueryPilot is a self-correcting Text-to-SQL system built around a structured agent pipeline and a LangGraph state machine. The architecture ensures schema scoping, safe SQL generation, execution validation, and automated correction.

---

## End-to-End Pipeline

```
Question → Schema Linker → SQL Generator → Critic → Executor → Corrector → Response
```

Each stage is modular and independently testable.

---

# Agent Architecture

## 1. Schema Linker

**File**: `backend/app/agents/schema_linker.py`  
**Input**: Question + schema name  
**Output**: Filtered schema dictionary (tables → columns, PK/FK) + list of table names

### How It Works

- Uses `SchemaMetadataExtractor` to pull PostgreSQL metadata (`pg_schema` from schema profile).
- Embeds both tables and columns with `sentence-transformers/all-MiniLM-L6-v2`.
- Stores embeddings in per-schema Chroma collections:
  - `querypilot_ecommerce_v2`
  - `querypilot_library_v2`
  - Includes `schema_name` in metadata.
- For a question:
  - Embeds the text.
  - Queries Chroma with:

    ```python
    where={"schema_name": <schema>}
    ```

  - Retrieves nearest schema chunks.
- Groups hits by `table_name`.
- Expands via foreign keys to pull related tables.

### Why

Strictly scopes downstream LLM to real tables and columns for the selected schema and prevents cross-schema hallucinations.

---

## 2. SQL Generator

**File**: `backend/app/agents/sql_generator.py`  
**Input**: Question + filtered schema + schema name  
**Output**: Raw SQL string

### How It Works

- Builds a prompt containing:
  - `available_tables`
  - Plain-text schema description (columns, PKs, FKs)
- Uses `get_llm()` from `config.py`.
- Calls either:
  - Groq: `llama-3.1-70b-versatile`
  - OpenAI: `gpt-4o-mini`
  - Selected via `LLM_PROVIDER`.
- Enforces strict prompt rules:
  - Use only listed tables
  - No destructive DML
  - Always add `LIMIT`
  - Correct `GROUP BY`

### Why

Generates the initial SQL attempt while guaranteeing it references only allowed tables and columns.

---

## 3. Critic

**File**: `backend/app/agents/critic.py`  
**Input**: Generated SQL + schema context  
**Output**: Validation result (confidence / issues)

### How It Works

- Performs static checks:
  - Blocks keywords like `DROP`, `DELETE`, `ALTER`
- Verifies referenced tables exist in the filtered schema.
- Performs lightweight syntax checks before DB execution.

### Why

Catches unsafe or invalid queries early, saves database round trips, and provides structured error types for correction.

---

## 4. Executor

**File**: `backend/app/agents/executor.py`  
**Input**: Validated SQL  
**Output**: Result rows or structured error

### How It Works

- Builds a SQLAlchemy engine using `db_url` from schema profile.
- Injects `pg_schema` via `search_path` when needed.
- Executes in read-only mode.
- Enforces:
  - `LIMIT`
  - `QUERY_TIMEOUT`
- Normalizes results into `ExecutionResult`:
  - `data`
  - `error_type`
  - `error_message`

### Why

Safely executes SQL against PostgreSQL and abstracts connection pooling and error normalization.

---

## 5. Corrector

**File**: `backend/app/agents/self_correction.py`  
**Input**: Question + current SQL + execution result/error  
**Output**: Corrected SQL or final failure

### How It Works

- Implements a LangGraph state machine (`CorrectionAgent`).
- Orchestrates:

  ```
  SCHEMA_LINK → SQL_GENERATION → CRITIC_VALIDATION → EXECUTION → [SUCCESS | CORRECTION]
  ```

- On error, builds correction prompt containing:
  - Failed SQL
  - Error type
  - Database error message
  - Original question
- Calls:

  ```python
  SQLGenerator.generate_with_correction(...)
  ```

- Tracks:
  - `attempts`
  - `schema_tables_used`
  - Correction flag
  - Final `error_type` / `error_message`
- Stops after 3 attempts.
- Returns `MAX_RETRIES_EXCEEDED` if still failing.

### Why

Enables self-healing SQL generation and surfaces clear telemetry for evaluation.

---

# LangGraph State Machine

## State Flow

```
SCHEMA_LINKING → SQL_GENERATION → CRITIC_VALIDATION → EXECUTION → [SUCCESS | CORRECTION]
```

**Initial State**:

```
{ question, schema_name }
```

### SCHEMA_LINKING

- Calls `SchemaLinker.link_schema(question, schema_name=...)`
- Stores:
  - `schema_dict`
  - `schema_tables_used`

### SQL_GENERATION

- Calls `SQLGenerator.generate_sql(question, filtered_schema, schema_name=...)`

### CRITIC_VALIDATION

- Runs static validation
- Proceeds to:
  - `EXECUTION`
  - or `CORRECTION` if unsafe

### EXECUTION

- Calls `Executor.execute(sql)`
- Stores `ExecutionResult`

### CORRECTION

- If failure and `attempts < 3`
  - Builds correction prompt
  - Loops back to `SQL_GENERATION`
- If `attempts == 3`
  - Emits final failure with `MAX_RETRIES_EXCEEDED`

---

# Schema Profiles

**Defined in**: `backend/app/schema_profiles.json`  
Loaded by `config.py` at startup.

## Profile Structure

Each entry contains:

- `pg_schema` — PostgreSQL schema name
- `collection_name` — Chroma collection name

Example values:

- `public` (ecommerce)
- `library`
- `querypilot_ecommerce_v2`
- `querypilot_library_v2`

## Runtime Usage

### SchemaLinker

- Uses `collection_name` and `CHROMA_URL`.
- Uses `pg_schema` when extracting PostgreSQL metadata.

### Executor

- Uses `db_url`.
- Injects `pg_schema` into `search_path`.

## Adding a New Schema

1. Add profile entry to `schema_profiles.json`.
2. Run:

   ```bash
   docker-compose exec backend python scripts/setup_schema.py --schema-name <name> --pg-schema <pg_schema>
   ```

3. Redeploy.
4. `startup_index.py` indexes schema into its Chroma collection.

---

# Tech Stack

| Layer | Technology |
|--------|------------|
| API | FastAPI |
| Orchestration | LangGraph (CorrectionAgent graph) |
| LLM | Groq llama-3.1-70b-versatile or OpenAI gpt-4o-mini |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Vector DB | ChromaDB |
| SQL DB | PostgreSQL 16 (Neon cloud) |
| Containers | Docker + docker-compose |
| Deployment | Render (free tier) |

---

# High-Level Diagram

```mermaid
flowchart LR
    Q[Question] --> API[FastAPI /query]
    API --> ORCH[LangGraph Orchestrator (CorrectionAgent)]

    subgraph Pipeline
        ORCH --> SL[Schema Linker - Chroma + PG metadata]
        SL --> SG[SQL Generator - LLM]
        SG --> CR[Critic - static checks]
        CR --> EX[Executor - PostgreSQL]
        EX -->|success| R[Response]
        EX -->|error| CO[Corrector - LangGraph loop]
        CO --> SG
    end
```

