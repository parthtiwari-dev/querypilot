"""
Day 5: Self-Correction Loop - LangGraph State Machine

This module implements a self-correction loop that automatically fixes failed SQL queries
using error feedback from the Executor. The system retries up to 3 times, learning from
both Critic validation issues and execution errors.

Key Features:
- 5-node LangGraph workflow (schema_link → generate → critic → execute → increment)
- Retry guard (stops if SQL unchanged)
- Separated metrics (first attempt vs corrected success)
- Minimal correction prompts (<100 tokens)
- Schema caching (runs once per question)
- 4 correction strategies (column, aggregation, timeout, generic)

Design Document: docs/day5_self_correction_design.md
"""

from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from dataclasses import dataclass
import logging
import re

from app.agents.schema_linker import SchemaLinker
from app.agents.sql_generator import SQLGenerator
from app.agents.critic import CriticAgent
from app.agents.executor import ExecutorAgent
from app.agents.correction_strategies import (
    CorrectionStrategyRouter,
    build_critic_correction_prompt,
    NON_RETRYABLE_ERRORS
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize correction strategy router
correction_router = CorrectionStrategyRouter()


# ============================================================================
# STATE DEFINITION
# ============================================================================

class SQLCorrectionState(TypedDict):
    """Minimal state for self-correction retry loop

    Design Decision: Keep state minimal. No heavy fields like full correction
    history (log to file instead).

    🔧 Improvement 1: validation_result includes 'issues' field for Critic feedback
    """
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
    fallback_used: bool 


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_sql(sql: str) -> str:
    """Normalize SQL for comparison (retry guard)

    Removes:
    - Extra whitespace
    - Case differences (lowercase all)
    - Comments

    This avoids false positives from formatting changes while catching
    actual duplicate queries.

    Args:
        sql: SQL query string

    Returns:
        Normalized SQL string
    """
    # Remove SQL comments
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)

    # Normalize whitespace and lowercase
    return " ".join(sql.strip().lower().split())


def get_sql_diff(sql1: str, sql2: str) -> str:
    """Highlight changes between SQL queries with actual snippets

    🔧 Improvement 4: Returns meaningful diffs like:
    'id' → 'product_id'

    Instead of:
    Changed at word 2

    Args:
        sql1: Previous SQL query
        sql2: Current SQL query

    Returns:
        Human-readable diff summary
    """
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


def build_correction_prompt(state: SQLCorrectionState) -> str:
    """Build correction prompt from Critic or Executor feedback

    🔧 Improvement 1: Handles two cases:
    1. Critic blocked SQL (validation_result has issues)
    2. Executor failed SQL (execution_result has error)

    This ensures retry always has correction signal.

    Args:
        state: Current state with validation/execution results

    Returns:
        Minimal correction prompt (<100 tokens)
    """
    failed_sql = state["generated_sql"]
    question = state["question"]

    # Case 1: Critic blocked (execution never ran)
    if not state["validation_result"].get("is_valid", True):
        issues = state["validation_result"].get("issues", [])
        logger.info("[CorrectionPrompt] Using Critic feedback")
        prompt = build_critic_correction_prompt(
            failed_sql=failed_sql,
            critic_issues=issues,
            question=question
        )
        return f"""IMPORTANT: Previous SQL was incorrect. You MUST fix the error.

        {prompt}
        """

    # Case 2: Execution failed - use strategy router
    exec_result = state["execution_result"]
    error_type = exec_result.get("error_type", "unknown")
    error_feedback = exec_result.get("error_feedback", exec_result.get("error_message", "Unknown error"))

    logger.info(f"[CorrectionPrompt] Using {error_type} strategy")

    prompt = correction_router.generate_prompt(
        error_type=error_type,
        error_feedback=error_feedback,
        failed_sql=failed_sql,
        question=question
    )
    return f"""IMPORTANT: Previous SQL was incorrect.
    You MUST fix the listed issues.
    Do NOT repeat the same SQL.

    {prompt}
    """


# ============================================================================
# GRAPH NODES
# ============================================================================

# Global references to agents (set during graph creation)
_schema_linker: Optional[SchemaLinker] = None
_sql_generator: Optional[SQLGenerator] = None
_critic: Optional[CriticAgent] = None
_executor: Optional[ExecutorAgent] = None


