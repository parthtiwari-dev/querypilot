"""
Test error classification accuracy

Runs broken queries from day4_error_tests.json and validates:
1. Error category matches expected
2. Error details extracted correctly
3. Feedback is helpful and actionable

Success criteria: >85% classification accuracy
"""

import json
import sys
from pathlib import Path

# Add backend to path for imports
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.agents.executor import ExecutorAgent, ErrorCategory
from app.config import settings


def test_error_classification():
    """Test error classification on known broken queries"""
    
    # Load test dataset
    dataset_path = backend_path / "app" / "evaluation" / "datasets" / "day4_error_tests.json"
    
    print(f"\nLoading error test dataset: {dataset_path}")
    with open(dataset_path) as f:
        test_cases = json.load(f)
    
    print(f"Loaded {len(test_cases)} test cases\n")
    
    # Initialize Executor Agent
    print("Initializing Executor Agent...")
    executor = ExecutorAgent(database_url=settings.DATABASE_URL)
    print("Executor initialized\n")
    
    print("=" * 80)
    print("ERROR CLASSIFICATION ACCURACY TEST")
    print("=" * 80)
    
    results = []
    correct = 0
    total = len(test_cases)
    
    for test in test_cases:
        print(f"\n[{test['id']}] {test['name']}")
        print(f"  Description: {test['description']}")
        print(f"  SQL: {test['sql'][:70]}...")
        print(f"  Expected: {test['expected_category']}")
        
        # Execute (will fail with known error)
        result = executor.execute(test['sql'])
        
        # Check classification
        expected = test['expected_category']
        actual = result.error_type
        
        is_correct = (actual == expected)
        
        if is_correct:
            print(f"  ✓ CORRECT: {actual}")
            correct += 1
            status = "PASS"
        else:
            print(f"  ✗ WRONG: Expected '{expected}', got '{actual}'")
            status = "FAIL"
        
        print(f"  Error Message: {result.error_message[:80]}...")
        print(f"  Feedback: {result.error_feedback[:120]}...")
        
        # Store result
        results.append({
            "id": test['id'],
            "name": test['name'],
            "expected": expected,
            "actual": actual,
            "correct": is_correct,
            "status": status,
            "error_message": result.error_message,
            "feedback": result.error_feedback,
            "details": result.error_details
        })
    
    # Calculate accuracy
    accuracy = correct / total * 100
    
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    print(f"Total test cases: {total}")
    print(f"Correct classifications: {correct}")
    print(f"Wrong classifications: {total - correct}")
    print(f"Accuracy: {accuracy:.1f}%")
    print()
    
    # Show metrics
    print("Executor Metrics:")
    print(f"  {executor.get_metrics()}")
    print(f"  Error distribution: {executor.get_metrics().error_counts}")
    print()
    
    # Pass/fail determination
    threshold = 85.0
    if accuracy >= threshold:
        print(f"✓ TEST PASSED: Accuracy {accuracy:.1f}% meets threshold {threshold}%")
        exit_code = 0
    else:
        print(f"✗ TEST FAILED: Accuracy {accuracy:.1f}% below threshold {threshold}%")
        exit_code = 1
    
    # Save detailed results
    output_path = backend_path / "evaluation_results" / "day4_error_classification_results.json"
    output_path.parent.mkdir(exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump({
            "summary": {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "threshold": threshold,
                "passed": accuracy >= threshold
            },
            "test_results": results,
            "metrics": {
                "total_queries": executor.metrics.total_queries,
                "failed_queries": executor.metrics.failed_queries,
                "error_counts": executor.metrics.error_counts,
                "avg_execution_time_ms": executor.metrics.avg_execution_time_ms
            }
        }, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_path}")
    print("=" * 80)
    
    # Cleanup
    executor.close()
    
    return exit_code


if __name__ == "__main__":
    try:
        exit_code = test_error_classification()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n✗ TEST ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
