"""
Day 4 Evaluation: Full Pipeline with Executor Agent

Tests the complete QueryPilot pipeline:
Question → Schema Linker → SQL Generator → Critic → Executor

Success criteria:
1. Execution success rate = 100% on Critic-validated queries
2. Execution latency <5s for valid queries
3. Error classification working for invalid queries
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, List

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.agents.schema_linker import SchemaLinker
from app.agents.sql_generator import SQLGenerator
from app.agents.critic import CriticAgent
from app.agents.executor import ExecutorAgent  # NEW for Day 4
from app.config import settings


def run_day4_evaluation(
    dataset_path: str = None,
    output_path: str = None,
    mode: str = "normal"
):
    """
    Run full pipeline evaluation with Executor Agent
    
    Args:
        dataset_path: Path to evaluation dataset (default: day2_baseline.json)
        output_path: Path to save results (default: day4_executor_results.json)
        mode: "normal" for Day 2 baseline, "adversarial" for Day 3 adversarial tests
    """
    
    # Default paths
    if dataset_path is None:
        if mode == "adversarial":
            dataset_path = backend_path / "app" / "evaluation" / "datasets" / "day3_critic_adversarial.json"
        else:
            dataset_path = backend_path / "app" / "evaluation" / "datasets" / "day2_baseline.json"
    
    if output_path is None:
        output_path = backend_path / "evaluation_results" / f"day4_{mode}_results.json"
    
    print("\n" + "=" * 80)
    print("DAY 4: FULL PIPELINE EVALUATION WITH EXECUTOR AGENT")
    print("=" * 80)
    print(f"Dataset: {dataset_path}")
    print(f"Output: {output_path}")
    print(f"Mode: {mode}")
    print("=" * 80)
    
    # Load test dataset
    print("\nLoading test dataset...")
    with open(dataset_path) as f:
        test_cases = json.load(f)
    print(f"Loaded {len(test_cases)} test cases\n")
    
    # Initialize all agents
    print("Initializing agents...")
    print("  [1/4] Schema Linker...")
    schema_linker = SchemaLinker()
    
    print("  [2/4] SQL Generator...")
    sql_generator = SQLGenerator()
    
    print("  [3/4] Critic Agent...")
    critic = CriticAgent()
    
    print("  [4/4] Executor Agent...")  # NEW
    executor = ExecutorAgent(database_url=settings.DATABASE_URL)
    
    print("All agents initialized ✓\n")
    
    # Results storage
    results = []
    
    # Counters
    total = len(test_cases)
    schema_success = 0
    generation_success = 0
    validation_success = 0
    execution_success = 0  # NEW
    execution_failed = 0   # NEW
    critic_blocked = 0     # NEW
    
    # Process each test case
    start_time = time.time()
    
    for idx, test_case in enumerate(test_cases, 1):
        question = test_case['question']
        test_id = test_case.get('id', f'q_{idx:03d}')
        
        print(f"\n[{idx}/{total}] {test_id}: {question}")
        print("-" * 80)
        
        result = {
            'id': test_id,
            'question': question,
            'expected_query': test_case.get('expected_query', ''),
            'difficulty': test_case.get('difficulty', 'unknown'),
            'category': test_case.get('category', 'unknown')
        }
        
        # Step 1: Schema Linking
        try:
            print("  [1/4] Schema Linking...", end=" ")
            filtered_schema = schema_linker.link_schema(question)
            relevant_tables = list(filtered_schema.keys())
            print(f"✓ Found {len(relevant_tables)} tables: {', '.join(relevant_tables)}")
            
            schema_success += 1
            result['schema_linking'] = {
                'success': True,
                'tables': relevant_tables,
                'table_count': len(relevant_tables)
            }
        except Exception as e:
            print(f"✗ FAILED: {str(e)}")
            result['schema_linking'] = {
                'success': False,
                'error': str(e)
            }
            results.append(result)
            continue
        
        # Step 2: SQL Generation
        try:
            print("  [2/4] SQL Generation...", end=" ")
            generated_sql = sql_generator.generate(question, filtered_schema)
            print(f"✓")
            print(f"        SQL: {generated_sql[:80]}...")
            
            generation_success += 1
            result['generation'] = {
                'success': True,
                'sql': generated_sql
            }
        except Exception as e:
            print(f"✗ FAILED: {str(e)}")
            result['generation'] = {
                'success': False,
                'error': str(e)
            }
            results.append(result)
            continue
        
        # Step 3: Critic Validation
        try:
            print("  [3/4] Critic Validation...", end=" ")
            validation_result = critic.validate(generated_sql, filtered_schema, question)
            
            if validation_result.is_valid:
                print(f"✓ VALID (confidence: {validation_result.confidence:.2f})")
                validation_success += 1
                result['validation'] = {
                    'is_valid': True,
                    'confidence': validation_result.confidence,
                    'issues': validation_result.issues
                }
            else:
                print(f"✗ INVALID (confidence: {validation_result.confidence:.2f})")
                print(f"        Issues: {', '.join(validation_result.issues[:2])}")
                critic_blocked += 1
                result['validation'] = {
                    'is_valid': False,
                    'confidence': validation_result.confidence,
                    'issues': validation_result.issues
                }
                result['execution'] = {
                    'executed': False,
                    'reason': 'Blocked by Critic'
                }
                results.append(result)
                continue
        except Exception as e:
            print(f"✗ FAILED: {str(e)}")
            result['validation'] = {
                'success': False,
                'error': str(e)
            }
            results.append(result)
            continue
        
        # Step 4: Execution (NEW for Day 4)
        try:
            print("  [4/4] SQL Execution...", end=" ")
            
            # Execute with schema for error feedback
            execution_result = executor.execute(
                generated_sql,
                timeout_seconds=30,
                row_limit=1000,
                schema=filtered_schema  # Pass schema for helpful error feedback
            )
            
            if execution_result.success:
                print(f"✓ SUCCESS")
                print(f"        Rows: {execution_result.row_count}, "
                      f"Time: {execution_result.execution_time_ms:.1f}ms")
                
                execution_success += 1
                result['execution'] = {
                    'executed': True,
                    'success': True,
                    'row_count': execution_result.row_count,
                    'execution_time_ms': execution_result.execution_time_ms,
                    'sql_executed': execution_result.sql_executed
                }
            else:
                print(f"✗ FAILED: {execution_result.error_type}")
                print(f"        Feedback: {execution_result.error_feedback[:80]}...")
                
                execution_failed += 1
                result['execution'] = {
                    'executed': True,
                    'success': False,
                    'error_type': execution_result.error_type,
                    'error_message': execution_result.error_message,
                    'error_feedback': execution_result.error_feedback,
                    'error_details': execution_result.error_details,
                    'execution_time_ms': execution_result.execution_time_ms
                }
        
        except Exception as e:
            print(f"✗ EXCEPTION: {str(e)}")
            execution_failed += 1
            result['execution'] = {
                'executed': False,
                'success': False,
                'exception': str(e)
            }
        
        results.append(result)
    
    total_time = time.time() - start_time
    
    # Calculate metrics
    print("\n" + "=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    
    print(f"\n📊 Pipeline Stage Success Rates:")
    print(f"  Schema Linking:    {schema_success}/{total} ({schema_success/total*100:.1f}%)")
    print(f"  SQL Generation:    {generation_success}/{total} ({generation_success/total*100:.1f}%)")
    print(f"  Critic Validation: {validation_success}/{total} ({validation_success/total*100:.1f}%)")
    print(f"  SQL Execution:     {execution_success}/{validation_success} valid queries ({execution_success/validation_success*100 if validation_success > 0 else 0:.1f}%)")
    
    print(f"\n🎯 Day 4 Success Criteria:")
    
    # Criterion 1: Execution success rate on valid queries
    exec_success_rate = (execution_success / validation_success * 100) if validation_success > 0 else 0
    exec_criterion_met = exec_success_rate == 100.0
    print(f"  1. Execution success rate (valid queries): {exec_success_rate:.1f}% "
          f"{'✓ PASS' if exec_criterion_met else '✗ FAIL'} (target: 100%)")
    
    # Criterion 2: Average execution latency
    avg_latency = executor.get_metrics().avg_execution_time_ms
    latency_criterion_met = avg_latency < 5000  # 5 seconds
    print(f"  2. Average execution latency: {avg_latency:.1f}ms "
          f"{'✓ PASS' if latency_criterion_met else '✗ FAIL'} (target: <5000ms)")
    
    # Criterion 3: Error classification working
    error_distribution = executor.get_metrics().error_counts
    classification_working = len(error_distribution) > 0 or execution_failed == 0
    print(f"  3. Error classification: {'✓ WORKING' if classification_working else '✗ NOT WORKING'}")
    
    print(f"\n📈 Executor Metrics:")
    print(f"  Total queries executed: {executor.metrics.total_queries}")
    print(f"  Successful: {executor.metrics.successful_queries}")
    print(f"  Failed: {executor.metrics.failed_queries}")
    print(f"  Avg execution time: {executor.metrics.avg_execution_time_ms:.1f}ms")
    print(f"  Min execution time: {executor.metrics.min_execution_time_ms:.1f}ms")
    print(f"  Max execution time: {executor.metrics.max_execution_time_ms:.1f}ms")
    
    if error_distribution:
        print(f"\n❌ Error Distribution:")
        for error_type, count in sorted(error_distribution.items(), key=lambda x: x[1], reverse=True):
            print(f"  {error_type}: {count}")
    
    print(f"\n⏱️  Total evaluation time: {total_time:.1f}s")
    
    # Overall pass/fail
    all_criteria_met = exec_criterion_met and latency_criterion_met and classification_working
    
    print("\n" + "=" * 80)
    if all_criteria_met:
        print("✓ DAY 4 EVALUATION PASSED - All criteria met!")
    else:
        print("✗ DAY 4 EVALUATION FAILED - Some criteria not met")
    print("=" * 80)
    
    # Save results
    output_path.parent.mkdir(exist_ok=True)
    
    summary = {
        'total_test_cases': total,
        'schema_linking_success': schema_success,
        'generation_success': generation_success,
        'validation_success': validation_success,
        'execution_success': execution_success,
        'execution_failed': execution_failed,
        'critic_blocked': critic_blocked,
        'execution_success_rate': exec_success_rate,
        'avg_execution_latency_ms': avg_latency,
        'total_time_seconds': total_time,
        'criteria_met': {
            'execution_success_100%': exec_criterion_met,
            'latency_under_5s': latency_criterion_met,
            'error_classification_working': classification_working,
            'all_passed': all_criteria_met
        },
        'executor_metrics': {
            'total_queries': executor.metrics.total_queries,
            'successful_queries': executor.metrics.successful_queries,
            'failed_queries': executor.metrics.failed_queries,
            'avg_execution_time_ms': executor.metrics.avg_execution_time_ms,
            'max_execution_time_ms': executor.metrics.max_execution_time_ms,
            'min_execution_time_ms': executor.metrics.min_execution_time_ms,
            'error_distribution': executor.metrics.error_counts
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump({
            'summary': summary,
            'test_results': results
        }, f, indent=2)
    
    print(f"\n💾 Results saved to: {output_path}")
    
    # Cleanup
    executor.close()
    
    return all_criteria_met


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run Day 4 full pipeline evaluation")
    parser.add_argument(
        '--mode',
        choices=['normal', 'adversarial'],
        default='normal',
        help='Evaluation mode (default: normal)'
    )
    parser.add_argument(
        '--dataset',
        type=str,
        help='Path to test dataset (optional)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Path to output file (optional)'
    )
    
    args = parser.parse_args()
    
    try:
        success = run_day4_evaluation(
            dataset_path=args.dataset,
            output_path=args.output,
            mode=args.mode
        )
        sys.exit(0 if success else 1)
    
    except Exception as e:
        print(f"\n✗ EVALUATION ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
