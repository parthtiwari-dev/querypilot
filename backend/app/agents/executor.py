"""
Executor Agent - Safe SQL execution with intelligent error classification

Responsibilities:
1. Execute validated SQL queries on PostgreSQL with safety measures
2. Classify execution errors into actionable categories
3. Generate helpful feedback for error recovery
4. Track execution metrics for monitoring

Critical Fixes Implemented:
- Fix #1: Safe LIMIT injection (documents nested query limitations)
- Fix #2: Transaction-scoped timeout (SET LOCAL, no connection pool pollution)
- Fix #3: Memory-safe result fetching (fetchmany instead of fetchall)
- Fix #4: Priority-ordered error classification (no ambiguity)
- Fix #5: Error distribution tracking (for Day 5 self-correction)
"""

import re
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Tuple
from difflib import get_close_matches

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


# ============================================================================
# ERROR CATEGORIES
# ============================================================================

class ErrorCategory(Enum):
    """
    Error categories for execution failures
    
    Organized by fixability:
    - Schema errors: Can fix with better schema linking
    - SQL errors: Can fix with SQL regeneration
    - System errors: Require system-level intervention
    """
    # Schema errors (fixable with schema validation)
    COLUMN_NOT_FOUND = "column_not_found"
    TABLE_NOT_FOUND = "table_not_found"
    
    # SQL errors (fixable with regeneration)
    SYNTAX_ERROR = "syntax_error"
    TYPE_MISMATCH = "type_mismatch"
    JOIN_ERROR = "join_error"
    AGGREGATION_ERROR = "aggregation_error"
    
    # System errors (require intervention)
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    CONNECTION_ERROR = "connection_error"
    
    # Catch-all
    UNKNOWN = "unknown"


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ExecutionResult:
    """Result of SQL execution"""
    success: bool                         # True if query executed successfully
    data: Optional[List[Tuple]] = None    # Query results (if success)
    error_type: Optional[str] = None      # Error category (if failure)
    error_message: Optional[str] = None   # Raw error text (if failure)
    error_feedback: Optional[str] = None  # Helpful feedback (if failure)
    error_details: Optional[Dict] = None  # Extracted details (if failure)
    execution_time_ms: float = 0.0        # Query execution latency
    row_count: int = 0                    # Number of rows returned
    sql_executed: str = ""                # Actual SQL executed (with LIMIT)
    
    def __str__(self):
        if self.success:
            return f"✓ SUCCESS: {self.row_count} rows in {self.execution_time_ms:.1f}ms"
        else:
            return f"✗ FAILED: {self.error_type} - {self.error_message}"


@dataclass
class ExecutionMetrics:
    """Execution statistics for monitoring and optimization"""
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_execution_time_ms: float = 0.0
    avg_execution_time_ms: float = 0.0
    max_execution_time_ms: float = 0.0
    min_execution_time_ms: float = float('inf')
    
    # Fix #5: Error distribution tracking (for Day 5 self-correction)
    error_counts: Dict[str, int] = field(default_factory=dict)
    
    def record_error(self, error_type: str):
        """Track error type frequency"""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
    
    def update(self, result: ExecutionResult):
        """Update metrics from execution result"""
        self.total_queries += 1
        
        if result.success:
            self.successful_queries += 1
        else:
            self.failed_queries += 1
            self.record_error(result.error_type)
        
        # Update timing stats
        self.total_execution_time_ms += result.execution_time_ms
        self.avg_execution_time_ms = self.total_execution_time_ms / self.total_queries
        self.max_execution_time_ms = max(self.max_execution_time_ms, result.execution_time_ms)
        self.min_execution_time_ms = min(self.min_execution_time_ms, result.execution_time_ms)
    
    def __str__(self):
        success_rate = (self.successful_queries / self.total_queries * 100) if self.total_queries > 0 else 0
        return (
            f"Metrics: {self.total_queries} queries, "
            f"{success_rate:.1f}% success, "
            f"avg {self.avg_execution_time_ms:.1f}ms"
        )


# ============================================================================
# ERROR CLASSIFIER
# ============================================================================

