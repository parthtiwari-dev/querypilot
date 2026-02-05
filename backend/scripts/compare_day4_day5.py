"""
Compare Day 4 (No Retry) vs Day 5 (With Self-Correction)

Shows the improvement gained from implementing the self-correction loop.

Day 4 has two modes:
- normal: Standard queries
- adversarial: Edge cases and stress tests

This script compares Day 5 with Day 4 normal mode by default (fair comparison).

Usage:
  python backend/scripts/compare_day4_day5.py                    # Uses day4 normal
  python backend/scripts/compare_day4_day5.py --mode adversarial # Uses day4 adversarial
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime


def load_results(filepath: str) -> dict:
    """Load evaluation results from JSON file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {filepath}")
        return None
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in: {filepath}")
        return None


def compare_results(day4_mode: str = 'normal'):
    """Compare Day 4 and Day 5 results

    Args:
        day4_mode: Which Day 4 results to compare ('normal' or 'adversarial')
    """

    print("=" * 80)
    print("DAY 4 (No Retry) vs DAY 5 (With Self-Correction)")
    print("=" * 80)

    # Load results - Day 4 filename depends on mode
    day4_filename = f"day4_{day4_mode}_results.json"
    day4_path = f"backend/evaluation_results/{day4_filename}"
    day5_path = "backend/evaluation_results/day5_correction_results.json"

    print(f"\nLoading results...")
    print(f"  Day 4 ({day4_mode}): {day4_path}")
    print(f"  Day 5: {day5_path}")

    day4 = load_results(day4_path)
    day5 = load_results(day5_path)

    if not day4:
        print(f"\n⚠️  Day 4 {day4_mode} results not found. Run day4 evaluation first:")
        print(f"    python backend/scripts/run_day4_eval.py --mode {day4_mode}")
        return None

    if not day5:
        print(f"\n⚠️  Day 5 results not found. Run day5 evaluation first:")
        print(f"    python backend/scripts/run_day5_eval.py")
        return None

    print(f"✓ Loaded both result files")

    # ========================================================================
    # COMPARISON METRICS
    # ========================================================================

    print("\n" + "=" * 80)
    print("COMPARISON")
    print("=" * 80)

    # Extract Day 4 metrics
    day4_summary = day4.get('summary', {})
    day4_total = day4_summary.get('total_test_cases', 0)
    day4_validation_success = day4_summary.get('validation_success', 0)
    day4_execution_success = day4_summary.get('execution_success', 0)

    # Day 4 success rate = executions that succeeded / total queries
    if day4_total > 0:
        day4_rate = (day4_execution_success / day4_total) * 100
    else:
        day4_rate = 0.0

    # Extract Day 5 metrics
    day5_summary = day5.get('summary', {})
    day5_total = day5_summary.get('first_attempt_success', 0) + day5_summary.get('corrected_success', 0) + day5_summary.get('final_failures', 0)
    day5_first_attempt = day5_summary.get('first_attempt_rate', 0) * 100
    day5_overall = day5_summary.get('overall_success_rate', 0) * 100
    day5_corrected = day5_summary.get('corrected_success', 0)
    day5_correction_effectiveness = day5_summary.get('correction_effectiveness', 0) * 100
    day5_first_success_count = day5_summary.get('first_attempt_success', 0)

    # Calculate improvement
    improvement = day5_overall - day4_rate

    # Display comparison
    print(f"\n📊 Success Rates:")
    print(f"  Day 4 (No Retry - {day4_mode} mode):")
    print(f"    Single attempt: {day4_rate:.1f}%")
    print(f"    ({day4_execution_success}/{day4_total} queries succeeded)")
    if day4_validation_success < day4_total:
        print(f"    Note: {day4_total - day4_validation_success} blocked by Critic")

    print(f"\n  Day 5 (With Self-Correction):")
    print(f"    First attempt: {day5_first_attempt:.1f}% ({day5_first_success_count} queries)")
    print(f"    After correction: {day5_overall:.1f}% ({day5_first_success_count + day5_corrected} queries)")
    print(f"    Queries fixed by retry: {day5_corrected}")

    print(f"\n📈 Improvement from Self-Correction:")
    if improvement > 0:
        print(f"  +{improvement:.1f}% improvement ({day4_rate:.1f}% → {day5_overall:.1f}%)")
        print(f"  {day5_corrected} additional queries succeeded via retry")
        print(f"  ✅ Self-correction is working!")
    elif improvement == 0:
        print(f"  No change ({day4_rate:.1f}% → {day5_overall:.1f}%)")
        print(f"  ⚠️  Correction not providing benefit")
    else:
        print(f"  {improvement:.1f}% decrease ({day4_rate:.1f}% → {day5_overall:.1f}%)")
        print(f"  ❌ Self-correction performing worse (check logs)")

    # Correction effectiveness
    print(f"\n🔧 Correction Effectiveness:")
    print(f"  Correction success rate: {day5_correction_effectiveness:.1f}%")
    failed_initially = day5_total - day5_first_success_count
    if failed_initially > 0:
        print(f"  (Of {failed_initially} queries that failed initially, {day5_corrected} were fixed)")

    # Avg attempts
    day5_avg_attempts = day5_summary.get('avg_attempts', 0)
    print(f"\n⏱️  Efficiency:")
    print(f"  Day 4: 1.00 attempts per query (no retry)")
    print(f"  Day 5: {day5_avg_attempts:.2f} attempts per query")
    if day5_avg_attempts < 1.5:
        print(f"  ✅ Efficient - most queries succeed on first attempt")
    elif day5_avg_attempts < 2.0:
        print(f"  ⚠️  Moderate - some retries needed")
    else:
        print(f"  ⚠️  High retry rate - may need generator improvements")

    # Category breakdown (if available)
    day5_categories = day5.get('category_breakdown', {})
    if day5_categories:
        print(f"\n📋 Day 5 Category Performance:")
        for category, stats in sorted(day5_categories.items()):
            total = stats.get('total', 0)
            first = stats.get('first_success', 0)
            corrected = stats.get('corrected', 0)
            failed = stats.get('failed', 0)

            if total > 0:
                overall_rate = ((first + corrected) / total) * 100
                correction_helped = corrected > 0

                status = "✓" if overall_rate >= 80 else "⚠️" if overall_rate >= 60 else "✗"

                print(f"  {status} {category:20s}: {first + corrected}/{total} ({overall_rate:.1f}%)")
                if correction_helped:
                    print(f"     └─ {corrected} fixed by correction")

    # Success criteria comparison
    print(f"\n✅ Success Criteria:")

    # Day 4 target depends on mode
    day4_target = 70 if day4_mode == 'normal' else 50  # Lower target for adversarial
    day4_passed = day4_rate >= day4_target
    day5_passed = day5.get('criteria', {}).get('all_passed', False)

    print(f"  Day 4 (>{day4_target}% for {day4_mode} mode): {'✓' if day4_passed else '✗'} ({day4_rate:.1f}%)")
    print(f"  Day 5 (>85% overall, >60% correction): {'✓' if day5_passed else '✗'}")

    # Overall assessment
    print("\n" + "=" * 80)
    print("ASSESSMENT")
    print("=" * 80)

    if improvement >= 10 and day5_passed:
        print("\n🎉 EXCELLENT: Self-correction significantly improved success rate!")
        print("   ✓ >10% improvement")
        print("   ✓ All Day 5 criteria met")
    elif improvement >= 5 and day5_passed:
        print("\n✅ GOOD: Self-correction improved success rate")
        print("   ✓ 5-10% improvement")
        print("   ✓ All Day 5 criteria met")
    elif improvement > 0:
        print("\n⚠️  MODERATE: Some improvement but criteria not fully met")
        print("   ✓ Improvement observed")
        print("   ✗ Some criteria not met - tuning recommended")
    elif improvement == 0:
        print("\n⚠️  NO IMPROVEMENT: Self-correction not helping")
        print("   ✗ No improvement from retry")
        print("   → Check correction strategies")
    else:
        print("\n❌ REGRESSION: Performance decreased with self-correction")
        print("   ✗ Negative improvement")
        print("   → Check for bugs in correction loop")

    print("\n" + "=" * 80)

    # Create summary report
    comparison_output = {
        "timestamp": datetime.now().isoformat(),
        "day4": {
            "mode": day4_mode,
            "filepath": day4_path,
            "success_rate": day4_rate,
            "successful_queries": day4_execution_success,
            "total_queries": day4_total,
            "validation_success": day4_validation_success
        },
        "day5": {
            "filepath": day5_path,
            "first_attempt_rate": day5_first_attempt,
            "overall_success_rate": day5_overall,
            "first_attempt_success": day5_first_success_count,
            "corrected_queries": day5_corrected,
            "correction_effectiveness": day5_correction_effectiveness,
            "avg_attempts": day5_avg_attempts,
            "total_queries": day5_total
        },
        "improvement": {
            "percentage_points": improvement,
            "queries_gained": day5_corrected,
            "is_improvement": improvement > 0
        },
        "criteria": {
            "day4_passed": day4_passed,
            "day5_passed": day5_passed
        }
    }

    # Save comparison
    output_filename = f"day4_{day4_mode}_vs_day5_comparison.json"
    output_path = f"backend/evaluation_results/{output_filename}"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(comparison_output, f, indent=2)

    print(f"\n💾 Comparison saved to: {output_path}")

    return comparison_output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare Day 4 (no retry) vs Day 5 (with self-correction)"
    )
    parser.add_argument(
        '--mode',
        choices=['normal', 'adversarial'],
        default='normal',
        help='Which Day 4 results to compare (default: normal)'
    )

    args = parser.parse_args()

    try:
        result = compare_results(day4_mode=args.mode)

        if result:
            # Exit with success if improvement observed
            improvement = result['improvement']['percentage_points']
            sys.exit(0 if improvement >= 0 else 1)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