def schema_link_node(state: SQLCorrectionState) -> SQLCorrectionState:
    """Node 1: Retrieve relevant schema using SchemaLinker (Day 1)

    🔧 Improvement 5: This node runs ONCE per question.
    Result is cached in state['filtered_schema'] for all retry attempts.

    Why: Schema linking is expensive (embedding similarity search).
    No need to repeat for same question.

    Args:
        state: Current state

    Returns:
        Updated state with filtered_schema
    """
    logger.info("=" * 80)
    logger.info(f"[Schema Link] Question: {state['question']}")
    logger.info("[Schema Link] Retrieving schema (ONCE per question)...")

    # Ensure global linker is set
    assert _schema_linker is not None, "SchemaLinker not initialized"
    filtered_schema = _schema_linker.link_schema(state["question"])
    state["filtered_schema"] = filtered_schema

    logger.info(f"[Schema Link] ✓ Cached {len(filtered_schema)} tables for all attempts")
    logger.info("=" * 80)

    return state


def generate_sql_node(state: SQLCorrectionState) -> SQLCorrectionState:
    """Node 2: Generate or regenerate SQL with correction prompt if retry"""
    
    attempt = state["attempt_number"]
    max_attempts = state["max_attempts"]
    
    logger.info("-" * 80)
    logger.info(f"[Generate] Attempt {attempt}/{max_attempts}")
    logger.info("-" * 80)
    
    assert _sql_generator is not None, "SQLGenerator not initialized"
    
    # ---------- ATTEMPT 1 ----------
    if attempt == 1:
        logger.info("[Generate] First attempt - generating SQL...")
        sql = _sql_generator.generate(
            question=state["question"],
            filtered_schema=state["filtered_schema"]
        )
    
    # ---------- ATTEMPT 2 ----------
    elif attempt == 2:
        logger.info("[Generate] Attempt 2 - auto column repair")
        previous_sql = state["previous_sqls"][-1]
        sql = auto_fix_columns(
            previous_sql,
            state["filtered_schema"]
        )
        logger.info("[Generate] Column repair applied")
    
    # ---------- ATTEMPT 3 ----------
    else:
        logger.info("[Generate] Attempt 3 - LLM correction with full context")
        correction_prompt = build_correction_prompt(state)
        sql = _sql_generator.generate_with_correction(
            question=state["question"],
            filtered_schema=state["filtered_schema"],
            correction_prompt=correction_prompt
        )
    
    # ---------- Logging ----------
    logger.info(f"[Generate] SQL:")
    logger.info(f"  {sql[:100]}{'...' if len(sql) > 100 else ''}")
    
    # Diff logging
    if state["previous_sqls"]:
        previous_sql = state["previous_sqls"][-1]
        diff_summary = get_sql_diff(previous_sql, sql)
        logger.info(f"[Diff] {diff_summary}")
    
    state["generated_sql"] = sql
    state["previous_sqls"].append(sql)
    # DO NOT set fallback_used here - it's only for tracking real fallbacks

    return state 


def critic_node(state: SQLCorrectionState) -> SQLCorrectionState:
    """Node 3: Validate SQL before execution (Day 3)

    🔧 Improvement 1: Store issues for correction prompts

    Args:
        state: Current state

    Returns:
        Updated state with validation_result
    """
    logger.info("-" * 80)
    logger.info("[Critic] Validating SQL...")

    # Ensure critic is set
    assert _critic is not None, "CriticAgent not initialized"

    result = _critic.validate(
        generated_sql=state["generated_sql"],
        filtered_schema=state["filtered_schema"],
        question=state["question"]
    )
    
    # Auto column repair only if column error detected
    if not result.is_valid:
        for issue in result.issues:
            if "does not exist" in issue.lower():
                fixed_sql = auto_fix_columns(
                    state["generated_sql"],
                    state["filtered_schema"]
                )

                if normalize_sql(fixed_sql) != normalize_sql(state["generated_sql"]):
                    logger.info("[AutoFix] Column repair applied")
                    state["generated_sql"] = fixed_sql
                    result = _critic.validate(
                        generated_sql=state["generated_sql"],
                        filtered_schema=state["filtered_schema"],
                        question=state["question"]
                    )
                break

    state["validation_result"] = {
        "is_valid": result.is_valid,
        "confidence": result.confidence,
        "issues": result.issues  # ← Store for correction prompts
    }

    logger.info(f"[Critic] Valid: {result.is_valid} (confidence: {result.confidence:.2f})")

    if not result.is_valid:
        logger.warning(f"[Critic] Issues found:")
        for issue in result.issues:
            logger.warning(f"  - {issue}")

    return state


