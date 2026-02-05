"""
Day 5 Evaluation Script - Self-Correction Testing

Tests the self-correction loop with 15 focused queries covering:
- Column errors (70%)
- Aggregation errors (20%)
- Timeout scenarios (test simplification)
- Non-retryable errors (should fail immediately)

Metrics are separated to show:
1. First attempt rate (generator quality WITHOUT correction)
2. Correction effectiveness (how much correction helps)
3. Overall success rate (after correction)
"""

import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from app.config import settings
from app.agents.schema_linker import SchemaLinker
from app.agents.sql_generator import SQLGenerator
from app.agents.critic import CriticAgent
from app.agents.executor import ExecutorAgent
from app.agents.self_correction import CorrectionAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_test_dataset(dataset_path: str) -> list:
    """Load test dataset from JSON file"""
    with open(dataset_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_correction_tests():
    """Run Day 5 correction tests with separated metrics"""

    print("=" * 80)
    print("DAY 5: SELF-CORRECTION EVALUATION")
    print("=" * 80)
    print(f"\nTimestamp: {datetime.now().isoformat()}")

    # Load test dataset
    dataset_path = "backend/app/evaluation/datasets/core_eval.json"
    test_cases = load_test_dataset(dataset_path)
    print(f"\nLoaded {len(test_cases)} test cases from {dataset_path}")

    # Initialize agents
    print("\nInitializing agents...")
    schema_linker = SchemaLinker()
    sql_generator = SQLGenerator()
    critic = CriticAgent()
    executor = ExecutorAgent(settings.DATABASE_URL)

    # Create CorrectionAgent with max_attempts=3
    correction_agent = CorrectionAgent(
        schema_linker=schema_linker,
        sql_generator=sql_generator,
        critic=critic,
        executor=executor,
        max_attempts=3
    )

    print("✓ All agents initialized")

    # Run tests
    print("\n" + "=" * 80)
    print("RUNNING TESTS")
    print("=" * 80)

    detailed_results = []

    for idx, test_case in enumerate(test_cases, 1):
        test_id = test_case.get('id', f"test_{idx}")
        question = test_case['question']

        # Optional fields (exist only in correction tests)
        expected_error = test_case.get('expected_first_error', "N/A")
        should_succeed = test_case.get('should_succeed', True)
        category = test_case.get('category', "core_eval")

        print(f"\n[{idx}/{len(test_cases)}] {test_id}: {question[:60]}...")
        print(f"    Expected error: {expected_error}")
        print(f"    Category: {category}")

        try:
            # Execute with retry
            result = correction_agent.execute_with_retry(question)

            # Store result
            test_result = {
                "test_id": test_id,
                "question": question,
                "category": category,
                "expected_error": expected_error,
                "should_succeed": should_succeed,
                "actual_success": result.success,
                "attempts": result.attempts,
                "was_corrected": result.was_corrected,
                "final_sql": result.final_sql,
                "execution_result": result.execution_result,
                "validation_issues": result.validation_issues
            }

            detailed_results.append(test_result)

            # Log result
            if result.success:
                if result.attempts == 1:
                    print(f"    ✓ SUCCESS on first attempt")
                else:
                    print(f"    ✓ SUCCESS after {result.attempts} attempts (CORRECTED!)")
            else:
                print(f"    ✗ FAILED after {result.attempts} attempts")
                if should_succeed:
                    print(f"    ⚠️  Expected to succeed but failed")

        except Exception as e:
            logger.error(f"Error running test {test_id}: {e}")
            test_result = {
                "test_id": test_id,
                "question": question,
                "category": category,
                "expected_error": expected_error,
                "should_succeed": should_succeed,
                "actual_success": False,
                "attempts": 0,
                "was_corrected": False,
                "error": str(e)
            }
            detailed_results.append(test_result)
            print(f"    ✗ ERROR: {e}")

    # ========================================================================
    # RESULTS SUMMARY WITH SEPARATED METRICS
    # ========================================================================

    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)

    # Get metrics from CorrectionAgent
    metrics = correction_agent.get_metrics()

    # DON'T HIDE WEAK GENERATION - Show first attempt separately
    print(f"\n📊 First Attempt (Generator Quality WITHOUT Correction):")
    print(f"  Success: {metrics.first_attempt_success}/{metrics.total_queries}")
    print(f"  Rate: {metrics.first_attempt_rate * 100:.1f}%")
    print(f"  (This shows SQLGenerator quality on its own)")

    # Show correction effectiveness
    print(f"\n🔧 Correction Effectiveness:")
    failed_initially = metrics.total_queries - metrics.first_attempt_success
    print(f"  Failed initially: {failed_initially}")
    print(f"  Fixed by correction: {metrics.corrected_success}")
    print(f"  Still failed: {metrics.final_failures}")
    if failed_initially > 0:
        correction_rate = metrics.correction_effectiveness * 100
        print(f"  Correction success rate: {correction_rate:.1f}%")
    else:
        print(f"  Correction success rate: N/A (no failures)")
    print(f"  (This shows how much self-correction helps)")

    # Show overall results
    print(f"\n📈 Overall (After Correction):")
    total_success = metrics.total_queries - metrics.final_failures
    print(f"  Total success: {total_success}/{metrics.total_queries}")
    print(f"  Overall rate: {metrics.overall_success_rate * 100:.1f}%")
    print(f"  Avg attempts: {metrics.avg_attempts:.2f}")

    # Success criteria
    print(f"\n✅ Success Criteria:")
    criterion_1 = metrics.first_attempt_rate > 0.3
    criterion_2 = metrics.correction_effectiveness > 0.6 if failed_initially > 0 else True
    criterion_3 = metrics.overall_success_rate > 0.85

    print(f"  1. First attempt >30%: {'✓' if criterion_1 else '✗'} ({metrics.first_attempt_rate * 100:.1f}%)")
    print(f"  2. Correction >60%: {'✓' if criterion_2 else '✗'} ({metrics.correction_effectiveness * 100:.1f}%)")
    print(f"  3. Overall >85%: {'✓' if criterion_3 else '✗'} ({metrics.overall_success_rate * 100:.1f}%)")

    all_passed = criterion_1 and criterion_2 and criterion_3
    if all_passed:
        print(f"\n🎉 ALL CRITERIA PASSED!")
    else:
        print(f"\n⚠️  Some criteria not met - may need tuning")

    # Breakdown by category
    print(f"\n📋 Breakdown by Category:")
    from collections import defaultdict
    category_stats = defaultdict(lambda: {"total": 0, "first_success": 0, "corrected": 0, "failed": 0})

    for result in detailed_results:
        cat = result['category']
        category_stats[cat]['total'] += 1

        if result['actual_success']:
            if result['attempts'] == 1:
                category_stats[cat]['first_success'] += 1
            else:
                category_stats[cat]['corrected'] += 1
        else:
            category_stats[cat]['failed'] += 1

    for category, stats in sorted(category_stats.items()):
        total = stats['total']
        first = stats['first_success']
        corrected = stats['corrected']
        failed = stats['failed']
        overall_rate = ((first + corrected) / total * 100) if total > 0 else 0

        print(f"  {category:20s}: {first + corrected}/{total} ({overall_rate:.1f}%) [First: {first}, Corrected: {corrected}, Failed: {failed}]")

    # Save results
    output_dir = Path("backend/evaluation_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    results_output = {
        "timestamp": datetime.now().isoformat(),
        "dataset": dataset_path,
        "total_tests": len(test_cases),
        "summary": {
            "first_attempt_success": metrics.first_attempt_success,
            "first_attempt_rate": metrics.first_attempt_rate,
            "corrected_success": metrics.corrected_success,
            "correction_effectiveness": metrics.correction_effectiveness,
            "final_failures": metrics.final_failures,
            "overall_success_rate": metrics.overall_success_rate,
            "avg_attempts": metrics.avg_attempts,
            "total_attempts": metrics.total_attempts
        },
        "criteria": {
            "first_attempt_above_30": criterion_1,
            "correction_above_60": criterion_2,
            "overall_above_85": criterion_3,
            "all_passed": all_passed
        },
        "category_breakdown": dict(category_stats),
        "detailed_results": detailed_results
    }

    output_file = output_dir / "day5_correction_results.json"
    # Ensure any SQLAlchemy Row or non-serializable objects are converted
    def _serialize_rows(rows):
        if rows is None:
            return None
        serial = []
        for r in rows:
            try:
                # SQLAlchemy Row has _mapping attribute
                if hasattr(r, '_mapping'):
                    serial.append(dict(r._mapping))
                elif isinstance(r, dict):
                    serial.append(r)
                else:
                    serial.append(list(r))
            except Exception:
                serial.append(str(r))
        return serial

    for res in detailed_results:
        er = res.get('execution_result')
        if er and 'data' in er:
            er['data'] = _serialize_rows(er['data'])

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results_output, f, indent=2, default=str)

    print(f"\n💾 Results saved to: {output_file}")

    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)

    return results_output


if __name__ == "__main__":
    try:
        results = run_correction_tests()

        # Exit with appropriate code
        if results['criteria']['all_passed']:
            print("\n✅ All success criteria met!")
            sys.exit(0)
        else:
            print("\n⚠️  Some criteria not met")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        sys.exit(1)