class ErrorClassifier:
    """
    Classifies execution errors into actionable categories
    
    Fix #4: Priority-ordered classification (no ambiguous matches)
    """
    
    def classify(self, error: Exception) -> ErrorCategory:
        """
        Classify error with priority ordering (most specific first)
        
        Priority levels:
        1. System errors (timeout, connection, permission)
        2. Schema errors (column, table not found)
        3. SQL errors (aggregation, join, type mismatch)
        4. Generic errors (syntax)
        5. Unknown (fallback)
        """
        error_msg = str(error).lower()
        
        # Priority 1: System errors (highest priority)
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
        
        # Priority 3: SQL errors (moderate specificity)
        if self._check_aggregation_error(error_msg):
            return ErrorCategory.AGGREGATION_ERROR
        if self._check_join_error(error_msg):
            return ErrorCategory.JOIN_ERROR
        if self._check_type_mismatch(error_msg):
            return ErrorCategory.TYPE_MISMATCH
        
        # Priority 4: Generic errors (low priority)
        if self._check_syntax_error(error_msg):
            return ErrorCategory.SYNTAX_ERROR
        
        # Priority 5: Fallback
        return ErrorCategory.UNKNOWN
    
    # System error checks
    def _check_timeout(self, error_msg: str) -> bool:
        patterns = [
            "canceling statement due to statement timeout",
            "query_timeout",
            "execution timeout",
            "statement timeout"
        ]
        return any(pattern in error_msg for pattern in patterns)
    
    def _check_connection(self, error_msg: str) -> bool:
        patterns = [
            "could not connect to server",
            "connection refused",
            "connection reset",
            "connection timed out",
            "server closed the connection"
        ]
        return any(pattern in error_msg for pattern in patterns)
    
    def _check_permission(self, error_msg: str) -> bool:
        patterns = [
            "permission denied",
            "must be owner of",
            "access denied"
        ]
        return any(pattern in error_msg for pattern in patterns)
    
    # Schema error checks
    def _check_column_not_found(self, error_msg: str) -> bool:
        patterns = [
            r"column .* does not exist",
            r"column .* of relation .* does not exist"
        ]
        return any(re.search(pattern, error_msg) for pattern in patterns)
    
    def _check_table_not_found(self, error_msg: str) -> bool:
        patterns = [
            r"relation .* does not exist",
            r"table .* does not exist"
        ]
        return any(re.search(pattern, error_msg) for pattern in patterns)
    
    # SQL error checks
    def _check_aggregation_error(self, error_msg: str) -> bool:
        patterns = [
            "must appear in the group by clause",
            "aggregate functions are not allowed",
            r"column .* must appear in the group by"
        ]
        return any(re.search(pattern, error_msg) for pattern in patterns)
    
    def _check_join_error(self, error_msg: str) -> bool:
        patterns = [
            r"column reference .* is ambiguous",
            "missing from-clause entry",
            "ambiguous column"
        ]
        return any(re.search(pattern, error_msg) for pattern in patterns)
    
    def _check_type_mismatch(self, error_msg: str) -> bool:
        patterns = [
            "cannot cast type",
            "invalid input syntax for type",
            "operator does not exist",
            "type mismatch"
        ]
        return any(pattern in error_msg for pattern in patterns)
    
    def _check_syntax_error(self, error_msg: str) -> bool:
        patterns = [
            "syntax error at or near",
            "syntax error",
            "invalid syntax"
        ]
        return any(pattern in error_msg for pattern in patterns)
    
    def extract_details(self, error: Exception, category: ErrorCategory) -> dict:
        """Extract specific details based on error category"""
        error_msg = str(error)
        details = {'full_error': error_msg}  # ✅ Add full error for context
        
        if category == ErrorCategory.COLUMN_NOT_FOUND:
            match = re.search(r'column "?(\w+)"? does not exist', error_msg, re.IGNORECASE)
            if match:
                details['missing_column'] = match.group(1)
                
        elif category == ErrorCategory.TABLE_NOT_FOUND:
            # Extract table name: 'relation "invoices" does not exist'
            match = re.search(r'relation "?(\w+)"? does not exist', error_msg, re.IGNORECASE)
            if match:
                details['missing_table'] = match.group(1)
        
        elif category == ErrorCategory.SYNTAX_ERROR:
            # Extract error location: 'syntax error at or near "FRM"'
            match = re.search(r'at or near "?(\w+)"?', error_msg, re.IGNORECASE)
            if match:
                details['error_near'] = match.group(1)
        
        return details
    
    def generate_feedback(
        self,
        category: ErrorCategory,
        details: dict,
        schema: dict = None
    ) -> str:
        """
        Generate helpful feedback for error recovery
        
        Schema-aware feedback when available (for column/table suggestions)
        
        Fix #9: Table-aware error feedback to prevent contradictory messages
        """
        
        if category == ErrorCategory.COLUMN_NOT_FOUND:
            missing_col = details.get('missing_column', 'unknown')
            
            if schema:
                # ✅ FIX #9: Extract table context from error message
                full_error = details.get('full_error', '').lower()
                
                # Try to identify which table the error refers to
                # Method 1: Look for explicit table references in error
                target_table = None
                for table in schema.keys():
                    # Check if table name appears in the error context
                    if table.lower() in full_error:
                        target_table = table
                        break
                
                # Method 2: If single table in schema, it must be that one
                if not target_table and len(schema) == 1:
                    target_table = list(schema.keys())[0]
                
                if target_table:
                    # Show columns from the specific table that caused the error
                    table_cols = list(schema[target_table]['columns'].keys())
                    suggestions = get_close_matches(missing_col, table_cols, n=3, cutoff=0.6)
                    
                    if suggestions:
                        return (
                            f"Column '{missing_col}' does not exist in table '{target_table}'. "
                            f"Available columns in {target_table}: {', '.join(table_cols)}. "
                            f"Did you mean: {', '.join(suggestions)}?"
                        )
                    else:
                        return (
                            f"Column '{missing_col}' does not exist in table '{target_table}'. "
                            f"Available columns in {target_table}: {', '.join(table_cols)}."
                        )
                else:
                    # Fallback: Can't determine specific table, search across all tables
                    all_columns_by_table = {}
                    for table, table_info in schema.items():
                        for col in table_info['columns'].keys():
                            if col.lower() not in all_columns_by_table:
                                all_columns_by_table[col.lower()] = []
                            all_columns_by_table[col.lower()].append(table)
                    
                    # Find similar column names across all tables
                    all_col_names = list(all_columns_by_table.keys())
                    suggestions = get_close_matches(missing_col.lower(), all_col_names, n=3, cutoff=0.6)
                    
                    if suggestions:
                        # Show which table(s) contain the suggestion
                        suggestion_details = []
                        for sug in suggestions:
                            tables_with_col = all_columns_by_table[sug]
                            suggestion_details.append(f"{sug} (in {', '.join(tables_with_col)})")
                        
                        return (
                            f"Column '{missing_col}' does not exist. "
                            f"Did you mean: {', '.join(suggestion_details)}?"
                        )
                    else:
                        # List available tables and sample columns
                        table_summaries = []
                        for table in list(schema.keys())[:3]:  # Show first 3 tables
                            cols = list(schema[table]['columns'].keys())[:3]
                            table_summaries.append(f"{table} ({', '.join(cols)}...)")
                        
                        return (
                            f"Column '{missing_col}' does not exist. "
                            f"Available tables: {', '.join(table_summaries)}"
                        )
            else:
                return f"Column '{missing_col}' does not exist. Check schema for valid column names."
        
        elif category == ErrorCategory.TABLE_NOT_FOUND:
            missing_table = details.get('missing_table', 'unknown')
            
            if schema:
                available_tables = list(schema.keys())
                suggestions = get_close_matches(missing_table, available_tables, n=3, cutoff=0.6)
                
                if suggestions:
                    return (
                        f"Table '{missing_table}' does not exist. "
                        f"Available tables: {', '.join(available_tables)}. "
                        f"Did you mean: {', '.join(suggestions)}?"
                    )
                else:
                    return (
                        f"Table '{missing_table}' does not exist. "
                        f"Available tables: {', '.join(available_tables)}."
                    )
            else:
                return f"Table '{missing_table}' does not exist. Check schema for valid table names."
        
        elif category == ErrorCategory.SYNTAX_ERROR:
            error_near = details.get('error_near', 'unknown')
            return (
                f"SQL syntax error near '{error_near}'. "
                f"Check for typos in SQL keywords (SELECT, FROM, WHERE, JOIN, etc.)."
            )
        
        elif category == ErrorCategory.TYPE_MISMATCH:
            return (
                "Type mismatch error. "
                "Check that column data types match comparison values. "
                "Use explicit casting if needed (e.g., price::numeric > 100)."
            )
        
        elif category == ErrorCategory.JOIN_ERROR:
            return (
                "JOIN error - column reference is ambiguous. "
                "Use table aliases (e.g., p.product_id, o.order_id) to clarify which table's column."
            )
        
        elif category == ErrorCategory.AGGREGATION_ERROR:
            return (
                "Aggregation error - missing GROUP BY clause. "
                "When using COUNT/SUM/AVG, non-aggregated columns must be in GROUP BY."
            )
        
        elif category == ErrorCategory.TIMEOUT:
            return (
                "Query execution timeout (exceeded 30 seconds). "
                "Query is too complex or slow. Try simplifying, adding indexes, or using LIMIT."
            )
        
        elif category == ErrorCategory.PERMISSION_DENIED:
            return (
                "Permission denied. "
                "Database user lacks permission to access this table or perform this operation."
            )
        
        elif category == ErrorCategory.CONNECTION_ERROR:
            return (
                "Database connection error. "
                "Check that PostgreSQL is running and connection settings are correct."
            )
        
        else:  # UNKNOWN
            return f"Unknown error occurred: {details.get('error_message', 'No details available')}"