def execute_node(state: SQLCorrectionState) -> SQLCorrectionState:
    """Node 4: Execute SQL with error classification (Day 4)

    Args:
        state: Current state

    Returns:
        Updated state with execution_result
    """
    logger.info("-" * 80)
    logger.info("[Execute] Running SQL...")

    # Ensure executor is set
    assert _executor is not None, "ExecutorAgent not initialized"

    result = _executor.execute(
        sql=state["generated_sql"],
        schema=state["filtered_schema"]
    )

    state["execution_result"] = {
        "success": result.success,
        "data": result.data,
        "error_type": result.error_type,
        "error_message": result.error_message,
        "error_feedback": result.error_feedback,
        "execution_time_ms": result.execution_time_ms,
        "row_count": result.row_count if result.success else 0
    }

    if result.success:
        # Persist final success in state (routing functions may not persist state changes)
        state["final_success"] = True

        logger.info(f"[Execute] ✓ SUCCESS")
        logger.info(f"  Rows: {result.row_count}")
        logger.info(f"  Time: {result.execution_time_ms:.1f}ms")
    else:
        # Ensure final_success explicitly false on failure
        state["final_success"] = False

        logger.error(f"[Execute] ✗ FAILED")
        logger.error(f"  Error Type: {result.error_type}")
        logger.error(f"  Error: {result.error_feedback or result.error_message}")

    return state


def increment_attempt_node(state: SQLCorrectionState) -> SQLCorrectionState:
    """Node 5: Increment attempt counter after deciding to retry

    🔧 Improvement 2: Increment AFTER generation decision, not before.
    This prevents attempt_number from exceeding max_attempts in metrics.

    Args:
        state: Current state

    Returns:
        Updated state with incremented attempt_number
    """
    # Don't increment if we've already succeeded
    if state.get("final_success"):
        logger.info("[Retry] Final success already achieved; not incrementing")
        return state

    state["attempt_number"] += 1
    logger.info("-" * 80)
    logger.info(f"[Retry] Incrementing to attempt {state['attempt_number']}/{state['max_attempts']}")
    logger.info("-" * 80)

    return state


# ============================================================================
# CONDITIONAL ROUTING
# ============================================================================

# Non-retryable errors (use imported constant from correction_strategies)
NON_RETRYABLE = NON_RETRYABLE_ERRORS  # {"permission_denied", "connection_error"}
# Note: timeout is now RETRYABLE (removed from this set)


def should_execute_or_retry(state: SQLCorrectionState) -> str:
    """Route 1: After Critic → Execute or Retry

    If Critic validates SQL → execute
    If Critic blocks SQL → retry with correction

    🔧 Improvement 1: When Critic blocks, correction prompt will use
    validation_result['issues'] since execution_result doesn't exist yet.

    Args:
        state: Current state

    Returns:
        "execute" or "increment_attempt"
    """
    attempt = state["attempt_number"]
    max_attempts = state["max_attempts"]

    # If Critic passed, execute
    if state["validation_result"]["is_valid"]:
        logger.info("[Route] Critic passed → Executing SQL")
        return "execute"

    # If we've already exhausted attempts, stop here
    if attempt >= max_attempts:
        state["final_success"] = False
        logger.warning("[Route] Critic blocked and max attempts reached → Ending")
        return END

    # Otherwise retry (Critic blocked)
    logger.warning("[Route] Critic blocked → Will retry with validation feedback")
    return "increment_attempt"


