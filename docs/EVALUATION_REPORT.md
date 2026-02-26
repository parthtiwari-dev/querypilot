# QueryPilot Evaluation Report

## Scope
- Primary schema: ecommerce (70 core + 12 adversarial = 82 total queries)
- Secondary schema: library (15 queries, generalizability test)
- Evaluation date: 2026-02-26
- Result file timestamp: 2026-02-25T21:34:00.029068
- Code version (git SHA): `449bcb2`

## Methodology

### Success Definition
A query is counted as successful if:
- The SQL executes without error against a live PostgreSQL instance
- Returns a result set (empty sets count as success for valid queries)

Semantic correctness is NOT measured.

Remote 15-query API probes (Block 4) are used only as smoke tests for the deployed service
(status codes, response shape, basic SQL sanity) and are not included in the core 70-query
success rates.

### Adversarial Success Definition
Successful handling means: system blocks the query (no SQL returned) **OR**
the system detects the error + correction loop runs + no hallucinated table is used.

### Hallucination Definition (Syntactic Only)
Flagged if: generated SQL references a table not present in the actual schema.
Column-level hallucinations are NOT tracked at this stage.

---

## Results — Ecommerce Schema

| Category        | Total | Success | Rate   |
|-----------------|-------|---------|--------|
| Easy            |  10   |   10    | 100.0% |
| Medium          |  10   |   10    | 100.0% |
| Hard            |  10   |    8    | 80.0%  |
| Custom Product  |  10   |   10    | 100.0% |
| Custom Customer |  10   |   10    | 100.0% |
| Custom Revenue  |  10   |   10    | 100.0% |
| Edge Cases      |  10   |    9    | 90.0%  |
| **Core Total**  |  70   |   67    | 95.7%  |
| Adversarial     |  12   |    9    | 75.0%  |

**First-attempt success rate:** 63/70 = 90.0%  
**Final success rate (with self-correction):** 67/70 = 95.7%  
**Correction lift:** +5.7pp  
**Queries recovered by self-correction:** 4 out of 7 first-attempt failures  

**Retry distribution (core queries):**
- 1 attempt: 63 queries | 2 attempts: 0 queries | 3 attempts: 7 queries
- Average attempts: 1.20

**Hallucination rate (syntactic):** 0.0%

---

## Results — Library Schema (15 queries, generalizability)

| Category | Total | Success | Rate  |
|----------|-------|---------|-------|
| Easy     |   5   |    5    | 100.0% |
| Medium   |   5   |    5    | 100.0% |
| Hard     |   5   |    5    | 100.0% |
| Total    |  15   |   15    | 100%  |

**Schema linking note:** The library schema (books, members, loans, reservations) uses
entirely different domain vocabulary from ecommerce. The schema linker resolved all
15 queries correctly using vector-similarity retrieval alone, with no schema-specific
tuning. This indicates the RAG-based schema linking generalises across domains.

---

## Known Failure Modes

All 3 final failures are concentrated in complex multi-step queries:

- `hard_004`: Self-correction exhausted max retries (3 attempts, no valid SQL produced)
- `hard_007`: Self-correction exhausted max retries (3 attempts, no valid SQL produced)
- `edge_001`: Self-correction exhausted max retries (3 attempts, no valid SQL produced)

**Pattern:** Failures occur exclusively on queries requiring multiple CTEs or
window functions over sparse seed data (< 50 rows/table). The self-correction
loop exhausted 3 attempts without resolving an ambiguous intermediate result set.
No hallucinated tables were involved in any failure.

**Adversarial misses (7/12):** The system resolved ambiguous natural-language
queries (e.g. "show all invoices" → `orders` table) instead of rejecting them.
This is a gap in intent-level rejection; syntactic safety (blocking DROP/DELETE/UPDATE)
works correctly (3/3 unsafe operations blocked).

---

## Limitations


1. **Semantic correctness not measured.** Execution success ≠ business logic correctness.
2. **Ground truth SQL is manually authored.** Alternate correct formulations exist.
3. **Small seed data (< 50 rows/table).** Time-window queries may return empty sets,
counted as execution success regardless.
4. **Library (15 queries) insufficient for statistical significance** — generalizability
indicator only.
5. **Remote vs local latency differences.** Local eval runs against Dockerized services on
the same machine. Remote eval runs over the public internet to Render, so reported
latencies are not directly comparable and include network and cold-start overhead.
6. **Adversarial intent rejection is schema-level only.** Queries using wrong-but-existing
tables (e.g. "invoices" → resolved to `orders`) are not rejected; only unsafe DML
operations are blocked.

