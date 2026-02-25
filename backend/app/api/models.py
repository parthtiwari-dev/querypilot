from pydantic import BaseModel
from typing import Optional, Any


class QueryRequest(BaseModel):
    question: str
    schema_name: str = "ecommerce"
    max_attempts: int = 3
    # Note: max_attempts is accepted for API compatibility.
    # Currently fixed at 3 at agent creation time.
    # Runtime override is ignored. See docs/API.md for details.

class QueryResponse(BaseModel):
    sql: Optional[str]
    success: bool
    attempts: int
    first_attempt_success: bool
    latency_ms: float
    schema_tables_used: list[str]
    correction_applied: bool
    rows: Optional[list[Any]]  # <- changed from list[dict]
    row_count: int
    error_type: Optional[str]
    error_message: Optional[str]

   