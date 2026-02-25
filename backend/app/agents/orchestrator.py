"""
Pipeline Orchestrator — QueryPilot

Single entrypoint for the full Text-to-SQL pipeline.
Caches built agents per schema to avoid re-initialization on every request.

Caching rationale:
  - SchemaEmbedder loads all-MiniLM-L6-v2 from disk (~400ms per load)
  - create_self_correction_graph() compiles a LangGraph graph per call
  - ExecutorAgent creates a SQLAlchemy connection pool per instantiation
  Rebuilding these per request benchmarks initialization, not reasoning.

max_attempts note:
  Accepted as a parameter for API compatibility.
  Currently fixed at 3 at agent creation time (cache creation).
  Runtime override via run_query(max_attempts=N) is ignored.
  Rationale: rebuilding CorrectionAgent per request recompiles the graph.

Threading limitation:
  create_self_correction_graph() in self_correction.py writes agent
  references to module-level globals. Concurrent requests for *different*
  schemas may overwrite each other's globals mid-execution.
  Safe for single-threaded uvicorn dev server (default).
  Do NOT run with --workers > 1 until self_correction.py internals
  are redesigned. This is a known, documented limitation.
"""

import time
import logging
from typing import Optional

from app.config import settings, SCHEMA_PROFILES, DEFAULT_SCHEMA
from app.agents.schema_linker import SchemaLinker
from app.agents.sql_generator import SQLGenerator
from app.agents.critic import CriticAgent
from app.agents.executor import ExecutorAgent
from app.agents.self_correction import CorrectionAgent


logger = logging.getLogger(__name__)


# ── Module-level agent cache ──────────────────────────────────────────────────
# Key: schema_name (str)
# Value: fully built CorrectionAgent with all sub-agents wired
# Built once on first request per schema, reused on all subsequent requests.
_agent_cache: dict = {}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_db_url_with_schema(base_url: str, pg_schema: str) -> str:
    """
    Inject PostgreSQL search_path into database URL for non-public schemas.

    Handles both URLs with and without existing query parameters:
      postgresql://...         → postgresql://...?options=-csearch_path%3Dlibrary
      postgresql://...?ssl=... → postgresql://...?ssl=...&options=-csearch_path%3Dlibrary

    Args:
        base_url:  Raw DATABASE_URL from config
        pg_schema: Target PostgreSQL schema name

    Returns:
        URL string with search_path injected, or original URL if schema is public
    """
    if pg_schema == "public":
        return base_url
    connector = "&" if "?" in base_url else "?"
    return f"{base_url}{connector}options=-csearch_path%3D{pg_schema}"


def _build_agents(schema_name: str) -> CorrectionAgent:
    """
    Build all agents for a schema profile and store in cache.
    Called only on cache miss — never called twice for the same schema_name.

    Build order matters:
      1. SchemaLinker  — needs collection_name + pg_schema
      2. SQLGenerator  — stateless, no dependencies
      3. CriticAgent   — stateless, no dependencies
      4. ExecutorAgent — needs db_url with search_path injected
      5. CorrectionAgent — receives all four above as pre-built objects
    """
    print(f"[Orchestrator] Building agents for schema: {schema_name}")
    logger.info(f"[Orchestrator] Building agents for schema: {schema_name}")

    profile    = SCHEMA_PROFILES[schema_name]
    pg_schema  = profile["pg_schema"]
    db_url     = _build_db_url_with_schema(profile["db_url"], pg_schema)

    schema_linker = SchemaLinker(
        collection_name=profile["collection_name"],
        pg_schema=pg_schema,
    )
    sql_generator = SQLGenerator()
    critic        = CriticAgent()
    executor      = ExecutorAgent(db_url)

    agent = CorrectionAgent(
        schema_linker=schema_linker,
        sql_generator=sql_generator,
        critic=critic,
        executor=executor,
        max_attempts=3,
    )

    _agent_cache[schema_name] = agent
    logger.info(f"[Orchestrator] Agents cached for schema: {schema_name}")
    return agent


def _get_agent(schema_name: str) -> CorrectionAgent:
    """Return cached agent or build on first call."""
    if schema_name in _agent_cache:
        print(f"[Orchestrator] Using cached agents for schema: {schema_name}")
        logger.info(f"[Orchestrator] Using cached agents for schema: {schema_name}")
        return _agent_cache[schema_name]
    return _build_agents(schema_name)


def _serialize_rows(rows) -> Optional[list]:
    """
    Safely convert SQLAlchemy Row objects to plain dicts for JSON serialisation.
    Returns None if rows is None.
    """
    if rows is None:
        return None
    out = []
    for r in rows:
        try:
            if hasattr(r, "mapping"):
                out.append(dict(r.mapping))
            elif isinstance(r, dict):
                out.append(r)
            else:
                out.append(list(r))
        except Exception:
            out.append(str(r))
    return out


# ── Public entrypoint ─────────────────────────────────────────────────────────

def run_query(
    question: str,
    schema_name: str = DEFAULT_SCHEMA,
    max_attempts: int = 3,
) -> dict:
    """
    Run a natural language question through the full Text-to-SQL pipeline.

    This is the single entrypoint used by:
      - FastAPI route handlers (POST /query)
      - Evaluation scripts (run_full_eval.py, run_library_eval.py)
      - CLI tools and tests

    Args:
        question:     Natural language query string
        schema_name:  Schema profile name (must exist in SCHEMA_PROFILES)
        max_attempts: Accepted for API compatibility. Currently ignored.
                      Agent is cached with max_attempts=3 at creation time.

    Returns:
        Flat dict with exactly 11 fields:
          sql                   — final generated SQL (None if pipeline failed)
          success               — True if execution succeeded without error
          attempts              — total correction loop iterations taken
          first_attempt_success — True if success on attempt 1
          latency_ms            — wall-clock ms from call entry to return
          schema_tables_used    — tables SchemaLinker provided as LLM context
          correction_applied    — True if attempts > 1
          rows                  — query result rows as list[dict] (None on failure)
          row_count             — len(rows), 0 on failure
          error_type            — structured error class (None on success)
          error_message         — raw PostgreSQL error string (None on success)

    Raises:
        ValueError: If schema_name not in SCHEMA_PROFILES
    """
    if schema_name not in SCHEMA_PROFILES:
        raise ValueError(
            f"Unknown schema '{schema_name}'. "
            f"Available profiles: {list(SCHEMA_PROFILES.keys())}"
        )

    agent = _get_agent(schema_name)

    # ── Run pipeline ──────────────────────────────────────────────────────────
    # Only execute_with_retry() is called on the agent.
    # Sub-agents (SchemaLinker, SQLGenerator, CriticAgent, ExecutorAgent)
    # are never called directly from here.
    start  = time.monotonic()
    result = agent.execute_with_retry(question)
    latency_ms = round((time.monotonic() - start) * 1000, 2)

    # ── Map CorrectionResult → flat dict ──────────────────────────────────────
    er         = result.execution_result or {}
    rows       = _serialize_rows(er.get("data")) if result.success else None
    row_count  = len(rows) if rows is not None else 0

    return {
        "sql":                   result.final_sql,
        "success":               result.success,
        "attempts":              result.attempts,
        "first_attempt_success": result.success and result.attempts == 1,
        "latency_ms":            latency_ms,
        "schema_tables_used":    result.schema_tables_used or [],
        "correction_applied":    result.attempts > 1,
        "rows":                  rows,
        "row_count":             row_count,
        "error_type":            er.get("error_type"),
        "error_message":         er.get("error_message"),
    }
