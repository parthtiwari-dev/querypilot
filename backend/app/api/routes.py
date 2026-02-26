from fastapi import APIRouter, HTTPException
from app.api.models import QueryRequest, QueryResponse
from app.agents.orchestrator import run_query
from app.config import SCHEMA_PROFILES

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    if request.schema_name not in SCHEMA_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown schema '{request.schema_name}'. "
                f"Available: {list(SCHEMA_PROFILES.keys())}"
            ),
        )
    
        # Block sensitive queries before they enter the pipeline
    SENSITIVE_KEYWORDS = [
        "password", "passwd", "secret", "credential", "credentials",
        "api_key", "apikey", "token", "private_key",
        "pg_shadow", "pg_authid", "information_schema.tables",
    ]
    question_lower = request.question.lower()
    if any(kw in question_lower for kw in SENSITIVE_KEYWORDS):
        return {
            "sql": "",
            "success": False,
            "attempts": 0,
            "first_attempt_success": False,
            "latency_ms": 0.0,
            "schema_tables_used": [],
            "correction_applied": False,
            "rows": [],
            "row_count": 0,
            "error_type": "blocked",
            "error_message": "This query was blocked for safety reasons.",
        }

    # Orchestrator already returns the exact shape QueryResponse expects.
    result = run_query(
        question=request.question,
        schema_name=request.schema_name,
        max_attempts=request.max_attempts,
    )
    return result  # <- no re-mapping, no extra wrapping


@router.get("/health")
def health():
    return {
        "status": "ok",
        "schemas_available": list(SCHEMA_PROFILES.keys()),
    }
