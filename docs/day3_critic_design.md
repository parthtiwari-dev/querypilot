# Day 3: Critic Agent Design
**Date:** February 5, 2026

## Purpose
Validate generated SQL before execution to catch errors early.

## Architecture
**4-layer validation pipeline:**
1. Syntax validation (sqlparse)
2. Schema validation (table/column existence)
3. Safety validation (block destructive ops)
4. Semantic validation (structural issues)

## Confidence Scoring
### confidence = 1.0 

- Syntax error: -0.6
- Schema error: -0.4 (per missing table/column)
- Safety violation: = 0.0 (hard block)
- Semantic issue: -0.2 (per issue)

**Clamp: max(0, min(confidence, 1))**

***Valid if: confidence >= 0.7 and confidence > 0***


## Validation Layers

### Layer 1: Syntax
- Tool: sqlparse
- Check: Valid PostgreSQL syntax
- Impact: -0.6

### Layer 2: Schema
- Check: All tables in filtered_schema
- Check: All columns in table columns
- Handle: Table aliases (p.product_id)
- Impact: -0.4 per error

### Layer 3: Safety
- Blocklist: DROP, DELETE, ALTER, TRUNCATE, UPDATE, INSERT, CREATE
- Impact: = 0.0 (immediate fail)

### Layer 4: Semantic (Mechanical)
- Check: Multiple tables → Expect JOIN
- Check: Aggregation + multiple columns → Expect GROUP BY
- No NLP, no question parsing
- Impact: -0.2 per issue

## Expected Outcomes
- Catch Day 2 failure (products.id) → confidence 0.6
- Detection rate: >80% on adversarial set
- False positive rate: <15%
- Latency: <100ms (no LLM)

## What's Out of Scope
- ❌ SQL regeneration (Day 5)
- ❌ Error classification (Day 4)
- ❌ Complex semantic analysis
- ❌ ML-based validation
