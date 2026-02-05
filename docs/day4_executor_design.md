# Day 4: Executor Agent Design Document

**Author:** QueryPilot Team  
**Date:** February 5, 2026  
**Status:** Design Phase  
**Estimated Implementation:** 6-7 hours

---

## 🎯 Overview

### What We're Building
A safe, reliable SQL execution layer with intelligent error classification for the QueryPilot Text-to-SQL system.

### Why We Need This
- **Day 3 Gap:** Critic validates SQL but doesn't execute it
- **Safety Requirements:** Need timeouts, row limits, connection pooling
- **Day 5 Foundation:** Self-correction requires error classification (can't fix what we can't identify)
- **Production Readiness:** Proper error handling + metrics tracking

### Success Criteria
1. **Error classification accuracy:** >85%
2. **Execution success rate:** 100% on Critic-validated queries
3. **Execution latency:** <5s for valid queries

---

## 🏗️ System Architecture

### Pipeline Flow (Days 1-4)

```
Question
  ↓
[Day 1] Schema Linker → filtered_schema
  ↓
[Day 2] SQL Generator → generated_sql
  ↓
[Day 3] Critic Agent → ValidationResult(is_valid, confidence, issues)
  ↓
[Day 4] Executor Agent → ExecutionResult(success, data, error_type)
```

### Components

#### 1. ExecutorAgent
**Responsibility:** Execute SQL safely on PostgreSQL with error recovery

**Interface:**
```python
class ExecutorAgent:
    def __init__(self, database_url: str)
    def execute(
        sql: str,
        timeout_seconds: int = 30,
        row_limit: int = 1000,
        schema: Dict[str, Dict] = None
    ) -> ExecutionResult
    def get_metrics() -> ExecutionMetrics
#### 2. ErrorClassifier

**Responsibility:** Categorize execution errors + generate actionable feedback

**Interface:**

```python
class ErrorClassifier:
    def classify(error: Exception) -> ErrorCategory
    def extract_details(error: Exception, category: ErrorCategory) -> dict
    def generate_feedback(
        category: ErrorCategory,
        details: dict,
        schema: dict = None
    ) -> str
```
#### 3. ErrorCategory (Enum)

10 Categories:

- `COLUMN_NOT_FOUND` - Schema error, fixable
- `TABLE_NOT_FOUND` - Schema error, fixable
- `SYNTAX_ERROR` - SQL error, fixable
- `TYPE_MISMATCH` - SQL error, fixable
- `JOIN_ERROR` - SQL error, fixable
- `AGGREGATION_ERROR` - SQL error, fixable
- `TIMEOUT` - System error, optimize query
- `PERMISSION_DENIED` - System error, not fixable
- `CONNECTION_ERROR` - System error, retry
- `UNKNOWN` - Catch-all

## 📊 Data Structures

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    """Result of SQL execution"""
    success: bool                         # True if query executed
    data: Optional[List[Tuple]]           # Query results (if success)
    error_type: Optional[str]             # Error category (if failure)
    error_message: Optional[str]          # Raw error text (if failure)
    error_feedback: Optional[str]         # Helpful feedback (if failure)
    error_details: Optional[Dict]         # Extracted details (if failure)
    execution_time_ms: float              # Query latency
    row_count: int                        # Rows returned
    sql_executed: str                     # Actual SQL run (with LIMIT)
```

**Design Decision:** Simple flat structure (not Union types)

**Rationale:** Matches Day 3's ValidationResult pattern, easier serialization

**Trade-off:** Some fields None when not applicable (acceptable for simplicity)

### ExecutionMetrics

```python
@dataclass
class ExecutionMetrics:
    """Execution statistics for monitoring"""
    total_queries: int
    successful_queries: int
    failed_queries: int
    total_execution_time_ms: float
    avg_execution_time_ms: float
    max_execution_time_ms: float
    min_execution_time_ms: float
    error_counts: Dict[str, int]          # NEW: Error distribution
    
    def record_error(self, error_type: str)
```

**Design Decision:** Add error distribution tracking

**Rationale:** Day 5 self-correction needs to know which errors are common

**Example Use:** "60% of failures = column_not_found" → prioritize column validation

