"""
Library Schema Evaluation Runner — Day 7
Runs all 15 library_eval.json queries through the full CorrectionAgent pipeline.
Output: backend/evaluation_results/day7_library_results.json
"""

import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.config import settings, SCHEMA_PROFILES
from app.agents.schema_linker import SchemaLinker
from app.agents.sql_generator import SQLGenerator
from app.agents.critic import CriticAgent
from app.agents.executor import ExecutorAgent
from app.agents.self_correction import CorrectionAgent
from app.evaluation.metrics import (
    execution_success_rate,
    first_vs_final_rate,
    retry_distribution,
    hallucination_rate,
    adversarial_results,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────
SCHEMA_NAME   = "library"
DATASET_FILE  = Path(__file__).parent.parent / "app/evaluation/datasets/library_eval.json"
OUTPUT_FILE   = Path(__file__).parent.parent / "evaluation_results/day7_library_results.json"

VALID_TABLES  = {"books", "members", "loans", "fines"}


def build_db_url_with_schema(base_url: str, pg_schema: str) -> str:
    """Append PostgreSQL search_path to a database URL so the executor
    resolves unqualified table names (e.g. 'books') in the right schema."""
    if pg_schema == "public":
        return base_url
    connector = "&" if "?" in base_url else "?"
    return f"{base_url}{connector}options=-csearch_path%3D{pg_schema}"


def load_dataset() -> list:
    if not DATASET_FILE.exists():
        print(f"ERROR: Dataset not found at {DATASET_FILE}")
        sys.exit(1)

    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)

    loaded = [c for c in cases if not c.get("skip")]
    skipped = len(cases) - len(loaded)

    print(f"  {'library_eval.json':<35} {len(loaded)} cases")
    if skipped:
        print(f"  (skipped {skipped} entries with skip=true)")

    return loaded


def get_schema_tables(schema_linker: SchemaLinker, question: str) -> list:
    try:
        if hasattr(schema_linker, "link_schema"):
            schema = schema_linker.link_schema(question)
        else:
            return []

        if isinstance(schema, dict):
            if "schema_dict" in schema and isinstance(schema["schema_dict"], dict):
                return list(schema["schema_dict"].keys())
            if "tables" in schema and isinstance(schema["tables"], list):
                return [t.lower() for t in schema["tables"]]
        return []
    except Exception as e:
        logger.warning(f"SchemaLinker failed: {e}")
        return []


def serialize_rows(rows):
    if rows is None:
        return None
    out = []
    for r in rows:
        try:
            out.append(dict(r.mapping) if hasattr(r, "mapping") else r if isinstance(r, dict) else list(r))
        except Exception:
            out.append(str(r))
    return out


def run_single_test(
    correction_agent: CorrectionAgent,
    schema_linker: SchemaLinker,
    test_case: dict,
    idx: int,
    total: int,
) -> dict:
    test_id  = test_case.get("id", f"test_{idx}")
    question = test_case["question"]
    complexity = test_case.get("complexity", "unknown")
    category   = test_case.get("category", "unknown")

    schema_tables_used = get_schema_tables(schema_linker, question)

    try:
        t0 = time.time()
        result = correction_agent.execute_with_retry(question)
        latency_ms = round((time.time() - t0) * 1000, 2)

        er = result.execution_result
        if isinstance(er, dict) and "data" in er:
            er_data = serialize_rows(er["data"])
        else:
            er_data = None

        error_type    = None
        error_message = None
        if isinstance(er, dict):
            error_type    = er.get("error_type")
            error_message = er.get("error_message")

        first_attempt_success = result.success and result.attempts == 1

        if result.success:
            tag = "1st" if first_attempt_success else f"corrected@{result.attempts}"
            print(f"  [{idx:>2}/{total}] {test_id:<20} ✓ {tag:<15} {latency_ms:>7.0f}ms")
        else:
            print(f"  [{idx:>2}/{total}] {test_id:<20} ✗ FAILED({result.attempts})      {latency_ms:>7.0f}ms  {error_type or ''}")

        return {
            "id":                   test_id,
            "question":             question,
            "complexity":           complexity,
            "category":             category,
            "should_be_valid":      test_case.get("should_be_valid", True),
            "expected_issue":       test_case.get("expected_issue", None),
            "sql":                  result.final_sql,
            "success":              result.success,
            "attempts":             result.attempts,
            "first_attempt_success": first_attempt_success,
            "latency_ms":           latency_ms,
            "schema_tables_used":   schema_tables_used,
            "error_type":           error_type,
            "error_message":        error_message,
            "correction_applied":   result.attempts > 1,
        }

    except Exception as e:
        logger.error(f"Runtime error on {test_id}: {e}")
        print(f"  [{idx:>2}/{total}] {test_id:<20} ✗ RUNTIME ERROR: {e}")
        return {
            "id":                   test_id,
            "question":             question,
            "complexity":           complexity,
            "category":             category,
            "should_be_valid":      test_case.get("should_be_valid", True),
            "expected_issue":       test_case.get("expected_issue", None),
            "sql":                  None,
            "success":              False,
            "attempts":             1,
            "first_attempt_success": False,
            "latency_ms":           0.0,
            "schema_tables_used":   schema_tables_used,
            "error_type":           "runtime_error",
            "error_message":        str(e),
            "correction_applied":   False,
        }


