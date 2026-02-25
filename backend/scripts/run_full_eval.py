# backend/scripts/run_full_eval.py
"""
Day 6 Full Evaluation Runner
Loads all 8 evaluation datasets, runs the Day-5 pipeline
(LangGraph + CorrectionAgent), captures structured results,
saves to day6_full_results.json, then prints metrics.
"""

import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.config import settings
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

# Valid ecommerce tables — used for hallucination detection
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


# ─── Schema tables helper ──────────────────────────────────────────────────

def get_schema_tables(schema_linker: SchemaLinker, question: str) -> list:
    try:
        if hasattr(schema_linker, 'get_relevant_schema'):
            schema = schema_linker.get_relevant_schema(question)
        elif hasattr(schema_linker, 'link_schema'):
            schema = schema_linker.link_schema(question)
        elif hasattr(schema_linker, 'get_schema'):
            schema = schema_linker.get_schema(question)
        else:
            return []

        if isinstance(schema, dict):
            # Shape: {"schema_dict": {"products": ..., "orders": ...}, "tables": [...]}
            if "schema_dict" in schema and isinstance(schema["schema_dict"], dict):
                return list(schema["schema_dict"].keys())
            if "tables" in schema and isinstance(schema["tables"], list):
                return [t.lower() for t in schema["tables"]]
            # Fallback: keys are table names directly
            return [k for k in schema.keys() if k not in ("schema_dict", "tables", "metadata")]
        if isinstance(schema, list):
            return [t.lower() for t in schema]
        return []
    except Exception as e:
        logger.warning(f"SchemaLinker failed: {e}")
        return []



# ─── Row serializer ────────────────────────────────────────────────────────

def _serialize_rows(rows):
    if rows is None:
        return None
    out = []
    for r in rows:
        try:
            out.append(dict(r._mapping) if hasattr(r, '_mapping') else (r if isinstance(r, dict) else list(r)))
        except Exception:
            out.append(str(r))
    return out


# ─── Single test runner ────────────────────────────────────────────────────

def run_single_test(
    correction_agent: CorrectionAgent,
    schema_linker: SchemaLinker,
    test_case: dict,
    idx: int,
    total: int
) -> dict:
    test_id = test_case.get("id", f"test_{idx}")
    question = test_case["question"]
    complexity = test_case.get("complexity", "unknown")
    category = test_case.get("category", "unknown")

    print(f"  [{idx:>3}/{total}]  {test_id:<20}  {question[:55]}...")

    # Get schema tables BEFORE running the pipeline
    schema_tables_used = get_schema_tables(schema_linker, question)

    try:
        t0 = time.time()
        result = correction_agent.execute_with_retry(question)
        latency_ms = round((time.time() - t0) * 1000, 2)

        # Serialize execution result rows
        er = result.execution_result
        if isinstance(er, dict) and "data" in er:
            er["data"] = _serialize_rows(er["data"])

        error_type = None
        error_message = None
        if isinstance(er, dict):
            error_type = er.get("error_type")
            error_message = er.get("error_message")

        first_attempt_success = result.success and result.attempts == 1

        # Console status
        if result.success:
            tag = "1st" if first_attempt_success else f"corrected×{result.attempts}"
            print(f"           ✓  {tag}  [{latency_ms:.0f}ms]")
        else:
            print(f"           ✗  FAILED×{result.attempts}  [{latency_ms:.0f}ms]  {error_type or ''}")

        return {
            "id": test_id,
            "question": question,
            "complexity": complexity,
            "category": category,
            "should_be_valid": test_case.get("should_be_valid", True),   # ← ADD
            "expected_issue": test_case.get("expected_issue", None),      # ← ADD
            "sql": result.final_sql,
            "success": result.success,
            "attempts": result.attempts,
            "first_attempt_success": first_attempt_success,
            "latency_ms": latency_ms,
            "schema_tables_used": schema_tables_used,
            "error_type": error_type,
            "error_message": error_message,
            "correction_applied": result.attempts > 1,
        }

    except Exception as e:
        logger.error(f"Runtime error on {test_id}: {e}")
        print(f"           ✗  ERROR: {e}")
        return {
            "id": test_id,
            "question": question,
            "complexity": complexity,
            "category": category,
            "sql": None,
            "success": False,
            "attempts": 1,
            "first_attempt_success": False,
            "latency_ms": 0.0,
            "schema_tables_used": schema_tables_used,
            "error_type": "runtime_error",
            "error_message": str(e),
            "correction_applied": False,
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
    print(f"    total           : {adv['total']}")
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

    # Init agents
    schema_linker   = SchemaLinker()
    sql_generator   = SQLGenerator()
    critic          = CriticAgent()
    executor        = ExecutorAgent(settings.DATABASE_URL)
    correction_agent = CorrectionAgent(
        schema_linker=schema_linker,
        sql_generator=sql_generator,
        critic=critic,
        executor=executor,
        max_attempts=3
    )
    print("✓ All agents initialized\n")

    # Run tests
    print("=" * 70)
    print("RUNNING TESTS")
    print("=" * 70)

    results = []
    for idx, test_case in enumerate(test_cases, 1):
        r = run_single_test(correction_agent, schema_linker, test_case, idx, len(test_cases))
        results.append(r)

    # Save raw results
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": len(results),
        "results": results
    }
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n💾  Saved to: {OUTPUT_FILE}")

    # Print metrics
    print_summary(results)

    print(f"Finished: {datetime.now().isoformat()}")
    print("=" * 70)

    # Exit code based on core success rate
    ex = execution_success_rate(results)
    sys.exit(0 if ex['rate'] >= 0.85 else 1)


if __name__ == "__main__":
    main()
