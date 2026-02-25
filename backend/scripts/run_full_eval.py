"""
Day 6 Full Evaluation Runner
Loads all 8 evaluation datasets, runs the Day-5 pipeline
(LangGraph + CorrectionAgent), captures structured results,
saves to day6_full_results.json, then prints metrics.

Refactored (Day 8): Agent wiring moved to orchestrator.
run_single_test() now calls orchestrator.run_query() directly.
"""

import sys
import json
import logging
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.agents.orchestrator import run_query
from app.config import DEFAULT_SCHEMA
from app.evaluation.metrics import (
    execution_success_rate,
    first_vs_final_rate,
    retry_distribution,
    hallucination_rate,
    adversarial_results,
)

logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ─── Config ────────────────────────────────────────────────────────────────

DATASET_DIR = Path("app/evaluation/datasets")
DATASETS = [
    "structured_easy.json",
    "structured_medium.json",
    "structured_hard.json",
    "custom_product.json",
    "custom_customer.json",
    "custom_revenue.json",
    "edge_cases.json",
    "adversarial_tests.json",
]
OUTPUT_FILE = Path("evaluation_results/day6_full_results.json")

VALID_TABLES = {
    "products", "customers", "orders", "order_items",
    "categories", "payments", "reviews"
}


# ─── Dataset loading ───────────────────────────────────────────────────────

def load_all_datasets() -> list:
    all_cases = []
    skipped = 0
    for fname in DATASETS:
        path = DATASET_DIR / fname
        if not path.exists():
            print(f"  ⚠  Missing: {path} — skipped")
            continue
        with open(path, 'r', encoding='utf-8') as f:
            cases = json.load(f)
        loaded = 0
        for case in cases:
            if case.get("skip") is True:
                skipped += 1
                continue
            all_cases.append(case)
            loaded += 1
        print(f"  ✓  {fname:<35}  {loaded} cases")
    print(f"  →  {skipped} entries skipped (skip=true)")
    return all_cases


# ─── Single test runner ────────────────────────────────────────────────────

def run_single_test(
    test_case: dict,
    idx: int,
    total: int,
    schema_name: str = DEFAULT_SCHEMA,
) -> dict:
    test_id    = test_case.get("id", f"test_{idx}")
    question   = test_case["question"]
    complexity = test_case.get("complexity", "unknown")
    category   = test_case.get("category", "unknown")

    print(f"  [{idx:>3}/{total}]  {test_id:<20}  {question[:55]}...")

    try:
        result = run_query(question, schema_name=schema_name)

        if result["success"]:
            tag = "1st" if result["first_attempt_success"] else f"corrected×{result['attempts']}"
            print(f"           ✓  {tag}  [{result['latency_ms']:.0f}ms]")
        else:
            print(f"           ✗  FAILED×{result['attempts']}  [{result['latency_ms']:.0f}ms]  {result['error_type'] or ''}")

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
        print(f"           ✗  ERROR: {e}")
        return {
            "id":                    test_id,
            "question":              question,
            "complexity":            complexity,
            "category":              category,
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


# ─── Summary printer ───────────────────────────────────────────────────────

def print_summary(results: list):
    print("\n" + "=" * 70)
    print("METRICS SUMMARY")
    print("=" * 70)

    ex  = execution_success_rate(results)
    fv  = first_vs_final_rate(results)
    rt  = retry_distribution(results)
    hl  = hallucination_rate(results, VALID_TABLES)
    adv = adversarial_results(results, VALID_TABLES)

    print(f"\n  execution_success_rate (core only, adversarial excluded)")
    print(f"    success rate    : {ex['rate']*100:.1f}%  ({ex['success']}/{ex['total']})")
    print(f"    adversarial out : {ex['adversarial_excluded']}")

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
    if hl['cases']:
        for c in hl['cases']:
            print(f"    ↳ {c['id']}: phantom={c['phantom_tables']}")

    print(f"\n  adversarial_results  (correct handling = fail+typed error+no phantom)")
    print(f"    total            : {adv['total']}")
    print(f"    correctly handled: {adv['correctly_handled']}  ({adv['handling_rate']*100:.1f}%)")
    if adv['failed_details']:
        print(f"    incorrectly handled:")
        for d in adv['failed_details']:
            print(f"      ↳ {d['id']}: should_valid={d['should_be_valid']} got={d['actual_success']} expected={d['expected_issue']} error={d['error_type']}")

    print()


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("QUERYPILOT — DAY 6 FULL EVALUATION")
    print("=" * 70)
    print(f"Started : {datetime.now().isoformat()}\n")

    # Load datasets
    print("Loading datasets...")
    test_cases = load_all_datasets()
    print(f"\nTotal to run: {len(test_cases)}\n")
    if not test_cases:
        print("ERROR: No test cases loaded. Check DATASET_DIR paths.")
        sys.exit(1)

    # Agents are built on first run_query() call via orchestrator cache.
    # No initialization needed here.
    print("✓ Orchestrator ready (agents build on first query)\n")

    # Run tests
    print("=" * 70)
    print("RUNNING TESTS")
    print("=" * 70)

    results = []
    for idx, test_case in enumerate(test_cases, 1):
        r = run_single_test(test_case, idx, len(test_cases))
        results.append(r)

    # Save raw results
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp":   datetime.now().isoformat(),
        "total_tests": len(results),
        "results":     results,
    }
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n💾  Saved to: {OUTPUT_FILE}")

    # Print metrics
    print_summary(results)

    print(f"Finished: {datetime.now().isoformat()}")
    print("=" * 70)

    ex = execution_success_rate(results)
    sys.exit(0 if ex['rate'] >= 0.85 else 1)


if __name__ == "__main__":
    main()
