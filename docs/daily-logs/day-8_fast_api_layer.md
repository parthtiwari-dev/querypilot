
# Day 8 — FastAPI Layer

## Objective

Expose the frozen QueryPilot pipeline as a clean HTTP API.
No agent changes. Thin wrapper only.

---

## What was built

### orchestrator.py

Single entry point for all pipeline callers (API, eval scripts, CLI):


```python
result = run_query(question="...", schema_name="ecommerce", max_attempts=3)
```

Key design decisions:

Module-level agent cache keyed by schema_name. Agents are expensive to instantiate
(LangGraph graph compile, embedding model load, DB connection pool).
The cache means first call per schema pays the init cost; all subsequent calls hit warm agents.

Fixed max_attempts=3 at cache creation time. The CorrectionAgent bakes max_attempts
into the compiled LangGraph. There is no clean way to override it per-request without recompiling
the graph. Accepted max_attempts in QueryRequest for API compatibility but it is currently
ignored at runtime. Fix deferred to a future phase.

Search path injection for non-public schemas. Library schema lives under pg_schema=library.
The orchestrator appends ?options=-csearch_path%3Dlibrary to the DB URL when building the
executor for the library profile. Ecommerce uses the default public schema and needs no injection.

---

## FastAPI wiring

app/api/models.py — QueryRequest and QueryResponse Pydantic models.

app/api/routes.py — POST /query and GET /health.

app/main.py — FastAPI app, router included.

Server: uvicorn app.main:app --reload --port 8001 from backend/.

---

## What was removed from eval scripts

Both run_full_eval.py and run_library_eval.py previously instantiated agents directly:

```python
schema_linker   = SchemaLinker(...)
sql_generator   = SQLGenerator()
critic          = CriticAgent()
executor        = ExecutorAgent(db_url)
correction_agent = CorrectionAgent(...)
```

These blocks were deleted. Both scripts now call orchestrator.run_query() instead.

Removed functions: get_schema_tables(), _serialize_rows(), build_db_url_with_schema().

Day 6 and Day 7 results were re-run after refactor — results were identical.

---

## Global variable threading risk

self_correction.py uses module-level globals for LangGraph node functions:

```python
global schema_linker, sql_generator, critic, executor
schema_linker = schema_linker
...
```

This is a design debt from Day 5 when LangGraph required closures, not dependency injection.

Risk: If two requests targeting different schemas are processed concurrently on the same
Python worker, the second request overwrites the globals mid-execution of the first.

Current mitigation: --workers 1 (uvicorn default) ensures single-threaded execution.
Concurrent requests are queued, not parallelised. Safe for development and single-user deployment.

Fix when needed: Refactor node functions to receive agents via state fields
(SQLCorrectionState.schema_linker, etc.) instead of module-level globals.
Deferred to Day 9+ since evaluation is single-threaded and this is a dev server.

---

## Parity test results

Script: backend/scripts/test_api_local.py

Baseline: evaluation_results/day6_full_results.json

Queries tested: 10 (3 easy, 4 medium, 2 hard, 1 adversarial)

| ID         | API success     | Base success     | Attempts api/base | Match |
|------------|----------------|------------------|------------------|-------|
| easy_001   | ✅              | ✅                | 1/1              | ✅    |
| easy_005   | ✅              | ✅                | 1/1              | SQL diff only |
| easy_010   | ✅              | ✅                | 1/1              | ✅    |
| medium_003 | ✅              | ✅                | 1/1              | ✅    |
| medium_007 | ✅              | ✅                | 1/1              | ✅    |
| medium_010 | ✅              | ✅                | 1/1              | ✅    |
| medium_009 | ✅              | ✅                | 1/1              | ✅    |
| hard_001   | ✅              | ✅                | 3/3              | ✅    |
| hard_005   | ✅              | ✅                | 1/3              | Improved |
| adv_004    | ❌ (blocked)    | ❌ (blocked)      | 1/1              | ✅    |

Behavioral parity: 10/10 (all success outcomes match baseline)

Strict SQL parity: 8/10 (2 diffs are LLM non-determinism, not bugs)


easy_005: different but valid SQL generated this run.

hard_005: succeeded on first attempt vs 3 in baseline — improvement, not regression.

---

## Latency

| Metric               | Value |
|----------------------|-------|
| p50 (warm cache)     | 2159ms |
| Worst case           | 25239ms |
| Worst case cause     | easy_001 — cold start (cache miss, graph compile, model load, DB connection warmup) |

First call per schema is always slow. From second call onward latency stabilises to 1200–3500ms
depending on query complexity and whether correction is needed.

---

## Surprises during wiring

main.py was accidentally placed in app/api/ instead of app/ root during initial file creation.
Uvicorn could not find app.main:app. Fixed by moving the file.

rows in the response was [[20]] (list of tuples) not [{"total_customers": 20}] (list of dicts).
Pydantic raised ResponseValidationError because the model declared rows: list[dict].
Fixed by relaxing the type to list[Any]. Proper dict serialization deferred to Day 9.

Port conflict: Chroma runs on localhost:8000 by default. Uvicorn also defaults to 8000.
Running uvicorn on --port 8001 resolved the conflict permanently.

---

## Definition of Done

- orchestrator.run_query() is the single entry point for all callers

- run_full_eval.py and run_library_eval.py produce identical results after refactor

- GET /health returns 200 with schema list

- POST /query returns all 11 fields on every call

- schema_tables_used populated on every successful query

- test_api_local.py passes 10/10 behavioral parity

- docs/API.md written

- docs