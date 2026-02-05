"""
SQL Generation Agent - Day 2
Converts natural language question + filtered schema → PostgreSQL SQL
"""
from typing import Dict, Optional
from app.config import get_llm


# Prompt Template Version 1
SQL_GENERATION_PROMPT_V1 = """You are a PostgreSQL SQL expert. Generate accurate SQL queries based on the provided database schema.

DATABASE SCHEMA:
{filtered_schema}

POSTGRESQL SYNTAX REMINDERS:
- Use :: for type casting (e.g., column_name::INTEGER)
- Date functions: DATE_TRUNC('month', date_column), CURRENT_DATE
- Limit results: ORDER BY column LIMIT N
- String matching: ILIKE for case-insensitive search

SAFETY RULES:
- Use ONLY the tables and columns listed in the schema above
- Do NOT reference tables or columns not explicitly provided
- Always add LIMIT 1000 to SELECT queries unless a different limit is specified
- Never use DROP, DELETE, ALTER, TRUNCATE, or other destructive operations
- If you need a table that is not in the schema, return SQL with a -- TODO: Missing table comment
- When multiple tables are required, use explicit JOIN conditions based on foreign keys
- Avoid SELECT *; select only necessary columns
- When using aggregation, ensure correct GROUP BY clauses

USER QUESTION:
{question}

OUTPUT:
Return ONLY the SQL query starting with SELECT or WITH. No explanations or markdown."""


def format_schema_to_text(filtered_schema: Dict) -> str:
    """
    Convert filtered schema dict to plain text format for prompt.
    
    Args:
        filtered_schema: Dict mapping table names to their metadata
            Example: {
                "products": {
                    "columns": {"product_id": "INTEGER", "name": "VARCHAR", ...},
                    "primary_keys": ["product_id"],
                    "foreign_keys": {"category_id": "categories.category_id"}
                }
            }
    
    Returns:
        Plain text schema description
    """
    if not filtered_schema:
        return "No tables found in schema."
    
    schema_lines = []
    
    for table_name, table_info in filtered_schema.items():
        # Table header
        schema_lines.append(f"Table: {table_name}")
        
        # Columns
        columns = table_info.get("columns", {})
        if columns:
            col_strs = [f"{col_name} ({col_type})" for col_name, col_type in columns.items()]
            schema_lines.append(f"Columns: {', '.join(col_strs)}")
        
        # Primary keys
        primary_keys = table_info.get("primary_keys", [])
        if primary_keys:
            schema_lines.append(f"Primary Key: {', '.join(primary_keys)}")
        
        # Foreign keys
        foreign_keys = table_info.get("foreign_keys", {})
        if foreign_keys:
            fk_strs = [f"{fk_col} → {ref_table}" for fk_col, ref_table in foreign_keys.items()]
            schema_lines.append(f"Foreign Keys: {', '.join(fk_strs)}")
        
        schema_lines.append("")  # Blank line between tables
    
    return "\n".join(schema_lines)


class SQLGenerator:
    """
    SQL Generation Agent - converts question + filtered schema to SQL.
    
    Design:
    - Single responsibility: generate SQL only (no validation, no execution)
    - Uses Groq (Llama 3.1 70B) by default via get_llm()
    - Zero-shot prompt with PostgreSQL-specific instructions
    - Enforces schema constraints to prevent hallucinations
    """
    
    def __init__(self, prompt_version: str = "v1"):
        """
        Initialize SQL Generator.
        
        Args:
            prompt_version: Which prompt template to use ("v1", "v2", etc.)
        """
        self.llm = get_llm()
        self.prompt_version = prompt_version
        
        # Select prompt template
        if prompt_version == "v1":
            self.prompt_template = SQL_GENERATION_PROMPT_V1
        else:
            raise ValueError(f"Unknown prompt version: {prompt_version}")
    
    def generate(
        self,
        question: str,
        filtered_schema: Dict,
        conversation_history: Optional[list] = None
    ) -> str:
        """
        Generate PostgreSQL SQL query from question and filtered schema.
        
        Args:
            question: User's natural language question
            filtered_schema: Dict of relevant tables from Schema Linker
            conversation_history: Optional conversation context (unused in Day 2)
        
        Returns:
            SQL query string
        
        Raises:
            ValueError: If filtered_schema is empty or invalid
        """
        # Validation
        if not question or not question.strip():
            raise ValueError("Question cannot be empty")
        
        if not filtered_schema:
            raise ValueError("Filtered schema cannot be empty")
        
        # Format schema to plain text
        schema_text = format_schema_to_text(filtered_schema)
        
        # Build prompt
        prompt = self.prompt_template.format(
            filtered_schema=schema_text,
            question=question.strip()
        )
        
        # Generate SQL via LLM
        response = self.llm.invoke(prompt)
        
        # Extract SQL from response
        sql = self._extract_sql(response.content if hasattr(response, 'content') else str(response))
        
        return sql
    
    def _extract_sql(self, response: str) -> str:
        """
        Clean and extract SQL from LLM response.
        
        Args:
            response: Raw LLM response
        
        Returns:
            Cleaned SQL string
        """
        sql = response.strip()
        
        # Remove markdown code blocks if present (safety fallback)
        if sql.startswith("```sql"):
            sql = sql[6:]
        if sql.startswith("```"):
            sql = sql[3:]
        if sql.endswith("```"):
            sql = sql[:-3]
        
        # Strip whitespace
        sql = sql.strip()
        
        return sql