def should_retry_or_end(state: SQLCorrectionState) -> str:
    """Route 2: After Execute → End or Retry

    If execution succeeded → END
    If max attempts → END
    If non-retryable error → END
    If SQL unchanged → END (retry guard)
    Otherwise → retry

    🔧 Improvement 2: Check attempt_number BEFORE incrementing.
    This ensures we don't exceed max_attempts.

    Args:
        state: Current state

    Returns:
        "increment_attempt" or END
    """
    exec_result = state["execution_result"]
    attempt = state["attempt_number"]
    max_attempts = state["max_attempts"]

    # Success - done
    if exec_result["success"]:
        state["final_success"] = True
        logger.info("=" * 80)
        logger.info(f"[End] ✓ SUCCESS on attempt {attempt}")
        logger.info("=" * 80)
        return END

    # Max attempts - give up
    if attempt >= max_attempts:
        state["final_success"] = False
        logger.warning("=" * 80)
        logger.warning(f"[End] ✗ Max attempts ({max_attempts}) reached")
        logger.warning("=" * 80)
        return END

    # Non-retryable error - give up
    if exec_result["error_type"] in NON_RETRYABLE:
        state["final_success"] = False
        logger.warning("=" * 80)
        logger.warning(f"[End] ✗ Non-retryable error: {exec_result['error_type']}")
        logger.warning("=" * 80)
        return END

    # 🔧 Improvement 2: Retry guard with normalized comparison
    if len(state["previous_sqls"]) >= 2:
        current_sql = normalize_sql(state["previous_sqls"][-1])
        previous_sql = normalize_sql(state["previous_sqls"][-2])
        if current_sql == previous_sql:
            state["final_success"] = False
            logger.warning("=" * 80)
            logger.warning("[End] ✗ SQL unchanged (retry guard triggered)")
            logger.warning(f"SQL:\n{state['generated_sql']}")
            logger.warning("=" * 80)
            return END
    # Retry
    logger.info(f"[Route] Error is retryable ({exec_result['error_type']}) → Will retry")

    return "increment_attempt"


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

def create_self_correction_graph(
    schema_linker: SchemaLinker,
    sql_generator: SQLGenerator,
    critic: CriticAgent,
    executor: ExecutorAgent
) -> object:
    """Build LangGraph workflow

    🔧 Improvement 2: Node order ensures attempt_number is accurate.
    Flow: generate → critic/execute → (if retry) → increment → generate
    This means attempt_number represents completed attempts.

    Graph Structure:
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

    Args:
        schema_linker: SchemaLinker instance (Day 1)
        sql_generator: SQLGenerator instance (Day 2)
        critic: CriticAgent instance (Day 3)
        executor: ExecutorAgent instance (Day 4)

    Returns:
        Compiled LangGraph workflow
    """
    # Set global references (used by node functions)
    global _schema_linker, _sql_generator, _critic, _executor
    _schema_linker = schema_linker
    _sql_generator = sql_generator
    _critic = critic
    _executor = executor

    # Create workflow
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
            "increment_attempt": "increment_attempt",
            END: END
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

    logger.info("[Graph] LangGraph workflow compiled successfully")

    return workflow.compile()


# ============================================================================
# METRICS & RESULTS
# ============================================================================

@dataclass
class CorrectionMetrics:
    """Track first attempt vs corrected separately (don't hide weak generation)

    Key Metrics:
    - first_attempt_rate: How good is SQLGenerator WITHOUT correction?
    - correction_effectiveness: How much does correction help?
    - overall_success_rate: Success rate after correction
    """
    # Counts
    total_queries: int = 0
    first_attempt_success: int = 0  # Succeeded without retry
    corrected_success: int = 0      # Fixed by retry
    final_failures: int = 0         # Failed after all retries
    total_attempts: int = 0

    @property
    def first_attempt_rate(self) -> float:
        """How good is SQLGenerator WITHOUT correction?"""
        if self.total_queries == 0:
            return 0.0
        return self.first_attempt_success / self.total_queries

    @property
    def correction_effectiveness(self) -> float:
        """How much does correction help?"""
        failed_initially = self.total_queries - self.first_attempt_success
        if failed_initially == 0:
            return 1.0
        return self.corrected_success / failed_initially

    @property
    def overall_success_rate(self) -> float:
        """Success rate after correction"""
        if self.total_queries == 0:
            return 0.0
        return (self.first_attempt_success + self.corrected_success) / self.total_queries

    @property
    def avg_attempts(self) -> float:
        """Average attempts per query"""
        if self.total_queries == 0:
            return 0.0
        return self.total_attempts / self.total_queries

    def update(self, result: 'CorrectionResult'):
        """Update metrics with result"""
        self.total_queries += 1
        self.total_attempts += result.attempts

        if result.attempts == 1 and result.success:
            self.first_attempt_success += 1
        elif result.attempts > 1 and result.success:
            self.corrected_success += 1
        else:
            self.final_failures += 1

    def to_dict(self) -> Dict[str, Any]:
        """Export metrics as dictionary"""
        return {
            "total_queries": self.total_queries,
            "first_attempt_success": self.first_attempt_success,
            "corrected_success": self.corrected_success,
            "final_failures": self.final_failures,
            "total_attempts": self.total_attempts,
            "first_attempt_rate": self.first_attempt_rate,
            "correction_effectiveness": self.correction_effectiveness,
            "overall_success_rate": self.overall_success_rate,
            "avg_attempts": self.avg_attempts
        }


