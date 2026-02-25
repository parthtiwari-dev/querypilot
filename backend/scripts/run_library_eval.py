"""
Library Schema Evaluation Runner — Day 7
Runs all 15 library_eval.json queries through the full CorrectionAgent pipeline.
Output: backend/evaluation_results/day7_library_results.json

Refactored (Day 8): Agent wiring and search_path injection moved to orchestrator.
run_single_test() now calls orchestrator.run_query(schema_name="library") directly.
"""

import sys
import json
import logging
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.agents.orchestrator import run_query
from app.evaluation.metrics import (
    execution_success_rate,
    first_vs_final_rate,
    retry_distribution,
    hallucination_rate,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ── Config ───────────────────────────────────────────────────────────

SCHEMA_NAME  = "library"
DATASET_FILE = Path(__file__).parent.parent / "app/evaluation/datasets/library_eval.json"
OUTPUT_FILE  = Path(__file__).parent.parent / "evaluation_results/day7_library_results.json"

VALID_TABLES = {"books", "members", "loans", "fines"}


# ── Dataset loading ──────────────────────────────────────────────────

def load_dataset() -> list:
    if not DATASET_FILE.exists():
        print(f"ERROR: Dataset not found at {DATASET_FILE}")
        sys.exit(1)

    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)

    loaded  = [c for c in cases if not c.get("skip")]
    skipped = len(cases) - len(loaded)

    print(f"  {'library_eval.json':<35} {len(loaded)} cases")
    if skipped:
        print(f"  (skipped {skipped} entries with skip=true)")

    return loaded


# ── Single test runner ───────────────────────────────────────────────

def run_single_test(
    test_case: dict,
    idx: int,
    total: int,
    schema_name: str = SCHEMA_NAME,
) -> dict:
    test_id    = test_case.get("id", f"test_{idx}")
    question   = test_case["question"]
    complexity = test_case.get("complexity", "unknown")
    category   = test_case.get("category", "unknown")

    try:
        result = run_query(question, schema_name=schema_name)

        if result["success"]:
            tag = "1st" if result["first_attempt_success"] else f"corrected@{result['attempts']}"
            print(f"  [{idx:>2}/{total}] {test_id:<20} ✓ {tag:<15} {result['latency_ms']:>7.0f}ms")
        else:
            print(f"  [{idx:>2}/{total}] {test_id:<20} ✗ FAILED({result['attempts']})      {result['latency_ms']:>7.0f}ms  {result['error_type'] or ''}")

        return {
            "id":                    test_id,
            "question":              question,
            "complexity":            complexity,
            "category":              category,
            "should_be_valid":       test_case.get("should_be_valid", True),
            "expected_issue":        test_case.get("expected_issue", None),
            "sql":                   result["sql"],
            "success":               result["success"],
            "attempts":              result["attempts"],
            "first_attempt_success": result["first_attempt_success"],
            "latency_ms":            result["latency_ms"],
            "schema_tables_used":    result["schema_tables_used"],
            "error_type":            result["error_type"],
            "error_message":         result["error_message"],
            "correction_applied":    result["correction_applied"],
        }

    except Exception as e:
        logger.error(f"Runtime error on {test_id}: {e}")
        print(f"  [{idx:>2}/{total}] {test_id:<20} ✗ RUNTIME ERROR: {e}")
        return {
            "id":                    test_id,
            "question":              question,
            "complexity":            complexity,
            "category":              category,
            "should_be_valid":       test_case.get("should_be_valid", True),
            "expected_issue":        test_case.get("expected_issue", None),
            "sql":                   None,
            "success":               False,
            "attempts":              1,
            "first_attempt_success": False,
            "latency_ms":            0.0,
            "schema_tables_used":    [],
            "error_type":            "runtime_error",
            "error_message":         str(e),
            "correction_applied":    False,
        }


# ── Summary printer ──────────────────────────────────────────────────

def print_summary(results: list) -> None:
    print("\n" + "=" * 70)
    print("METRICS SUMMARY")
    print("=" * 70)

    ex = execution_success_rate(results)
    fv = first_vs_final_rate(results)
    rt = retry_distribution(results)
    hl = hallucination_rate(results, VALID_TABLES)

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

    print(f"\n  complexity_breakdown")
    for level in ["easy", "medium", "hard"]:
        subset = [r for r in results if r.get("complexity") == level]
        if not subset:
            continue
        passed = sum(1 for r in subset if r.get("success"))
        print(f"    {level:<8}: {passed}/{len(subset)}  ({passed/len(subset)*100:.0f}%)")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("QUERYPILOT — DAY 7 LIBRARY EVALUATION")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")

    # Load dataset
    print("\nLoading dataset...")
    test_cases = load_dataset()
    print(f"Total to run   : {len(test_cases)}")

    if not test_cases:
        print("ERROR: No test cases loaded.")
        sys.exit(1)

    # Agents are built on first run_query() call via orchestrator cache.
    # No initialization needed here.
    print("Orchestrator ready (agents build on first query)\n")

    # Run tests
    print("=" * 70)
    print("RUNNING TESTS")
    print("=" * 70)

    results = []
    for idx, test_case in enumerate(test_cases, 1):
        r = run_single_test(test_case, idx, len(test_cases))
        results.append(r)

    # Save results
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp":   datetime.now().isoformat(),
        "schema":      SCHEMA_NAME,
        "total_tests": len(results),
        "results":     results,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nSaved to {OUTPUT_FILE}")

    # Print metrics
    print_summary(results)

    print(f"\nFinished: {datetime.now().isoformat()}")
    print("=" * 70)

    ex = execution_success_rate(results)
    sys.exit(0 if ex["rate"] >= 0.70 else 1)


if __name__ == "__main__":
    main()