## 🔧 Critical Issues & Fixes

### Issue #1: LIMIT Injection Safety ⚠️

**Problem:** Simple substring check breaks on nested queries/CTEs

**Bad Approach:**

```python
if "LIMIT" not in sql_upper:
    return f"{sql.rstrip(';')} LIMIT {limit}"
# Fails: SELECT * FROM (SELECT * FROM products LIMIT 50) sub
# Outer query has no LIMIT, but check sees inner LIMIT
```

**Day 4 Fix:**

```python
def _add_row_limit(self, sql: str, limit: int) -> str:
    """Add LIMIT if not present (simple strategy)"""
    sql = sql.rstrip(";").strip()
    
    if "LIMIT" not in sql.upper():
        sql += f" LIMIT {limit}"
    
    return sql
```

**Known Limitations (Documented, Not Fixed):**

- ❌ Nested subqueries: Outer LIMIT may not be added
- ❌ CTEs: LIMIT placement may be incorrect
- ❌ ORDER BY interactions: May break ordering semantics

**Rationale for Simple Approach:**

- Works for 95% of Day 2's baseline queries
- Perfect SQL parsing = 4+ hours (scope creep risk)
- Acceptable trade-off: Ship fast, note limitations

**Future Work (Day 8+):** Use sqlparse AST to inject LIMIT correctly

### Issue #4: Error Classification Ordering ⚠️

**Problem:** Overlapping patterns cause wrong classification

**Example:**

```
Error: "column must appear in GROUP BY clause"
Matches: "column" → COLUMN_NOT_FOUND ❌
Matches: "GROUP BY" → AGGREGATION_ERROR ✅
Matches: "error" → SYNTAX_ERROR ❌
```

**Bad Approach:**

```python
# Dict iteration = undefined order
for category, patterns in PATTERNS.items():
    if pattern in error_msg:
        return category  # May return wrong category!
```

**Day 4 Fix:**

```python
def classify(self, error: Exception) -> ErrorCategory:
    """Check in PRIORITY ORDER (most specific first)"""
    error_msg = str(error).lower()
    
    # Priority 1: System errors (highest)
    if self._check_timeout(error_msg):
        return ErrorCategory.TIMEOUT
    if self._check_connection(error_msg):
        return ErrorCategory.CONNECTION_ERROR
    if self._check_permission(error_msg):
        return ErrorCategory.PERMISSION_DENIED
    
    # Priority 2: Schema errors (specific)
    if self._check_column_not_found(error_msg):
        return ErrorCategory.COLUMN_NOT_FOUND
    if self._check_table_not_found(error_msg):
        return ErrorCategory.TABLE_NOT_FOUND
    
    # Priority 3: SQL errors (moderate)
    if self._check_aggregation_error(error_msg):
        return ErrorCategory.AGGREGATION_ERROR
    if self._check_join_error(error_msg):
        return ErrorCategory.JOIN_ERROR
    if self._check_type_mismatch(error_msg):
        return ErrorCategory.TYPE_MISMATCH
    
    # Priority 4: Generic (low priority)
    if self._check_syntax_error(error_msg):
        return ErrorCategory.SYNTAX_ERROR
    
    # Priority 5: Fallback
    return ErrorCategory.UNKNOWN
```

**Why Separate Methods:**

- Clear priority hierarchy
- Each check is testable independently
- No ambiguity in classification
## 🔌 Integration Points

### With Day 3 Critic Agent

**Input:** Receives ValidationResult from Critic

```python
validation_result = critic.validate(generated_sql, filtered_schema, question)

if validation_result.is_valid:
    # Execute with Executor
    execution_result = executor.execute(
        generated_sql,
        schema=filtered_schema  # Pass for error feedback
    )
else:
    # Don't execute, return Critic errors
    print(validation_result.issues)
```

**Contract:**

- Executor ONLY runs queries with is_valid=True
- Invalid queries never reach Executor
- Critic errors take precedence over execution errors

### With Day 2 SQL Generator

**Schema Propagation:**

