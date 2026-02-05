"""
Critic Agent - Day 3
Pre-execution SQL validation with 4-layer checks
"""
from dataclasses import dataclass
from typing import Dict, List, Set
import re
import logging

try:
    import sqlparse
except ImportError:
    sqlparse = None

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of SQL validation"""
    confidence: float
    is_valid: bool
    issues: List[str]
    layer_results: Dict[str, Dict]
    
    def __str__(self):
        status = "✓ VALID" if self.is_valid else "✗ INVALID"
        return f"{status} (confidence: {self.confidence:.2f}) - {len(self.issues)} issues"


class CriticAgent:
    """
    Validates generated SQL before execution.
    
    4-layer validation:
    1. Syntax (sqlparse)
    2. Schema (table/column existence)
    3. Safety (block destructive ops)
    4. Semantic (structural issues)
    
    Confidence scoring:
    - Start: 1.0
    - Syntax error: -0.6
    - Schema error: -0.4 per issue
    - Safety violation: = 0.0
    - Semantic issue: -0.2 per issue
    """
    
    # Dangerous SQL keywords (case-insensitive)
    UNSAFE_KEYWORDS = [
        'DROP', 'DELETE', 'ALTER', 'TRUNCATE', 
        'UPDATE', 'INSERT', 'CREATE', 'REPLACE'
    ]
    
    # Aggregation functions
    AGGREGATION_FUNCS = ['COUNT(', 'SUM(', 'AVG(', 'MAX(', 'MIN(']
    
    def __init__(self, confidence_threshold: float = 0.7):
        """
        Initialize Critic Agent.
        
        Args:
            confidence_threshold: Minimum confidence to consider valid (default 0.7)
        """
        self.threshold = confidence_threshold
        
        if sqlparse is None:
            logger.warning("sqlparse not installed. Syntax validation will be limited.")
    
    def validate(
        self,
        generated_sql: str,
        filtered_schema: Dict[str, Dict],
        question: str = ""
    ) -> ValidationResult:
        """
        Validate SQL through 4 layers.
        
        Args:
            generated_sql: SQL query to validate
            filtered_schema: Schema from Schema Linker
            question: Original question (optional, for logging)
        
        Returns:
            ValidationResult with confidence, validity, and issues
        """
        confidence = 1.0
        issues = []
        layer_results = {}
        
        # Layer 1: Syntax Validation
        syntax_result = self._validate_syntax(generated_sql)
        layer_results['syntax'] = syntax_result
        if not syntax_result['valid']:
            confidence -= 0.6
            issues.extend(syntax_result['issues'])
        
        # Layer 2: Schema Validation
        schema_result = self._validate_schema(generated_sql, filtered_schema)
        layer_results['schema'] = schema_result
        if not schema_result['valid']:
            # Stack penalties: -0.4 per missing table/column
            num_errors = len(schema_result['issues'])
            confidence -= (0.4 * num_errors)
            issues.extend(schema_result['issues'])
        
        # Layer 3: Safety Validation
        safety_result = self._validate_safety(generated_sql)
        layer_results['safety'] = safety_result
        if not safety_result['valid']:
            confidence = 0.0  # Hard override
            issues.extend(safety_result['issues'])
        
        # Layer 4: Semantic Validation (mechanical)
        semantic_result = self._validate_semantics(generated_sql)
        layer_results['semantic'] = semantic_result
        if not semantic_result['valid']:
            num_issues = len(semantic_result['issues'])
            confidence -= (0.2 * num_issues)
            issues.extend(semantic_result['issues'])
        
        # Clamp confidence
        confidence = max(0.0, min(confidence, 1.0))
        
        # Determine validity
        is_valid = (confidence >= self.threshold) and (confidence > 0.0)
        
        return ValidationResult(
            confidence=confidence,
            is_valid=is_valid,
            issues=issues,
            layer_results=layer_results
        )
    
    def _validate_syntax(self, sql: str) -> Dict:
        """
        Layer 1: Validate SQL syntax.
        
        Returns:
            {'valid': bool, 'issues': List[str]}
        """
        issues = []
        
        # Basic checks
        if not sql or not sql.strip():
            issues.append("Empty SQL query")
            return {'valid': False, 'issues': issues}
        
        sql_upper = sql.upper().strip()
        
        # Must start with SELECT or WITH
        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            issues.append("SQL must start with SELECT or WITH")
            return {'valid': False, 'issues': issues}
        
        # Use sqlparse if available
        if sqlparse:
            try:
                parsed = sqlparse.parse(sql)
                if not parsed:
                    issues.append("SQL parsing failed - invalid syntax")
                    return {'valid': False, 'issues': issues}
                
                # Check for basic structure
                statement = parsed[0]
                if statement.get_type() not in ['SELECT', 'UNKNOWN']:
                    issues.append(f"Unexpected SQL type: {statement.get_type()}")
                    return {'valid': False, 'issues': issues}
                
            except Exception as e:
                issues.append(f"Syntax error: {str(e)}")
                return {'valid': False, 'issues': issues}
        
        # Basic syntax checks (fallback if no sqlparse)
        if sql.count('(') != sql.count(')'):
            issues.append("Unmatched parentheses")
            return {'valid': False, 'issues': issues}
        
        return {'valid': True, 'issues': []}
    
    def _validate_schema(self, sql: str, filtered_schema: Dict[str, Dict]) -> Dict:
        """
        Layer 2: Validate all tables and columns exist in schema.
        
        Returns:
            {'valid': bool, 'issues': List[str]}
        """
        issues = []
        
        if not filtered_schema:
            issues.append("No schema provided for validation")
            return {'valid': False, 'issues': issues}
        
        # Extract table names from SQL
        referenced_tables = self._extract_table_names(sql)
        schema_tables = set(filtered_schema.keys())
        
        # Check tables exist
        for table in referenced_tables:
            if table not in schema_tables:
                issues.append(f"Table '{table}' not in schema (available: {', '.join(schema_tables)})")
        
        # Extract column references
        referenced_columns = self._extract_column_references(sql)
        
        # Check columns exist in their tables
        for table, columns in referenced_columns.items():
            if table not in filtered_schema:
                continue  # Already flagged above
            
            schema_columns = set(filtered_schema[table]['columns'].keys())
            
            for col in columns:
                if col not in schema_columns and col != '*':
                    issues.append(
                        f"Column '{col}' not in table '{table}' "
                        f"(available: {', '.join(list(schema_columns)[:5])}...)"
                    )
        
        return {'valid': len(issues) == 0, 'issues': issues}
    
    def _validate_safety(self, sql: str) -> Dict:
        """
        Layer 3: Check for dangerous operations.
        
        Returns:
            {'valid': bool, 'issues': List[str]}
        """
        issues = []
        sql_upper = sql.upper()
        
        for keyword in self.UNSAFE_KEYWORDS:
            if keyword in sql_upper:
                issues.append(f"Unsafe operation detected: {keyword}")
        
        return {'valid': len(issues) == 0, 'issues': issues}
    
    def _validate_semantics(self, sql: str) -> Dict:
        """
        Layer 4: Mechanical semantic checks (no NLP).
        
        Checks:
        1. Multiple tables → Expect JOIN
        2. Aggregation + multiple columns → Expect GROUP BY
        
        Returns:
            {'valid': bool, 'issues': List[str]}
        """
        issues = []
        sql_upper = sql.upper()
        
        # Check 1: Multiple tables but no JOIN
        num_tables = len(self._extract_table_names(sql))
        has_join = 'JOIN' in sql_upper
        
        if num_tables > 1 and not has_join:
            issues.append("Multiple tables detected but no JOIN found (possible cartesian product)")
        
        # Check 2: Aggregation without GROUP BY
        has_aggregation = any(func in sql_upper for func in self.AGGREGATION_FUNCS)
        has_group_by = 'GROUP BY' in sql_upper
        
        if has_aggregation and not has_group_by:
            # Check if SELECT has multiple columns (simple heuristic)
            try:
                select_clause = sql_upper.split('FROM')[0]
                # Count commas in SELECT (rough indicator of multiple columns)
                if ',' in select_clause:
                    issues.append("Aggregation with multiple columns but no GROUP BY")
            except:
                pass  # If parsing fails, skip this check
        
        return {'valid': len(issues) == 0, 'issues': issues}
    
    def _extract_table_names(self, sql: str) -> Set[str]:
        """
        Extract table names from SQL query.
        Handles: FROM table, JOIN table, table AS alias
        
        Returns:
            Set of table names
        """
        tables = set()
        sql_upper = sql.upper()
        
        # Pattern: FROM/JOIN table_name [AS alias]
        # Simple regex approach
        patterns = [
            r'FROM\s+(\w+)',
            r'JOIN\s+(\w+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, sql_upper)
            tables.update(match.lower() for match in matches)

        # NEW: extract CTE names
        cte_matches = re.findall(r'WITH\s+(\w+)\s+AS', sql_upper)
        tables.update(match.lower() for match in cte_matches)

        return tables


    def _extract_column_references(self, sql: str) -> Dict[str, Set[str]]:
        """
        Extract column references grouped by table.
        Handles: table.column, alias.column
        For bare columns (no table prefix), only check if single table query.
        
        Returns:
            Dict mapping table/alias to set of columns
        """
        references = {}
        
        # Pattern 1: table.column or alias.column (most reliable)
        pattern = r'(\w+)\.(\w+)'
        matches = re.findall(pattern, sql)
        
        for table_or_alias, column in matches:
            table_key = table_or_alias.lower()
            if table_key not in references:
                references[table_key] = set()
            references[table_key].add(column.lower())

        # Also capture columns used as function arguments, e.g. DATE_TRUNC('month', order_date)
        # and MAX(order_date) — include qualified names like alias.column as well.
        try:
            from_tables = self._extract_table_names(sql)
        except Exception:
            from_tables = set()

        func_pattern = re.compile(r"\b\w+\s*\([^)]*?,\s*([A-Za-z_][\w\.]*)\)", re.IGNORECASE)
        func_matches = func_pattern.findall(sql)
        for col in func_matches:
            col_clean = col.strip().strip(') ,')
            col_clean = col_clean.strip('"\'')
            # If qualified (table.column), split and add
            if '.' in col_clean:
                table_part, col_part = col_clean.split('.', 1)
                table_key = table_part.lower()
                if table_key not in references:
                    references[table_key] = set()
                references[table_key].add(col_part.lower())
            else:
                # If single-table query, attribute bare function arg to that table
                if len(from_tables) == 1:
                    table = list(from_tables)[0]
                    if table not in references:
                        references[table] = set()
                    references[table].add(col_clean.lower())

        # Pattern 2: Bare column names (only for single-table queries)
        # Multi-table queries with bare columns are too ambiguous to validate reliably
        from_tables = self._extract_table_names(sql)
        
        if len(from_tables) == 1:
            # Single table - safe to check bare columns
            table = list(from_tables)[0]
            
            try:
                select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
                if select_match:
                    select_clause = select_match.group(1)
                    
                    # Extract column names
                    columns = [col.strip() for col in select_clause.split(',')]
                    
                    if table not in references:
                        references[table] = set()
                    
                    for col in columns:
                        # Skip if has table prefix (already caught by pattern 1)
                        if '.' in col:
                            continue
                        
                        # Skip SQL keywords, functions, and wildcards
                        col_upper = col.upper()
                        skip_keywords = ['AS', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'DISTINCT', '*']
                        if any(kw in col_upper for kw in skip_keywords):
                            continue
                        
                        # Extract just the column name (remove AS aliases, etc)
                        col_name = col.split()[0].strip('(),')
                        
                        if col_name and not col_name.upper() in skip_keywords:
                            references[table].add(col_name.lower())
            except:
                pass  # If parsing fails, rely on pattern 1 only
        
        # Resolve aliases to actual table names
        # Pattern: FROM table AS alias
        alias_pattern = r'(?:FROM|JOIN)\s+(\w+)\s+(?:AS\s+)?(\w+)'
        aliases = re.findall(alias_pattern, sql, re.IGNORECASE)
        
        alias_map = {}
        for table, alias in aliases:
            # Only treat as alias if different from table name
            if table.lower() != alias.lower():
                alias_map[alias.lower()] = table.lower()
        
        # Resolve aliases
        resolved = {}
        for key, cols in references.items():
            actual_table = alias_map.get(key, key)
            if actual_table not in resolved:
                resolved[actual_table] = set()
            resolved[actual_table].update(cols)
        
        return resolved



# Testing when run directly
if __name__ == "__main__":
    print("\n" + "="*60)
    print("CRITIC AGENT - VALIDATION TESTS")
    print("="*60)
    
    # Mock schema
    test_schema = {
        "products": {
            "columns": {"product_id": "INTEGER", "name": "VARCHAR", "price": "DECIMAL"},
            "primary_keys": ["product_id"],
            "foreign_keys": {}
        },
        "orders": {
            "columns": {"order_id": "INTEGER", "customer_id": "INTEGER", "total": "DECIMAL"},
            "primary_keys": ["order_id"],
            "foreign_keys": {}
        }
    }
    
    critic = CriticAgent()
    
    # Test cases
    test_cases = [
        {
            "name": "Valid simple query",
            "sql": "SELECT product_id, name FROM products LIMIT 1000",
            "expected_valid": True
        },
        {
            "name": "Column hallucination (products.id)",
            "sql": "SELECT id FROM products",
            "expected_valid": False
        },
        {
            "name": "Table hallucination",
            "sql": "SELECT * FROM invoices",
            "expected_valid": False
        },
        {
            "name": "Unsafe operation (DELETE)",
            "sql": "DELETE FROM products WHERE price > 100",
            "expected_valid": False
        },
        {
            "name": "Multiple tables, no JOIN",
            "sql": "SELECT * FROM products, orders",
            "expected_valid": True  # Warning but not invalid
        },
        {
            "name": "Valid JOIN query",
            "sql": "SELECT p.name FROM products p JOIN orders o ON p.product_id = o.product_id",
            "expected_valid": True
        }
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{i}. {test['name']}")
        print(f"   SQL: {test['sql'][:60]}...")
        
        result = critic.validate(test['sql'], test_schema)
        print(f"   Result: {result}")
        
        if result.is_valid == test['expected_valid']:
            print(f"   ✓ PASS")
        else:
            print(f"   ✗ FAIL (expected valid={test['expected_valid']})")