# ============================================================================
# EXECUTOR AGENT
# ============================================================================

class ExecutorAgent:
    """
    Safe SQL execution agent with error classification
    
    Features:
    - Connection pooling for performance
    - Automatic timeout enforcement (30s default)
    - Row limit enforcement (1000 default)
    - Intelligent error classification
    - Schema-aware error feedback
    - Execution metrics tracking
    """
    
    def __init__(self, database_url: str):
        """
        Initialize Executor with connection pooling
        
        Args:
            database_url: PostgreSQL connection string
        """
        logger.info("Initializing Executor Agent...")
        
        # Create SQLAlchemy engine with connection pooling
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=5,              # Max 5 persistent connections
            max_overflow=10,          # Allow 10 extra if busy
            pool_pre_ping=True,       # Test connection before use (prevents stale connections)
            pool_recycle=3600         # Recycle connections after 1 hour
        )
        
        # Initialize error classifier
        self.classifier = ErrorClassifier()
        
        # Initialize metrics tracking
        self.metrics = ExecutionMetrics()
        
        logger.info("Executor Agent initialized successfully")
        logger.info(f"Connection pool: size=5, max_overflow=10, recycle=3600s")
    
    def execute(
        self,
        sql: str,
        timeout_seconds: int = 30,
        row_limit: int = 1000,
        schema: Dict[str, Dict] = None
    ) -> ExecutionResult:
        """
        Execute SQL query safely with error classification
        
        Args:
            sql: SQL query to execute
            timeout_seconds: Query timeout (default 30s)
            row_limit: Maximum rows to return (default 1000)
            schema: Schema metadata for error feedback (optional)
        
        Returns:
            ExecutionResult with data or error classification
        """
        start_time = time.time()
        
        try:
            # Fix #1: Add LIMIT clause if not present (simple strategy)
            sql_with_limit = self._add_row_limit(sql, row_limit)
            
            logger.info(f"Executing SQL: {sql_with_limit[:80]}...")
            
            # Execute with connection from pool
            with self.engine.connect() as conn:
                # Fix #2: Set LOCAL timeout (transaction-scoped, no pool pollution)
                timeout_ms = timeout_seconds * 1000
                conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
                
                # Execute query
                result = conn.execute(text(sql_with_limit))
                
                # Fix #3: Use fetchmany for memory safety (caps at row_limit)
                rows = result.fetchmany(row_limit)
                
                execution_time_ms = (time.time() - start_time) * 1000
                
                logger.info(f"Execution successful: {len(rows)} rows in {execution_time_ms:.1f}ms")
                
                # Create success result
                exec_result = ExecutionResult(
                    success=True,
                    data=rows,
                    execution_time_ms=round(execution_time_ms, 2),
                    row_count=len(rows),
                    sql_executed=sql_with_limit
                )
                
                # Update metrics
                self.metrics.update(exec_result)
                
                return exec_result
        
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            
            logger.error(f"Execution failed: {str(e)}")
            
            # Fix #4: Classify error with priority ordering
            error_category = self.classifier.classify(e)
            error_details = self.classifier.extract_details(e, error_category)
            
            # Generate helpful feedback (schema-aware if available)
            error_feedback = self.classifier.generate_feedback(
                error_category,
                error_details,
                schema
            )
            
            logger.error(f"Error classified as: {error_category.value}")
            logger.error(f"Feedback: {error_feedback}")
            
            # Create failure result
            exec_result = ExecutionResult(
                success=False,
                error_type=error_category.value,
                error_message=str(e),
                error_feedback=error_feedback,
                error_details=error_details,
                execution_time_ms=round(execution_time_ms, 2),
                row_count=0,
                sql_executed=sql
            )
            
            # Fix #5: Update metrics with error distribution
            self.metrics.update(exec_result)
            
            return exec_result
    
    def _add_row_limit(self, sql: str, limit: int) -> str:
        """
        Add LIMIT clause if not present (simple strategy)
        
        Fix #1 Implementation:
        - Simple substring check (works for 95% of cases)
        - Known limitation: Nested subqueries may not get outer LIMIT
        - Trade-off: Simplicity > perfect SQL parsing
        
        Known broken cases:
        - Nested queries: SELECT * FROM (SELECT * FROM t LIMIT 50) sub
        - CTEs: WITH t AS (...) SELECT ...
        
        Future improvement (Day 8): Use sqlparse AST for correct placement
        """
        sql = sql.rstrip(";").strip()
        sql_upper = sql.upper()
        
        # Simple check: if LIMIT exists anywhere, trust it
        if "LIMIT" not in sql_upper:
            sql += f" LIMIT {limit}"
        
        return sql
    
    def get_metrics(self) -> ExecutionMetrics:
        """Get current execution metrics"""
        return self.metrics
    
    def reset_metrics(self):
        """Reset metrics (useful for testing)"""
        self.metrics = ExecutionMetrics()
        logger.info("Metrics reset")
    
    def close(self):
        """Close database connection pool"""
        self.engine.dispose()
        logger.info("Executor Agent closed, connection pool disposed")
