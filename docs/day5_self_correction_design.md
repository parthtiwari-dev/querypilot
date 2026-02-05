# Day 5: Self-Correction Loop - Design Document

**Author:** QueryPilot Team  
**Date:** February 5, 2026  
**Status:** Implementation Ready  
**Estimated Implementation Time:** 5-6 hours

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Solution Architecture](#solution-architecture)
4. [LangGraph State Machine](#langgraph-state-machine)
5. [Correction Strategies](#correction-strategies)
6. [Retry Logic](#retry-logic)
7. [Metrics & Observability](#metrics--observability)
8. [Integration Points](#integration-points)
9. [Testing Strategy](#testing-strategy)
10. [Success Criteria](#success-criteria)
11. [Design Improvements](#design-improvements)

---

## 1. Overview

### 1.1 Purpose

Implement a self-correction loop that **automatically fixes failed SQL queries** using error feedback from the executor. When a query fails, the system analyzes the error, generates a correction prompt, and regenerates SQL with up to 3 attempts.

### 1.2 Key Innovation

**Problem:** 25% of queries fail after Critic validation (Day 4 baseline: 75% success rate)

**Solution:** Self-correction loop that learns from execution errors

**Target:** 85%+ overall success rate (10%+ improvement)

### 1.3 Design Principles

1. **Minimal Complexity** - 3 correction strategies (not 7), 5 LangGraph nodes (not 10)
2. **Focused Corrections** - Fix column errors (70% of failures) and aggregation errors (20% of failures) first
3. **Separated Metrics** - Track first-attempt success separately from corrected success (don't hide weak generation)
4. **Aggressive Logging** - Log every attempt with SQL diffs for debugging
5. **Retry Guards** - Stop if SQL unchanged, max attempts reached, or non-retryable error

---

## 2. Problem Statement

### 2.1 Current Pipeline (Day 4)

```
Question 
  ↓
SchemaLinker → filtered_schema
  ↓
SQLGenerator → generated_sql
  ↓
CriticAgent → validation_result
  ↓
  if valid:
    ExecutorAgent → execution_result
      ↓
      if success: ✓ return data
      if fail: ✗ return error (NO RETRY)
```

**Issue:** 25% of queries fail and system gives up immediately.

### 2.2 Failure Analysis (Day 4 Results)

| Error Type | % of Failures | Retryable? | Priority |
|------------|---------------|------------|----------|
| column_not_found | 70% | ✅ Yes | **HIGH** |
| aggregation_error | 20% | ✅ Yes | **HIGH** |
| timeout | 5% | ✅ Yes | Medium |
| join_error | 3% | ✅ Yes | Low |
| syntax_error | 1% | ✅ Yes | Low |
| type_mismatch | 1% | ✅ Yes | Low |
| permission_denied | <1% | ❌ No | N/A |
| connection_error | <1% | ❌ No | N/A |

**Decision:** Focus on fixing **column_not_found** and **aggregation_error** first (90% of failures).

### 2.3 Why Retry Matters

**Example failure:**
```sql
-- Generated SQL (Attempt 1)
SELECT id, price FROM products WHERE category = 'Electronics'

-- Error: column "id" does not exist
-- Hint: Did you mean "product_id"?
```

**With self-correction:**
```sql
-- Corrected SQL (Attempt 2)
SELECT product_id, price FROM products WHERE category = 'Electronics'

-- ✓ Success!
```

**User Experience:** Query fails → system fixes itself → user sees success (transparent recovery)

---

## 3. Solution Architecture

### 3.1 High-Level Flow

```
Question 
  ↓
SchemaLinker → filtered_schema (CACHED, runs once only)
  ↓
┌─────────────── RETRY LOOP (max 3 attempts) ───────────────-┐
│                                                            │
│  SQLGenerator (with correction prompt if retry) → sql      │
│    ↓                                                       │
│  CriticAgent → validation                                  │
│    ↓                                                       │
│    if invalid:                                             │
│      → Generate correction prompt from Critic issues       │
│      → RETRY (increment attempt)                           │
│                                                            │
│    if valid:                                               │
│      ExecutorAgent → execution                             │
│        ↓                                                   │
│        if success: ✓ EXIT LOOP                             │
│        if fail:                                            │
│          → Classify error                                  │
│          → Generate correction prompt from execution error │
│          → RETRY (increment attempt)                       │
│                                                            │
│  Stop conditions:                                          │
│    - Max 3 attempts reached                                │
│    - SQL unchanged (retry guard)                           │
│    - Non-retryable error (permission_denied, etc.)         │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 3.2 Components

| Component | Responsibility | File |
|-----------|---------------|------|
| **CorrectionAgent** | Orchestrates retry loop, tracks metrics | `backend/app/agents/self_correction.py` |
| **LangGraph State Machine** | Manages state transitions, conditional routing | `backend/app/agents/self_correction.py` |
| **Correction Strategies** | Generates error-specific correction prompts | `backend/app/agents/correction_strategies.py` |
| **SQL Generator** | Adds `generate_with_correction()` method | `backend/app/agents/sql_generator.py` |

---

## 4. LangGraph State Machine

### 4.1 State Structure (Minimal)

```python
from typing import TypedDict, List, Dict, Any

class SQLCorrectionState(TypedDict):
    \"\"\"Minimal state for self-correction retry loop\"\"\"
    
    # Input
    question: str
    
    # Intermediate results
    filtered_schema: Dict[str, Any]
    generated_sql: str
    validation_result: Dict[str, Any]  # Includes 'issues' for Critic feedback
    execution_result: Dict[str, Any]
    
    # Retry tracking
    attempt_number: int
    max_attempts: int
    previous_sqls: List[str]  # For retry guard (detect unchanged SQL)
    
    # Output
    final_success: bool
```

**Design Decision:** Keep state **minimal**. No heavy fields like full correction history (log to file instead).

**🔧 Improvement 1:** `validation_result` must include `issues` field so Critic feedback can be used in correction prompts when execution never runs.

### 4.2 Graph Nodes (5 Total)

```python
from langgraph.graph import StateGraph, START, END

# Node 1: Schema Linking (RUNS ONCE ONLY)
def schema_link_node(state: SQLCorrectionState) -> SQLCorrectionState:
    \"\"\"Retrieve relevant schema using SchemaLinker (Day 1)
    
    🔧 Improvement 5: This node runs ONCE per question.
    Result is cached in state['filtered_schema'] for all retry attempts.
    \"\"\"
    logger.info("[Schema Link] Retrieving schema (ONCE per question)")
    filtered_schema = schema_linker.link_schema(state["question"])
    state["filtered_schema"] = filtered_schema
    logger.info(f"[Schema Link] Found {len(filtered_schema)} tables (cached for retries)")
    return state

# Node 2: SQL Generation (with correction support)
def generate_sql_node(state: SQLCorrectionState) -> SQLCorrectionState:
    \"\"\"Generate or regenerate SQL with correction prompt if retry
    
    🔧 Improvement 1: Correction prompts use:
    - Critic issues (if Critic blocked)
    - Execution errors (if execution failed)
    \"\"\"
    attempt = state["attempt_number"]
    logger.info(f"[Generate] Attempt {attempt}/{state['max_attempts']}")
    
    if attempt == 1:
        # First attempt: normal generation
        sql = sql_generator.generate(
            state["question"],
            state["filtered_schema"]
        )
        logger.info(f"[Generate] First attempt SQL: {sql[:60]}...")
    else:
        # Retry: generate with correction prompt
        correction_prompt = build_correction_prompt(state)
        
        sql = sql_generator.generate_with_correction(
            state["question"],
            state["filtered_schema"],
            correction_prompt
        )
        
        # 🔧 Improvement 4: Enhanced SQL diff logging
        previous_sql = state["previous_sqls"][-1]
        logger.info(f"[Generate] Retry SQL: {sql[:60]}...")
        diff_summary = get_sql_diff(previous_sql, sql)
        logger.info(f"[Diff] {diff_summary}")
    
    state["generated_sql"] = sql
    state["previous_sqls"].append(sql)
    return state

# Node 3: Critic Validation
def critic_node(state: SQLCorrectionState) -> SQLCorrectionState:
    \"\"\"Validate SQL before execution (Day 3)
    
    🔧 Improvement 1: Store issues for correction prompts
    \"\"\"
    logger.info(f"[Critic] Validating SQL...")
    result = critic.validate(
        state["generated_sql"],
        state["filtered_schema"],
        state["question"]
    )
    state["validation_result"] = {
        "is_valid": result.is_valid,
        "confidence": result.confidence,
        "issues": result.issues  # ← Store for correction prompts
    }
    logger.info(f"[Critic] Valid: {result.is_valid} (confidence: {result.confidence:.2f})")
    if not result.is_valid:
        logger.warning(f"[Critic] Issues: {result.issues}")
    return state

# Node 4: SQL Execution
def execute_node(state: SQLCorrectionState) -> SQLCorrectionState:
    \"\"\"Execute SQL with error classification (Day 4)\"\"\"
    logger.info(f"[Execute] Running SQL...")
    result = executor.execute(
        state["generated_sql"],
        schema=state["filtered_schema"]
    )
    state["execution_result"] = {
        "success": result.success,
        "data": result.data,
        "error_type": result.error_type,
        "error_message": result.error_message,
        "error_feedback": result.error_feedback,
        "execution_time_ms": result.execution_time_ms
    }
    
    if result.success:
        logger.info(f"[Execute] ✓ SUCCESS ({result.row_count} rows in {result.execution_time_ms:.1f}ms)")
    else:
        logger.error(f"[Execute] ✗ FAILED: {result.error_type}")
        logger.error(f"[Execute] Error: {result.error_feedback}")
    
    return state

# Node 5: Increment Attempt Counter
def increment_attempt_node(state: SQLCorrectionState) -> SQLCorrectionState:
    \"\"\"Increment attempt counter after deciding to retry
    
    🔧 Improvement 2: Increment AFTER generation decision, not before.
    This prevents attempt_number from exceeding max_attempts in metrics.
    \"\"\"
    state["attempt_number"] += 1
    logger.info(f"[Retry] Will retry as attempt {state['attempt_number']}/{state['max_attempts']}")
    return state
```

### 4.3 Conditional Routing

**Route 1: After Critic → Execute or Retry**

```python
def should_execute_or_retry(state: SQLCorrectionState) -> str:
    \"\"\"
    If Critic validates SQL → execute
    If Critic blocks SQL → retry with correction
    
    🔧 Improvement 1: When Critic blocks, correction prompt will use
    validation_result['issues'] since execution_result doesn't exist yet.
    \"\"\"
    if state["validation_result"]["is_valid"]:
        return "execute"
    else:
        # Critic found pre-execution issues, retry with Critic feedback
        logger.warning("[Route] Critic blocked SQL, will retry with validation feedback")
        return "increment_attempt"
```

**Route 2: After Execute → End or Retry**

```python
NON_RETRYABLE = {"permission_denied", "connection_error"}

def should_retry_or_end(state: SQLCorrectionState) -> str:
    \"\"\"
    If execution succeeded → END
    If max attempts → END
    If non-retryable error → END
    If SQL unchanged → END (retry guard)
    Otherwise → retry
    
    🔧 Improvement 2: Check attempt_number BEFORE incrementing.
    This ensures we don't exceed max_attempts.
    \"\"\"
    exec_result = state["execution_result"]
    attempt = state["attempt_number"]
    max_attempts = state["max_attempts"]
    
    # Success - done
    if exec_result["success"]:
        state["final_success"] = True
        logger.info(f"[End] ✓ SUCCESS on attempt {attempt}")
        return END
    
    # Max attempts - give up
    if attempt >= max_attempts:
        state["final_success"] = False
        logger.warning(f"[End] ✗ Max attempts ({max_attempts}) reached")
        return END
    
    # Non-retryable error - give up
    if exec_result["error_type"] in NON_RETRYABLE:
        state["final_success"] = False
        logger.warning(f"[End] ✗ Non-retryable error: {exec_result['error_type']}")
        return END
    
    # 🔧 Improvement 2: Retry guard with normalized comparison
    if len(state["previous_sqls"]) >= 2:
        current_sql = normalize_sql(state["previous_sqls"][-1])
        previous_sql = normalize_sql(state["previous_sqls"][-2])
        if current_sql == previous_sql:
            state["final_success"] = False
            logger.warning("[End] ✗ SQL unchanged, stopping retry")
            return END
    
    # Retry
    logger.info(f"[Retry] Error is retryable ({exec_result['error_type']}), preparing attempt {attempt + 1}")
    return "increment_attempt"
```

### 4.4 Graph Construction

```python
def create_self_correction_graph():
    \"\"\"Build LangGraph workflow
    
    🔧 Improvement 2: Node order ensures attempt_number is accurate.
    Flow: generate → critic/execute → (if retry) → increment → generate
    This means attempt_number represents completed attempts.
    \"\"\"
    workflow = StateGraph(SQLCorrectionState)
    
    # Add nodes
    workflow.add_node("schema_link", schema_link_node)
    workflow.add_node("generate_sql", generate_sql_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("increment_attempt", increment_attempt_node)
    
    # Linear edges
    workflow.add_edge("schema_link", "generate_sql")
    workflow.add_edge("generate_sql", "critic")
    
    # Conditional: Critic → Execute or Retry
    workflow.add_conditional_edges(
        "critic",
        should_execute_or_retry,
        {
            "execute": "execute",
            "increment_attempt": "increment_attempt"
        }
    )
    
    # Conditional: Execute → END or Retry
    workflow.add_conditional_edges(
        "execute",
        should_retry_or_end,
        {
            "increment_attempt": "increment_attempt",
            END: END
        }
    )
    
    # Retry loops back to generate
    workflow.add_edge("increment_attempt", "generate_sql")
    
    # Entry point
    workflow.set_entry_point("schema_link")
    
    return workflow.compile()
```

### 4.5 Graph Visualization

```
START
  ↓
schema_link (RUNS ONCE)
  ↓
generate_sql ←─────────┐
  ↓                     │
critic                  │
  ↓                     │
  ├→ (valid) → execute  │
  │              ↓      │
  │              ├→ (success) → END
  │              ↓      │
  │              └→ (fail/retryable) → increment_attempt ─┘
  │                     
  └→ (invalid) → increment_attempt ─┘
```

---

## 5. Correction Strategies

### 5.1 Strategy Design (3 Only)

**Priority:**
1. **ColumnCorrectionStrategy** - Fixes 70% of failures
2. **AggregationCorrectionStrategy** - Fixes 20% of failures
3. **GenericCorrectionStrategy** - Fallback for remaining 10%

**Deferred to Day 8+:**
- JoinCorrectionStrategy
- SyntaxCorrectionStrategy
- TypeMismatchCorrectionStrategy
- TimeoutCorrectionStrategy (use generic for now)

### 5.2 Correction Prompt Philosophy

**Bad (verbose):**
```
The previous SQL query failed with a column error:

Failed SQL:
SELECT id FROM products

Error Message:
column "id" does not exist

Hint: Did you mean "product_id"?

Available columns in the products table:
- product_id (integer)
- name (text)
- price (numeric)
...

Database Schema:
{full_schema_dump}

Please regenerate the SQL query for: "What products do we have?"

Instructions:
1. Identify the incorrect column name
2. Replace it with the correct column from the available columns list
3. Ensure all other query components remain correct
...
```
**Length:** 300+ tokens  
**Problem:** Too verbose, confuses LLM, wastes context

**Good (minimal):**
```
Failed SQL:
SELECT id FROM products

Error:
column "id" does not exist. Did you mean "product_id"?

Fix and regenerate for: "What products do we have?"
```
**Length:** 50 tokens  
**Benefit:** Concise, focused, LLM understands error from message

### 5.3 Building Correction Prompts

**🔧 Improvement 1: Correction prompt builder handles both Critic and Executor feedback**

```python
def build_correction_prompt(state: SQLCorrectionState) -> str:
    \"\"\"Build correction prompt from Critic or Executor feedback
    
    Handles two cases:
    1. Critic blocked SQL (validation_result has issues)
    2. Executor failed SQL (execution_result has error)
    \"\"\"
    failed_sql = state["generated_sql"]
    question = state["question"]
    
    # Case 1: Critic blocked (execution never ran)
    if not state["validation_result"]["is_valid"]:
        issues = state["validation_result"]["issues"]
        issues_text = "\\n".join(f"- {issue}" for issue in issues)
        
        return f\"\"\"
Failed SQL:
{failed_sql}

Critic Issues:
{issues_text}

Fix and regenerate for: "{question}"
\"\"\".strip()
    
    # Case 2: Execution failed
    exec_result = state["execution_result"]
    error_type = exec_result.get("error_type", "unknown")
    error_feedback = exec_result.get("error_feedback", exec_result.get("error_message", "Unknown error"))
    
    # Use strategy-specific prompt
    strategy = CorrectionStrategyFactory.get_strategy(error_type)
    return strategy.generate_prompt(failed_sql, error_feedback, question)
```

### 5.4 Strategy Implementations

#### 5.4.1 ColumnCorrectionStrategy

**Purpose:** Fix column name errors (70% of failures)

**Example Error:**
```
column "id" does not exist
Hint: Did you mean "product_id"?
```

**Correction Prompt:**
```python
class ColumnCorrectionStrategy:
    def generate_prompt(
        self,
        failed_sql: str,
        error_feedback: str,
        question: str
    ) -> str:
        return f\"\"\"
Failed SQL:
{failed_sql}

Error:
{error_feedback}

Fix the column name and regenerate for: "{question}"
\"\"\".strip()
```

**Why Minimal:** PostgreSQL error message already contains:
- The wrong column name
- The correct column name hint
- Schema context

LLM needs no additional information.

#### 5.4.2 AggregationCorrectionStrategy

**Purpose:** Fix aggregation errors (20% of failures)

**Example Error:**
```
column "products.name" must appear in GROUP BY clause or be used in an aggregate function
```

**🔧 Improvement 3: Add constraint to prevent oscillation**

**Correction Prompt:**
```python
class AggregationCorrectionStrategy:
    def generate_prompt(
        self,
        failed_sql: str,
        error_feedback: str,
        question: str
    ) -> str:
        return f\"\"\"
Failed SQL:
{failed_sql}

Error:
{error_feedback}

Fix the GROUP BY clause. Keep all aggregations (COUNT, SUM, AVG, etc.) and only add missing columns to GROUP BY.

Regenerate for: "{question}"
\"\"\".strip()
```

**🔧 Why This Helps:**
Without the constraint, LLM might:
- Attempt 1: Missing GROUP BY
- Attempt 2: Adds GROUP BY but removes COUNT()
- Attempt 3: Removes GROUP BY, adds COUNT() back → oscillation

The constraint "Keep all aggregations" stabilizes the correction.

#### 5.4.3 GenericCorrectionStrategy

**Purpose:** Fallback for all other errors (10% of failures)

**Correction Prompt:**
```python
class GenericCorrectionStrategy:
    def generate_prompt(
        self,
        failed_sql: str,
        error_feedback: str,
        question: str
    ) -> str:
        return f\"\"\"
Failed SQL:
{failed_sql}

Error:
{error_feedback}

Fix and regenerate for: "{question}"
\"\"\".strip()
```

**Why Generic Works:** Most errors (syntax, type mismatch, timeout) are self-explanatory from PostgreSQL error messages.

### 5.5 Strategy Selection

```python
class CorrectionStrategyFactory:
    \"\"\"Select correction strategy based on error type\"\"\"
    
    @staticmethod
    def get_strategy(error_type: str):
        if error_type == "column_not_found":
            return ColumnCorrectionStrategy()
        elif error_type == "aggregation_error":
            return AggregationCorrectionStrategy()
        else:
            # Fallback for all other errors
            return GenericCorrectionStrategy()
```

---

## 6. Retry Logic

### 6.1 Retry Conditions

**Retry if ALL conditions are true:**
1. ✅ Not at max attempts (default: 3)
2. ✅ Not a non-retryable error
3. ✅ SQL changed from previous attempt (retry guard)

**Stop if ANY condition is true:**
1. ❌ Max attempts reached
2. ❌ Non-retryable error (permission_denied, connection_error)
3. ❌ SQL unchanged (LLM regenerated identical query)
4. ✅ Execution succeeded

**🔧 Improvement 2: Attempt counting happens AFTER decision to retry, ensuring accurate metrics.**

### 6.2 Retry Guard (SQL Unchanged Detection)

**Problem:**
```
Attempt 1: SELECT id FROM products → column error
Attempt 2: SELECT id FROM products → (LLM regenerated SAME SQL!)
Attempt 3: SELECT id FROM products → wasted attempt
```

**Solution:**
```python
def normalize_sql(sql: str) -> str:
    \"\"\"Normalize SQL for comparison
    
    Removes:
    - Extra whitespace
    - Case differences (lowercase all)
    - Comments
    
    This avoids false positives from formatting changes.
    \"\"\"
    # Remove comments
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    sql = re.sub(r'/\\*.*?\\*/', '', sql, flags=re.DOTALL)
    
    # Normalize whitespace and lowercase
    return " ".join(sql.strip().lower().split())

def is_sql_unchanged(state: SQLCorrectionState) -> bool:
    \"\"\"Check if SQL identical to previous attempt\"\"\"
    if len(state["previous_sqls"]) < 2:
        return False
    
    current = normalize_sql(state["previous_sqls"][-1])
    previous = normalize_sql(state["previous_sqls"][-2])
    
    return current == previous
```

**Why Normalized:** Avoids false positives from whitespace/formatting changes while catching actual duplicate queries.

### 6.3 Non-Retryable Errors

```python
NON_RETRYABLE = {
    "permission_denied",  # User lacks privileges
    "connection_error"     # Database unreachable
}
```

**Why These?**
- **permission_denied:** No amount of SQL regeneration will fix lack of permissions
- **connection_error:** Database issue, not query issue

**Why Timeout IS Retryable:**
- Timeout often fixable by adding `LIMIT` or simplifying query
- LLM can optimize slow queries

### 6.4 Max Attempts

**Default:** 3 attempts

**Rationale:**
- **1 attempt:** No retry (Day 4 baseline)
- **2 attempts:** 1 retry, may not be enough
- **3 attempts:** 2 retries, good balance
- **4+ attempts:** Diminishing returns, wastes time

**Evidence from LLM research:** Most fixable errors resolve within 2 retries.

---

## 7. Metrics & Observability

### 7.1 Key Metrics (Separated Tracking)

```python
@dataclass
class CorrectionMetrics:
    \"\"\"Track first attempt vs corrected separately (don't hide weak generation)\"\"\"
    
    # Counts
    total_queries: int = 0
    first_attempt_success: int = 0  # Succeeded without retry
    corrected_success: int = 0      # Fixed by retry
    final_failures: int = 0         # Failed after all retries
    total_attempts: int = 0
    
    # Ratios (computed)
    @property
    def first_attempt_rate(self) -> float:
        \"\"\"How good is SQLGenerator WITHOUT correction?\"\"\"
        if self.total_queries == 0:
            return 0.0
        return self.first_attempt_success / self.total_queries
    
    @property
    def correction_effectiveness(self) -> float:
        \"\"\"How much does correction help?\"\"\"
        failed_initially = self.total_queries - self.first_attempt_success
        if failed_initially == 0:
            return 1.0
        return self.corrected_success / failed_initially
    
    @property
    def overall_success_rate(self) -> float:
        \"\"\"Success rate after correction\"\"\"
        if self.total_queries == 0:
            return 0.0
        return (self.first_attempt_success + self.corrected_success) / self.total_queries
    
    @property
    def avg_attempts(self) -> float:
        \"\"\"Average attempts per query\"\"\"
        if self.total_queries == 0:
            return 0.0
        return self.total_attempts / self.total_queries
```

### 7.2 Why Separate Tracking Matters

**Scenario 1: Good Generator**
```
First attempt rate: 85%
Correction effectiveness: 70%
Overall success rate: 89%
```
**Interpretation:** Generator is strong, correction adds marginal value.

**Scenario 2: Weak Generator Hidden by Correction**
```
First attempt rate: 30%
Correction effectiveness: 80%
Overall success rate: 85%
```
**Interpretation:** Generator is weak, correction masks the problem. **Action needed:** Improve SQLGenerator (better prompts, examples).

**If we only track overall:** Both scenarios show ~85% success, but underlying issues are different.

### 7.3 Logging Strategy

**Log at every step:**

```python
import logging
logger = logging.getLogger(__name__)

# Attempt start
logger.info(f"[Attempt {attempt}] Generating SQL...")

# SQL generated
logger.info(f"[Attempt {attempt}] SQL: {sql[:80]}...")

# Critic validation
logger.info(f"[Critic] Valid: {is_valid} (confidence: {confidence:.2f})")
if not is_valid:
    logger.warning(f"[Critic] Issues: {issues}")

# Execution result
if success:
    logger.info(f"[Execute] ✓ SUCCESS ({row_count} rows)")
else:
    logger.error(f"[Execute] ✗ FAILED: {error_type}")
    logger.error(f"[Execute] Error: {error_feedback}")

# 🔧 Improvement 4: Enhanced SQL diff on retry
if attempt > 1:
    diff_summary = get_sql_diff(previous_sql, current_sql)
    logger.info(f"[Diff] {diff_summary}")

# Retry decision
logger.info(f"[Retry] Retrying (attempt {attempt + 1})")

# Final result
logger.info(f"[Final] {'✓ SUCCESS' if success else '✗ FAILED'} after {attempt} attempts")
```

### 7.4 SQL Diff Utility

**🔧 Improvement 4: Show actual snippets, not just word positions**

```python
def get_sql_diff(sql1: str, sql2: str) -> str:
    \"\"\"Highlight changes between SQL queries with actual snippets
    
    🔧 Improvement 4: Returns meaningful diffs like:
    'id' → 'product_id'
    
    Instead of:
    Changed at word 2
    \"\"\"
    # Normalize for comparison
    norm1 = normalize_sql(sql1)
    norm2 = normalize_sql(sql2)
    
    if norm1 == norm2:
        return "No functional changes (formatting only)"
    
    # Split into words
    words1 = norm1.split()
    words2 = norm2.split()
    
    # Find differences
    changes = []
    max_len = max(len(words1), len(words2))
    
    for i in range(max_len):
        w1 = words1[i] if i < len(words1) else None
        w2 = words2[i] if i < len(words2) else None
        
        if w1 != w2:
            if w1 is None:
                changes.append(f"Added: '{w2}'")
            elif w2 is None:
                changes.append(f"Removed: '{w1}'")
            else:
                changes.append(f"Changed: '{w1}' → '{w2}'")
    
    if not changes:
        return "Structural changes detected"
    
    # Return first 3 changes (avoid log spam)
    summary = ", ".join(changes[:3])
    if len(changes) > 3:
        summary += f" (and {len(changes) - 3} more)"
    
    return summary
```

**Example output:**
```
[Diff] Changed: 'id' → 'product_id'
[Diff] Changed: 'name' → 'product_name', Added: 'group', Added: 'by'
[Diff] Removed: 'order', Removed: 'by', Changed: 'date' → 'created_at'
```

**Why Better:** Instant understanding of what changed, no need to compare queries manually.

---

## 8. Integration Points

### 8.1 Day 1: SchemaLinker

**Integration:** Called once at start, result cached in state.

**🔧 Improvement 5: Explicitly cache and reuse schema**

```python
# In schema_link_node
def schema_link_node(state: SQLCorrectionState) -> SQLCorrectionState:
    \"\"\"Schema linking runs ONCE per question
    
    🔧 Improvement 5: Schema is retrieved once and cached in state.
    All retry attempts reuse the same filtered_schema.
    
    Why: Schema linking is expensive (embedding similarity search).
    No need to repeat for same question.
    \"\"\"
    logger.info("[Schema Link] Retrieving schema (ONCE per question)")
    filtered_schema = schema_linker.link_schema(state["question"])
    state["filtered_schema"] = filtered_schema
    logger.info(f"[Schema Link] Cached {len(filtered_schema)} tables for all attempts")
    return state

# In generate_sql_node (all attempts)
def generate_sql_node(state: SQLCorrectionState) -> SQLCorrectionState:
    # Reuse cached schema
    filtered_schema = state["filtered_schema"]  # ← Already computed
    
    sql = sql_generator.generate(
        state["question"],
        filtered_schema  # ← Same schema for all attempts
    )
    ...
```

**No changes needed** to SchemaLinker implementation.

**Verification:**
- Add assertion: `assert "filtered_schema" in state`
- Log: "Using cached schema" on retry attempts

### 8.2 Day 2: SQLGenerator

**Integration:** Add `generate_with_correction()` method.

**Modification:** `backend/app/agents/sql_generator.py`

```python
class SQLGenerator:
    def generate(self, question: str, filtered_schema: Dict) -> str:
        \"\"\"Generate SQL (first attempt)\"\"\"
        # Existing implementation
        ...
    
    def generate_with_correction(
        self,
        question: str,
        filtered_schema: Dict,
        correction_prompt: str
    ) -> str:
        \"\"\"Generate SQL with correction prompt (retry)
        
        🔧 Improvement 1: correction_prompt can come from:
        - Critic issues (if Critic blocked)
        - Execution errors (if execution failed)
        \"\"\"
        # Prepend correction prompt to system message
        system_message = f\"\"\"{correction_prompt}

---

Original task: {question}

Schema:
{format_schema(filtered_schema)}

Generate corrected PostgreSQL query:
\"\"\"
        
        # Call LLM
        response = self.llm.invoke([HumanMessage(content=system_message)])
        sql = self.extract_sql(response.content)
        
        return sql
```

### 8.3 Day 3: CriticAgent

**Integration:** Called every attempt, no changes needed.

**🔧 Improvement 1: Issues are stored in state for correction prompts**

```python
# In critic_node
result = critic.validate(
    state["generated_sql"],
    state["filtered_schema"],
    state["question"]
)
state["validation_result"] = {
    "is_valid": result.is_valid,
    "confidence": result.confidence,
    "issues": result.issues  # ← Used if Critic blocks and we retry
}
```

**No changes needed** to CriticAgent implementation.

### 8.4 Day 4: ExecutorAgent

**Integration:** Called after Critic validation, no changes needed.

```python
# In execute_node
result = executor.execute(
    state["generated_sql"],
    schema=state["filtered_schema"]
)
```

**Leverages:** Executor's error classification and feedback (Day 4) for correction prompts.

**No changes needed** to ExecutorAgent implementation.

---

## 9. Testing Strategy

### 9.1 Test Dataset

**File:** `backend/app/evaluation/datasets/correction_tests.json`

**Structure:**
```json
[
  {
    "id": 1,
    "question": "What products do we have?",
    "expected_behavior": "first_attempt_success",
    "notes": "Simple query, should succeed on first try"
  },
  {
    "id": 2,
    "question": "Show me customer names and their order totals",
    "expected_behavior": "corrected_success",
    "error_type_expected": "column_not_found",
    "notes": "Generator likely uses 'id' instead of 'customer_id'"
  },
  {
    "id": 3,
    "question": "Average order value by product category",
    "expected_behavior": "corrected_success",
    "error_type_expected": "aggregation_error",
    "notes": "Generator likely forgets GROUP BY"
  }
]
```

**Coverage:**
- 5 queries: first-attempt success (baseline)
- 7 queries: column_not_found errors (correction)
- 3 queries: aggregation_error errors (correction)

**Total:** 15 test queries

### 9.2 Evaluation Script

**File:** `backend/scripts/run_day5_eval.py`

**Metrics to Collect:**
```python
{
  "total_queries": 15,
  "first_attempt_success": 5,
  "corrected_success": 8,
  "final_failures": 2,
  "avg_attempts": 1.6,
  "first_attempt_rate": 0.33,
  "correction_effectiveness": 0.80,
  "overall_success_rate": 0.87,
  "by_error_type": {
    "column_not_found": {
      "count": 7,
      "corrected": 6,
      "correction_rate": 0.86
    },
    "aggregation_error": {
      "count": 3,
      "corrected": 2,
      "correction_rate": 0.67
    }
  }
}
```

### 9.3 Comparison Script

**File:** `backend/scripts/compare_day4_day5.py`

**Compare:**
- Day 4: No retry (baseline 75%)
- Day 5: With retry (target 85%+)

**Output:**
```
Day 4 vs Day 5 Comparison
=========================
Metric                  Day 4    Day 5    Change
-------------------------------------------------
Success Rate            75.0%    87.0%    +12.0%
Avg Execution Time      12.8ms   18.5ms   +44.5%
Failed Queries          5/20     2/15     -60.0%
```

---

## 10. Success Criteria

### 10.1 Quantitative Metrics

| Metric | Target | Why It Matters |
|--------|--------|----------------|
| **First-attempt success rate** | >30% | Generator quality baseline |
| **Correction effectiveness** | >60% | Correction strategy performance |
| **Overall success rate** | >85% | System performance (Day 4: 75%) |

**All 3 must pass** for Day 5 to be successful.

### 10.2 Qualitative Criteria

- ✅ **Column errors fixed** - Most common failure resolved
- ✅ **Aggregation errors fixed** - Second most common failure resolved
- ✅ **Retry guard works** - No infinite loops, stops when SQL unchanged
- ✅ **Logging comprehensive** - Can debug any failed query from logs
- ✅ **Metrics separated** - Can identify if generator is weak

### 10.3 User Experience

**Before (Day 4):**
```
User: "What products do we have?"
System: ✗ Error: column "id" does not exist
```

**After (Day 5):**
```
User: "What products do we have?"
System: ✓ [Shows 50 products]
(Internally: Attempt 1 failed, Attempt 2 succeeded)
```

**Goal:** User never sees the failure.

---

## 11. Design Improvements

### 11.1 🔧 Improvement 1: Critic Failure Needs Structured Feedback

**Problem:**
```python
# Current flow
Critic invalid → retry
# But correction prompt pulls error from execution:
exec_result["error_feedback"]
# When Critic blocks SQL, execution never runs!
# So correction prompt may lack structured reason.
```

**Solution:**
Store Critic issues and use them when building correction prompts:

```python
state["validation_result"]["issues"]  # ← List of validation issues

# In build_correction_prompt():
if not state["validation_result"]["is_valid"]:
    # Use Critic issues (execution never ran)
    issues = state["validation_result"]["issues"]
    return f"Critic Issues: {issues}..."
else:
    # Use execution error (Critic passed but execution failed)
    return f"Error: {exec_result['error_feedback']}..."
```

**Impact:** Retries after Critic blocks now have proper correction signal.

---

### 11.2 🔧 Improvement 2: Attempt Counting Edge Case

**Problem:**
```python
# You increment attempt BEFORE regeneration:
attempt_number = 3
increment → 4
then exit
# Result may show 4 attempts even though max is 3
```

**Solution:**
Safer logic - increment AFTER deciding to retry:

```python
# Flow:
generate_sql (attempt N)
  ↓
critic/execute
  ↓
should_retry?
  ↓ YES
increment_attempt (N → N+1)
  ↓
generate_sql (attempt N+1)
```

**Implementation:**
```python
def should_retry_or_end(state: SQLCorrectionState) -> str:
    attempt = state["attempt_number"]  # Check BEFORE incrementing
    max_attempts = state["max_attempts"]
    
    if attempt >= max_attempts:
        return END  # Don't increment
    
    if retryable_error:
        return "increment_attempt"  # Increment happens in separate node

def increment_attempt_node(state: SQLCorrectionState) -> SQLCorrectionState:
    state["attempt_number"] += 1  # Only called when retry confirmed
    return state
```

**Impact:** Metrics accurately reflect actual attempts (max 3, never 4).

---

### 11.3 🔧 Improvement 3: Aggregation Correction Needs One Hint

**Problem:**
```python
# Aggregation retries sometimes oscillate:
Attempt 1: missing GROUP BY
Attempt 2: adds GROUP BY but drops COUNT()
Attempt 3: removes GROUP BY, adds COUNT() back
# LLM confused about what to keep
```

**Solution:**
Add minimal constraint to correction prompt:

```python
# Old prompt:
"Fix the GROUP BY clause and regenerate"

# New prompt:
"Fix the GROUP BY clause. Keep all aggregations (COUNT, SUM, AVG, etc.) and only add missing columns to GROUP BY."
```

**Impact:** Stabilizes aggregation corrections, reduces oscillation.

---

### 11.4 🔧 Improvement 4: SQL Diff Is Too Naive

**Problem:**
```python
# Current diff:
"Changed at word 2"
# Not helpful for debugging
```

**Solution:**
Show actual snippets:

```python
def get_sql_diff(sql1: str, sql2: str) -> str:
    # Find differences
    changes = []
    for i, (w1, w2) in enumerate(zip(words1, words2)):
        if w1 != w2:
            changes.append(f"'{w1}' → '{w2}'")
    
    return ", ".join(changes[:3])

# Output:
"Changed: 'id' → 'product_id'"
"Changed: 'name' → 'product_name', Added: 'group'"
```

**Impact:** Debugging becomes instant, no manual SQL comparison needed.

---

### 11.5 🔧 Improvement 5: Schema Linking Is Reused Correctly

**Current Design:** Schema linker runs only once per question ✅

**Verification:**
```python
def schema_link_node(state: SQLCorrectionState) -> SQLCorrectionState:
    # Runs once at start
    filtered_schema = schema_linker.link_schema(state["question"])
    state["filtered_schema"] = filtered_schema  # Cached
    
    # All retry attempts reuse state["filtered_schema"]
    return state
```

**Why Correct:**
- Schema linking is expensive (embedding search in ChromaDB)
- Question doesn't change across retry attempts
- Schema is same for all attempts

**Just Keep It This Way:** No changes needed, design is already optimal.

---

## 12. Implementation Checklist

### Phase 1: Core Infrastructure (Block 1)
- [ ] Design document (this file) ✅
- [ ] LangGraph state machine (5 nodes)
- [ ] CorrectionAgent wrapper class
- [ ] Correction metrics dataclass
- [ ] Retry guard implementation (normalized SQL comparison)
- [ ] SQL diff utility (show actual snippets)

### Phase 2: Correction Strategies (Block 2)
- [ ] ColumnCorrectionStrategy
- [ ] AggregationCorrectionStrategy (with "keep aggregations" hint)
- [ ] GenericCorrectionStrategy
- [ ] CorrectionStrategyFactory
- [ ] build_correction_prompt() (handles Critic + Executor feedback)
- [ ] Modify SQLGenerator (add generate_with_correction)

### Phase 3: Testing (Block 3)
- [ ] Create correction_tests.json (15 queries)
- [ ] Implement run_day5_eval.py
- [ ] Implement compare_day4_day5.py
- [ ] Run tests, collect metrics
- [ ] Verify success criteria

### Phase 4: Documentation (Block 4)
- [ ] Evaluation report (docs/day5_self_correction_evaluation_report.md)
- [ ] Daily log (docs/daily-logs/day-5.md)
- [ ] Update README with Day 5 summary

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **LLM regenerates identical SQL** | Wasted retry attempts | 🔧 Retry guard (normalized SQL diff) |
| **Correction prompts too long** | Token bloat, slower inference | Keep prompts <100 tokens |
| **Weak generator hidden** | Can't identify root cause | 🔧 Separate first-attempt metrics |
| **Infinite retry loops** | System hangs | Max 3 attempts, timeout enforcement |
| **Non-retryable errors retried** | Wasted attempts | Explicit non-retryable list |
| **Critic feedback missing** | Retry lacks correction signal | 🔧 Store validation issues in state |
| **Aggregation oscillation** | Retry wastes attempts | 🔧 "Keep aggregations" hint |

---

## 14. Future Enhancements (Post-Day 5)

**Not in scope for Day 5:**
- JoinCorrectionStrategy (deferred to Day 8+)
- TimeoutCorrectionStrategy (use generic for now)
- Adaptive max attempts (based on error type)
- Correction prompt optimization (A/B testing)
- Multi-error correction (fix 2+ errors in one retry)

---

## 15. References

- [Day 1: SchemaLinker Design](../day-1-overview.md)
- [Day 2: SQLGenerator Baseline Report](../day2_sql_generator_baseline_report.md)
- [Day 3: Critic Design](../day3_critic_design.md)
- [Day 4: Executor Design](../day4_executor_design.md)
- [Day 4: Executor Evaluation Report](../day4_executor_evaluation_report.md)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph Best Practices](https://www.swarnendu.de/blog/langgraph-best-practices/)

---

**End of Design Document**

**🔧 Design Improvements Implemented:**
1. ✅ Critic feedback structured and used in correction prompts
2. ✅ Attempt counting fixed (increment after retry decision)
3. ✅ Aggregation correction stabilized with "keep aggregations" hint
4. ✅ SQL diff shows actual snippets (not just word positions)
5. ✅ Schema linking verified to run once (already correct)