def print_summary(results: list) -> None:
    print("\n" + "=" * 70)
    print("METRICS SUMMARY")
    print("=" * 70)

    ex  = execution_success_rate(results)
    fv  = first_vs_final_rate(results)
    rt  = retry_distribution(results)
    hl  = hallucination_rate(results, VALID_TABLES)

    print(f"\n  execution_success_rate")
    print(f"    success rate    : {ex['rate']*100:.1f}%  ({ex['success']}/{ex['total']})")

    print(f"\n  first_vs_final_rate")
    print(f"    first attempt   : {fv['first_attempt_rate']*100:.1f}%  ({fv['first_attempt_count']} tests)")
    print(f"    correction eff  : {fv['correction_effectiveness']*100:.1f}%  ({fv['corrected_count']} fixed)")
    print(f"    final failures  : {fv['final_failures']}")
    print(f"    overall rate    : {fv['overall_success_rate']*100:.1f}%")

    print(f"\n  retry_distribution")
    print(f"    avg attempts    : {rt['avg_attempts']:.2f}")
    print(f"    distribution    : {rt['distribution']}")

    print(f"\n  hallucination_rate")
    print(f"    rate            : {hl['hallucination_rate']*100:.1f}%  ({hl['hallucinated_count']} cases)")
    if hl["cases"]:
        for c in hl["cases"]:
            print(f"      {c['id']}  phantom: {c['phantom_tables']}")

    # ── Per-complexity breakdown ─────────────────────────────────────
    print(f"\n  complexity_breakdown")
    for level in ["easy", "medium", "hard"]:
        subset = [r for r in results if r.get("complexity") == level]
        if not subset:
            continue
        passed = sum(1 for r in subset if r.get("success"))
        print(f"    {level:<8}: {passed}/{len(subset)}  ({passed/len(subset)*100:.0f}%)")


def main():
    print("=" * 70)
    print("QUERYPILOT — DAY 7 LIBRARY EVALUATION")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")

    # ── Load profile ─────────────────────────────────────────────────
    profile         = SCHEMA_PROFILES[SCHEMA_NAME]
    pg_schema       = profile["pg_schema"]
    collection_name = profile["collection_name"]
    db_url          = build_db_url_with_schema(profile["db_url"], pg_schema)

    print(f"\nSchema profile : {SCHEMA_NAME}")
    print(f"pg_schema      : {pg_schema}")
    print(f"collection     : {collection_name}")

    # ── Load dataset ─────────────────────────────────────────────────
    print("\nLoading dataset...")
    test_cases = load_dataset()
    print(f"Total to run   : {len(test_cases)}")

    if not test_cases:
        print("ERROR: No test cases loaded.")
        sys.exit(1)

    # ── Init agents ──────────────────────────────────────────────────
    schema_linker    = SchemaLinker(collection_name=collection_name, pg_schema=pg_schema)
    sql_generator    = SQLGenerator()
    critic           = CriticAgent()
    executor         = ExecutorAgent(db_url)
    correction_agent = CorrectionAgent(
        schema_linker=schema_linker,
        sql_generator=sql_generator,
        critic=critic,
        executor=executor,
        max_attempts=3,
    )
    print("All agents initialized\n")

    # ── Run tests ────────────────────────────────────────────────────
    print("=" * 70)
    print("RUNNING TESTS")
    print("=" * 70)

    results = []
    for idx, test_case in enumerate(test_cases, 1):
        r = run_single_test(correction_agent, schema_linker, test_case, idx, len(test_cases))
        results.append(r)

    # ── Save results ─────────────────────────────────────────────────
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp":    datetime.now().isoformat(),
        "schema":       SCHEMA_NAME,
        "total_tests":  len(results),
        "results":      results,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nSaved to {OUTPUT_FILE}")

    # ── Print metrics ────────────────────────────────────────────────
    print_summary(results)

    print(f"\nFinished: {datetime.now().isoformat()}")
    print("=" * 70)

    ex = execution_success_rate(results)
    sys.exit(0 if ex["rate"] >= 0.70 else 1)


if __name__ == "__main__":
    main()
