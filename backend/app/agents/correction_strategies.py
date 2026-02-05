"""
Day 5: Correction Strategies - Minimal Prompts for Self-Correction

This module implements 4 focused correction strategies that generate minimal
prompts (<100 tokens) for SQL regeneration during the retry loop.

Strategies:
1. ColumnNotFoundStrategy (70% of failures) - Fix column names
2. AggregationErrorStrategy (20% of failures) - Fix GROUP BY clauses
3. TimeoutStrategy (5% of failures) - Simplify slow queries
4. GenericStrategy (5% of failures) - Fallback for all other errors

Design Philosophy: Keep prompts minimal. PostgreSQL error messages already
contain enough context for the LLM to fix issues.

Design Document: docs/day5_self_correction_design.md
"""

import re
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


# ============================================================================
# STRATEGY PROTOCOL
# ============================================================================

class CorrectionStrategy(Protocol):
    """Protocol for correction strategies

    All strategies must implement generate_prompt() which returns
    a minimal correction prompt (<100 tokens).
    """

    def generate_prompt(
        self,
        error_feedback: str,
        failed_sql: str,
        question: str
    ) -> str:
        """Generate minimal correction prompt

        Args:
            error_feedback: Error message from Executor
            failed_sql: SQL query that failed
            question: Original natural language question

        Returns:
            Minimal correction prompt (<100 tokens)
        """
        ...


# ============================================================================
# STRATEGY IMPLEMENTATIONS
# ============================================================================

class ColumnNotFoundStrategy:
    """Fix column name errors (70% of failures)

    Example errors:
    - column "id" does not exist
    - column "name" does not exist. Did you mean "product_name"?

    Strategy: Extract wrong column from error, let LLM fix with schema context.
    """

    def generate_prompt(
        self,
        error_feedback: str,
        failed_sql: str,
        question: str
    ) -> str:
        """Generate minimal column correction prompt

        Extracts the problematic column name from error message.

        Args:
            error_feedback: Error like 'column "id" does not exist'
            failed_sql: Failed SQL query
            question: Original question

        Returns:
            Minimal prompt focusing on column fix
        """
        # Extract column from error message
        # Pattern: column "id" does not exist
        # Pattern: column 'name' does not exist
        match = re.search(r"column ['\"](\w+)['\"]", error_feedback, re.IGNORECASE)  # CORRECT - single backslash in raw string

        missing_col = match.group(1) if match else "unknown"

        logger.info(f"[ColumnStrategy] Extracted missing column: '{missing_col}'")

        # Minimal prompt (< 50 tokens)
        prompt = f"""Failed SQL:
        {failed_sql}

        Error: Column '{missing_col}' does not exist.

        DO NOT use column '{missing_col}' again.
        Replace it using correct schema columns.

        Return corrected SQL only for: {question}
        """.strip()

        return prompt


class AggregationErrorStrategy:
    """Fix GROUP BY errors (20% of failures)

    Example errors:
    - column "products.name" must appear in GROUP BY clause or be used in an aggregate function
    - column "orders.customer_id" must appear in the GROUP BY clause

    Strategy: Tell LLM to fix GROUP BY, with constraint to keep aggregations.

    🔧 Improvement 3: Added "keep aggregations" hint to prevent oscillation.
    """

    def generate_prompt(
        self,
        error_feedback: str,
        failed_sql: str,
        question: str
    ) -> str:
        """Generate minimal aggregation correction prompt

        🔧 Improvement 3: Includes stability hint to prevent oscillation
        (add GROUP BY → drop COUNT → remove GROUP BY → repeat)

        Args:
            error_feedback: Error about missing GROUP BY
            failed_sql: Failed SQL query
            question: Original question

        Returns:
            Minimal prompt with GROUP BY fix instruction
        """
        logger.info("[AggregationStrategy] Fixing GROUP BY clause")

        # Minimal prompt with stabilization hint (< 80 tokens)
        prompt = f"""Failed SQL:
        {failed_sql}

        Error: Missing GROUP BY clause.

        Do NOT change joins or aggregations.
        Only add required columns to GROUP BY.

        Return corrected SQL for: {question}
        """.strip()

        return prompt


class TimeoutStrategy:
    """Simplify slow queries (5% of failures)

    Example error:
    - canceling statement due to statement timeout

    Strategy: Add LIMIT, remove unnecessary JOINs, simplify aggregations.

    🔧 Improvement: Timeout is now retryable (was non-retryable in initial design).
    """

    def generate_prompt(
        self,
        error_feedback: str,
        failed_sql: str,
        question: str
    ) -> str:
        """Generate timeout simplification prompt

        Suggests optimizations:
        - Add LIMIT if missing
        - Remove unnecessary JOINs
        - Simplify aggregations

        Args:
            error_feedback: Timeout error message
            failed_sql: Failed SQL query (too slow)
            question: Original question

        Returns:
            Prompt with simplification instructions
        """
        logger.info("[TimeoutStrategy] Simplifying query to avoid timeout")

        # Check if LIMIT already exists
        has_limit = "LIMIT" in failed_sql.upper()

        # Build simplification instructions
        simplify_hints = []
        if not has_limit:
            simplify_hints.append("Add LIMIT 100 if missing")
        simplify_hints.append("Remove unnecessary JOINs")
        simplify_hints.append("Simplify complex aggregations")

        hints_text = "\n".join(f"- {hint}" for hint in simplify_hints)

        # Minimal prompt (< 100 tokens)
        prompt = f"""Failed SQL (timed out after 30 seconds):
{failed_sql}

Error: Query timeout.

Simplify the query:
{hints_text}

Regenerate simpler SQL for: {question}
""".strip()

        return prompt