@dataclass
class CorrectionResult:
    """Result of self-correction execution

    Attributes:
        question: Original natural language question
        final_sql: Final SQL query (may be corrected)
        success: Whether execution succeeded
        attempts: Number of attempts made
        execution_result: ExecutionResult from final attempt
        validation_issues: List of Critic issues (if any)
    """
    question: str
    final_sql: str
    success: bool
    attempts: int
    execution_result: Dict[str, Any]
    validation_issues: Optional[List[str]] = None
    used_fallback: bool = False
    
    @property
    def was_corrected(self) -> bool:
        """Fixed by retry"""
        return self.success and self.attempts > 1

    def to_dict(self) -> Dict[str, Any]:
        """Export result as dictionary"""
        return {
            "question": self.question,
            "final_sql": self.final_sql,
            "success": self.success,
            "attempts": self.attempts,
            "was_corrected": self.was_corrected,
            "execution_result": self.execution_result,
            "validation_issues": self.validation_issues
        }


# ============================================================================
# CORRECTION AGENT
# ============================================================================

class CorrectionAgent:
    """Self-correction agent with retry loop

    Orchestrates the self-correction workflow using LangGraph. Tracks metrics
    separately for first-attempt success vs corrected success to avoid hiding
    weak generation.

    Attributes:
        schema_linker: SchemaLinker instance (Day 1)
        sql_generator: SQLGenerator instance (Day 2)
        critic: CriticAgent instance (Day 3)
        executor: ExecutorAgent instance (Day 4)
        max_attempts: Maximum retry attempts (default: 3)
        graph: Compiled LangGraph workflow
        metrics: CorrectionMetrics instance
    """

    def __init__(
        self,
        schema_linker: SchemaLinker,
        sql_generator: SQLGenerator,
        critic: CriticAgent,
        executor: ExecutorAgent,
        max_attempts: int = 3
    ):
        """Initialize CorrectionAgent

        Args:
            schema_linker: SchemaLinker instance (Day 1)
            sql_generator: SQLGenerator instance (Day 2)
            critic: CriticAgent instance (Day 3)
            executor: ExecutorAgent instance (Day 4)
            max_attempts: Maximum retry attempts (default: 3)
        """
        self.schema_linker = schema_linker
        self.sql_generator = sql_generator
        self.critic = critic
        self.executor = executor
        self.max_attempts = max_attempts

        # Build LangGraph workflow
        logger.info("[CorrectionAgent] Building LangGraph workflow...")
        # Typing: compiled graph has runtime 'invoke' method; use Any to satisfy type checker
        self.graph: Any = create_self_correction_graph(
            schema_linker=schema_linker,
            sql_generator=sql_generator,
            critic=critic,
            executor=executor
        )

        # Initialize metrics
        self.metrics = CorrectionMetrics()

        logger.info(f"[CorrectionAgent] Initialized with max_attempts={max_attempts}")

    def execute_with_retry(self, question: str) -> CorrectionResult:
        """Execute query with self-correction

        Main entry point for the self-correction loop. Runs the LangGraph workflow
        which handles retry logic automatically.

        Args:
            question: Natural language question

        Returns:
            CorrectionResult with execution outcome and metrics
        """
        logger.info("\n" + "=" * 80)
        logger.info(f"[CorrectionAgent] NEW QUERY")
        logger.info(f"[CorrectionAgent] Question: {question}")
        logger.info("=" * 80)

        # Initialize state
        initial_state: SQLCorrectionState = {
            "question": question,
            "filtered_schema": {},
            "generated_sql": "",
            "validation_result": {},
            "execution_result": {},
            "attempt_number": 1,
            "max_attempts": self.max_attempts,
            "previous_sqls": [],
            "final_success": False,
            "fallback_used": False
        }

        # Run LangGraph workflow
        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as e:
            logger.error(f"[CorrectionAgent] Graph execution failed: {e}")
            raise

        # Build result
        result = CorrectionResult(
            question=question,
            final_sql=final_state["generated_sql"],
            success=final_state["final_success"],
            attempts=final_state["attempt_number"],
            execution_result=final_state["execution_result"],
            validation_issues=final_state["validation_result"].get("issues", []),
            used_fallback=final_state.get("fallback_used", False)
        )

        # Update metrics
        self.metrics.update(result)

        # Log final summary
        logger.info("\n" + "=" * 80)
        logger.info("[CorrectionAgent] FINAL RESULT")
        logger.info("=" * 80)
        if result.success:
            if result.attempts == 1:
                logger.info("[CorrectionAgent] ✓ SUCCESS on first attempt")
            else:
                logger.info(f"[CorrectionAgent] ✓ SUCCESS after {result.attempts} attempts (CORRECTED!)")
        else:
            logger.error(f"[CorrectionAgent] ✗ FAILED after {result.attempts} attempts")

        logger.info(f"[CorrectionAgent] Final SQL: {result.final_sql[:80]}...")
        logger.info("=" * 80 + "\n")

        return result

    def get_metrics(self) -> CorrectionMetrics:
        """Get current metrics

        Returns:
            CorrectionMetrics instance with aggregated stats
        """
        return self.metrics

    def reset_metrics(self):
        """Reset metrics (useful for testing)"""
        self.metrics = CorrectionMetrics()
        logger.info("[CorrectionAgent] Metrics reset")

