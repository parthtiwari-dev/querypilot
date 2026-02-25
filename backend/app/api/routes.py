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