class GenericStrategy:
    """Fallback for all other errors (5% of failures)

    Handles:
    - syntax_error
    - type_mismatch
    - join_error
    - table_not_found
    - unknown

    Strategy: Minimal prompt with error feedback. PostgreSQL errors are
    usually self-explanatory, so LLM can fix without extra context.
    """

    def generate_prompt(
        self,
        error_feedback: str,
        failed_sql: str,
        question: str
    ) -> str:
        """Generate generic correction prompt

        Simply passes through the error feedback, which is already helpful
        from Day 4's ErrorClassifier.

        Args:
            error_feedback: Error message from Executor
            failed_sql: Failed SQL query
            question: Original question

        Returns:
            Minimal prompt with error feedback
        """
        logger.info("[GenericStrategy] Using generic correction")

        # Minimal prompt (< 50 tokens + error message)
        prompt = f"""Failed SQL:
        {failed_sql}

        Error:
        {error_feedback}

        Do NOT repeat the same mistake.
        Return corrected SQL only for: {question}
        """.strip()


        return prompt


# ============================================================================
# STRATEGY ROUTER
# ============================================================================

class CorrectionStrategyRouter:
    """Route errors to appropriate correction strategy

    Routes to 4 strategies based on error type:
    - column_not_found → ColumnNotFoundStrategy (70%)
    - aggregation_error → AggregationErrorStrategy (20%)
    - timeout → TimeoutStrategy (5%)
    - Everything else → GenericStrategy (5%)

    Usage:
        router = CorrectionStrategyRouter()
        prompt = router.generate_prompt(
            error_type="column_not_found",
            error_feedback="column 'id' does not exist",
            failed_sql="SELECT id FROM products",
            question="What products do we have?"
        )
    """

    def __init__(self):
        """Initialize router with 4 strategies"""
        self.strategies = {
            "column_not_found": ColumnNotFoundStrategy(),
            "aggregation_error": AggregationErrorStrategy(),
            "timeout": TimeoutStrategy(),
        }
        self.default = GenericStrategy()

        logger.info("[CorrectionRouter] Initialized with 4 strategies")

    def generate_prompt(
        self,
        error_type: str,
        error_feedback: str,
        failed_sql: str,
        question: str
    ) -> str:
        """Generate correction prompt using appropriate strategy

        Routes to:
        - ColumnNotFoundStrategy if error_type == "column_not_found"
        - AggregationErrorStrategy if error_type == "aggregation_error"
        - TimeoutStrategy if error_type == "timeout"
        - GenericStrategy for all other error types

        Args:
            error_type: Error category from ErrorClassifier (Day 4)
            error_feedback: Human-readable error message
            failed_sql: SQL query that failed
            question: Original natural language question

        Returns:
            Minimal correction prompt (<100 tokens)
        """
        # Select strategy
        strategy = self.strategies.get(error_type, self.default)
        strategy_name = strategy.__class__.__name__

        logger.info(f"[CorrectionRouter] Routing {error_type} → {strategy_name}")

        # Generate prompt
        prompt = strategy.generate_prompt(
            error_feedback=error_feedback,
            failed_sql=failed_sql,
            question=question
        )

        # Log prompt length
        prompt_tokens = len(prompt.split())
        logger.info(f"[CorrectionRouter] Generated prompt ({prompt_tokens} tokens)")

        if prompt_tokens > 100:
            logger.warning(f"[CorrectionRouter] Prompt exceeds 100 tokens: {prompt_tokens}")

        return prompt

    def get_strategy(self, error_type: str) -> CorrectionStrategy:
        """Get strategy instance for error type

        Args:
            error_type: Error category

        Returns:
            Strategy instance
        """
        return self.strategies.get(error_type, self.default)


# ============================================================================
# HELPER: Critic Feedback Handler
# ============================================================================

def build_critic_correction_prompt(
    failed_sql: str,
    critic_issues: list[str],
    question: str
) -> str:
    """Build correction prompt from Critic validation issues

    🔧 Improvement 1: Handles case where Critic blocks SQL before execution.
    In this case, execution_result doesn't exist, so we use validation issues.

    Args:
        failed_sql: SQL that Critic rejected
        critic_issues: List of validation issues from Critic
        question: Original question

    Returns:
        Minimal correction prompt with Critic feedback
    """
    logger.info(f"[CriticCorrection] Building prompt for {len(critic_issues)} issues")

    # Format issues as bullet points
    issues_text = "\n".join(f"- {issue}" for issue in critic_issues)

    # Minimal prompt
    prompt = f"""Failed SQL:
{failed_sql}

Critic Issues:
{issues_text}

Fix and regenerate for: {question}
""".strip()

    return prompt


# ============================================================================
# CONSTANTS
# ============================================================================

# Non-retryable error types (updated to exclude timeout)
NON_RETRYABLE_ERRORS = {
    "permission_denied",  # User lacks database privileges
    "connection_error",   # Database unreachable
}

# Retryable error types (timeout is now retryable!)
RETRYABLE_ERRORS = {
    "column_not_found",
    "aggregation_error",
    "timeout",  # 🔧 Now retryable with simplification
    "syntax_error",
    "type_mismatch",
    "join_error",
    "table_not_found",
    "unknown",
}