```python
# Schema flows through entire pipeline
filtered_schema = schema_linker.link_schema(question)
generated_sql = sql_generator.generate(question, filtered_schema)
validation_result = critic.validate(generated_sql, filtered_schema, question)
execution_result = executor.execute(generated_sql, schema=filtered_schema)
```

**Why Schema Matters:**

- Error feedback needs available columns: "Did you mean product_id?"
- Feedback generator uses schema to suggest alternatives
- Schema-aware feedback improves Day 5 self-correction

## ⚙️ Configuration

### Database Connection

```python
from app.config import settings

executor = ExecutorAgent(database_url=settings.DATABASE_URL)
# Uses: postgresql://admin:devpassword@localhost:5432/ecommerce
```

### Connection Pool Settings (SQLAlchemy Defaults)

```python
engine = create_engine(
    database_url,
    poolclass=QueuePool,
    pool_size=5,              # Max 5 persistent connections
    max_overflow=10,          # Allow 10 extra if busy
    pool_pre_ping=True,       # Test connection before use
    pool_recycle=3600         # Recycle after 1 hour
)
```

**Design Decision:** Use defaults for Day 4

**Rationale:** Good for 100-1000 QPS, no premature optimization

**Future Tuning (Day 8+):** Adjust based on production load

### Timeout & Row Limits

```python
# From .env (already exists)
QUERY_TIMEOUT=30  # seconds

# In code (configurable parameters)
executor.execute(
    sql,
    timeout_seconds=30,   # Default, overridable
    row_limit=1000        # Default, overridable for testing
)
```

**Design Decision:** Parameters with defaults (not env vars)

**Rationale:** Flexible for testing, safe defaults for production

**Example Override:** `executor.execute(sql, row_limit=10)` for tests

## 🧪 Testing Strategy

### Test Dataset: error_tests.json

7+ Broken Queries (One Per Error Type):

```json
[
  {
    "id": "err_001",
    "error_type": "column_not_found",
    "sql": "SELECT id FROM products",
    "expected_category": "column_not_found"
  },
  {
    "id": "err_002",
    "error_type": "table_not_found",
    "sql": "SELECT * FROM invoices",
    "expected_category": "table_not_found"
  },
  {
    "id": "err_003",
    "error_type": "syntax_error",
    "sql": "SELCT * FRM products",
    "expected_category": "syntax_error"
  },
  {
    "id": "err_004",
    "error_type": "type_mismatch",
    "sql": "SELECT * FROM products WHERE price = 'expensive'",
    "expected_category": "type_mismatch"
  },
  {
    "id": "err_005",
    "error_type": "aggregation_error",
    "sql": "SELECT category_id, COUNT(*) FROM products",
    "expected_category": "aggregation_error"
  },
  {
    "id": "err_006",
    "error_type": "join_error",
    "sql": "SELECT product_id FROM products, order_items WHERE product_id = 1",
    "expected_category": "join_error"
  },
  {
    "id": "err_007",
    "error_type": "timeout",
    "sql": "SELECT pg_sleep(40)",
    "expected_category": "timeout"
  }
]
```

### Test Script: test_error_classifier.py

**Validation Logic:**

- Load error test dataset
- Execute each broken query
- Check if error category matches expected
- Calculate accuracy: correct / total
- Pass threshold: >85%

### Integration Test: run_day4_eval.py

**Full Pipeline Test:**

- Run Day 2's 20 baseline questions
- Schema → Generate → Critic → Executor (full chain)
- Verify Critic-validated queries execute successfully
- Verify metrics tracking works
- Pass criteria: 100% success on valid queries
🚫 Out of Scope (Day 4)
NOT Building Today:

❌ Self-correction loop (Day 5)

❌ Retry logic (Day 5)

❌ SQL regeneration (Day 5)

❌ Result formatting (Day 6)

❌ Natural language summaries (Day 6)

❌ Conversation history (Day 6)

❌ Query caching (Day 8)

❌ Async execution (Day 8)

❌ Result streaming (Day 8)

Day 4 Focus:

✅ Safe execution (timeouts, row limits, pooling)

✅ Error classification (7 categories)

✅ Actionable feedback (schema-aware)

✅ Metrics tracking (error distribution)

## 📝 Known Limitations