from difflib import get_close_matches
import re

def auto_fix_columns(sql: str, schema: dict) -> str:
    """
    Replace invalid columns with closest match.
    Handles BOTH qualified (table.column) and bare (column) references.
    """
    from difflib import get_close_matches
    import re
    
    # Build table → columns map
    column_map = {}
    for table, info in schema.items():
        cols = info.get("columns", {})
        column_map[table.lower()] = [c.lower() for c in cols.keys()]
    
    # ✅ FIX #8A: Handle qualified references (table.column)
    pattern_qualified = r'(\w+)\.(\w+)'
    matches = re.findall(pattern_qualified, sql)
    
    for table, column in matches:
        table_lower = table.lower()
        column_lower = column.lower()
        
        if table_lower not in column_map:
            continue
        
        candidates = column_map[table_lower]
        
        # Column already valid
        if column_lower in candidates:
            continue
        
        # Find closest column name
        match = get_close_matches(column_lower, candidates, n=1, cutoff=0.6)
        if match:
            correct = match[0]
            sql = re.sub(
                rf'\b{table}\.{column}\b',
                f"{table}.{correct}",
                sql,
                flags=re.IGNORECASE
            )
    
    # ✅ FIX #8B: Handle bare column references (no table prefix)
    # Extract error message from logs to find which table is missing the column
    # For now, try all tables and use first match
    pattern_bare = r'\b(\w+)\b'
    
    # Get all possible columns across all tables
    all_columns = {}
    for table, cols in column_map.items():
        for col in cols:
            if col not in all_columns:
                all_columns[col] = table
    
    # Find potential bare columns (keywords excluded)
    sql_keywords = {'select', 'from', 'where', 'and', 'or', 'order', 'by', 'limit', 
                    'group', 'having', 'join', 'on', 'as', 'with', 'case', 'when', 
                    'then', 'else', 'end', 'distinct', 'count', 'sum', 'avg', 'max', 'min'}
    
    words = re.findall(r'\b(\w+)\b', sql.lower())
    for word in words:
        if word in sql_keywords or word in column_map:
            continue
        
        # Check if this word looks like a column name that doesn't exist
        found = False
        for table, cols in column_map.items():
            if word in cols:
                found = True
                break
        
        if not found:
            # Try to find similar column
            all_col_names = [col for cols in column_map.values() for col in cols]
            matches = get_close_matches(word, all_col_names, n=1, cutoff=0.7)
            if matches:
                # Replace bare column with corrected version
                sql = re.sub(
                    rf'\b{word}\b',
                    matches[0],
                    sql,
                    flags=re.IGNORECASE,
                    count=1  # Only replace first occurrence
                )
    
    return sql