### LIMIT Injection

**Limitation:** Nested subqueries may not get outer LIMIT

**Example:** `SELECT * FROM (SELECT * FROM products LIMIT 50) sub` → No outer LIMIT added

**Impact:** Low (Day 2 baseline has no nested queries)

**Mitigation:** Document in evaluation report

**Future Fix:** SQL AST parsing (Day 8)

### Error Classification

**Limitation:** Some rare errors → UNKNOWN category

**Target:** 85%+ accuracy (not 100%)

**Example:** Custom PostgreSQL extensions may have unique error messages

**Mitigation:** Log UNKNOWN errors, add patterns iteratively

### Feedback Quality

**Limitation:** Similar name suggestions may be incorrect

**Example:** "id" suggests "product_id" but user meant "order_id"

**Impact:** Low (Day 5 LLM can handle ambiguous suggestions)

**Mitigation:** Provide multiple suggestions (top 3)

## 🗂️ File Structure

### New Files Created:

```
backend/app/agents/executor.py              # ExecutorAgent + ErrorClassifier
backend/app/evaluation/datasets/error_tests.json  # Error test cases
backend/scripts/test_error_classifier.py    # Accuracy test
backend/scripts/run_day4_eval.py            # Integration test
docs/day4_executor_design.md                # This document
docs/day4_executor_evaluation_report.md     # Results (post-testing)
docs/daily-logs/day-4.md                    # Comprehensive daily log
```

### Modified Files:

```
None (Executor is net-new, doesn't modify existing agents)
```
## ✅ Implementation Checklist

### Block 1: Executor Core (2.5 hours)

- ☐ Design doc completed
- ☐ ExecutorAgent.__init__() with connection pool
- ☐ ExecutorAgent.execute() with 5 critical fixes
- ☐ ExecutionMetrics with error_counts tracking
- ☐ Basic execution tests (valid query, timeout, row limit)

### Block 2: Error Classification (2.5 hours)

- ☐ ErrorCategory enum (10 categories)
- ☐ ErrorClassifier.classify() with priority ordering
- ☐ ErrorClassifier.extract_details() for column/table names
- ☐ ErrorClassifier.generate_feedback() with schema awareness
- ☐ Integrated into ExecutorAgent.execute()

### Block 3: Testing & Integration (2 hours)

- ☐ error_tests.json created (7+ broken queries)
- ☐ test_error_classifier.py written + run
- ☐ Classification accuracy >85% verified
- ☐ run_day4_eval.py updated with Executor
- ☐ Day 2's 20 questions run end-to-end
- ☐ Metrics tracked and logged

### Documentation

- ☐ Design doc completed (this file)
- ☐ Evaluation report written (day4_executor_evaluation_report.md)
- ☐ Daily log written (docs/daily-logs/day-4.md)
- ☐ Known limitations documented
- ☐ Git commit with clear message

## 🎯 Next Steps (Day 5 Preview)

### What Day 5 Will Use From Day 4:

- ExecutionResult.error_type → Determine correction strategy
- ExecutionResult.error_feedback → Pass to LLM for regeneration
- ExecutionMetrics.error_counts → Prioritize correction effort
- ErrorCategory → Map to correction agents

### Day 5 Self-Correction Loop:

```python
# Pseudocode
attempt = 1
max_attempts = 3

while attempt <= max_attempts:
    execution_result = executor.execute(sql, schema=schema)
    
    if execution_result.success:
        return execution_result.data  # Success!
    
    # Use Day 4's error classification
    correction_prompt = f"""
    SQL failed with {execution_result.error_type}.
    Feedback: {execution_result.error_feedback}
    Fix the SQL and try again.
    """
    
    sql = llm.regenerate(correction_prompt)
    attempt += 1

return "Failed after 3 attempts"
```
## 📚 References

- **Day 1:** Schema Intelligence Layer (schema_linker.py)
- **Day 2:** SQL Generator (sql_generator.py, 95% baseline)
- **Day 3:** Critic Agent (critic.py, 90% error detection)
- **PostgreSQL Docs:** Statement Timeout
- **SQLAlchemy Docs:** Connection Pooling

