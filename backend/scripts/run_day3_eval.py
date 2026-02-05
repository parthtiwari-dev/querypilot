"""
Day 3 Evaluation Script
Tests SQL Generator + Critic Agent validation on baseline + adversarial queries
"""
import json
import sys
from pathlib import Path
from typing import Dict, List
import time

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.schema_linker import SchemaLinker
from app.agents.sql_generator import SQLGenerator
from app.agents.critic import CriticAgent
from app.config import settings
import psycopg2


def load_test_dataset(dataset_path: str) -> List[Dict]:
    """Load evaluation dataset from JSON."""
    with open(dataset_path, 'r') as f:
        return json.load(f)


def test_sql_execution(sql: str, db_url: str) -> Dict:
    """
    Execute SQL and return result.
    
    Returns:
        {
            "success": bool,
            "error_type": str or None,
            "error_message": str or None,
            "execution_time_ms": float
        }
    """
    start_time = time.time()
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        cursor.execute(sql)
        
        try:
            results = cursor.fetchall()
            row_count = len(results)
        except:
            row_count = cursor.rowcount
        
        cursor.close()
        conn.close()
        
        execution_time = (time.time() - start_time) * 1000
        
        return {
            "success": True,
            "error_type": None,
            "error_message": None,
            "execution_time_ms": round(execution_time, 2),
            "row_count": row_count
        }
    
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        error_str = str(e)
        
        # Basic error classification
        error_type = "unknown"
        if "does not exist" in error_str.lower():
            if "column" in error_str.lower():
                error_type = "column_not_found"
            elif "table" in error_str.lower():
                error_type = "table_not_found"
        elif "syntax error" in error_str.lower():
            error_type = "syntax_error"
        elif "aggregate" in error_str.lower() or "group by" in error_str.lower():
            error_type = "aggregation_error"
        
        return {
            "success": False,
            "error_type": error_type,
            "error_message": error_str,
            "execution_time_ms": round(execution_time, 2)
        }


def run_evaluation(dataset_path: str, output_path: str, mode: str = "normal"):
    """
    Run full Day 3 evaluation with Critic Agent.
    
    Args:
        dataset_path: Path to test dataset JSON
        output_path: Path to save results
        mode: "normal" (with SQL generation) or "adversarial" (pre-written SQL)
    """
    
    print("=" * 60)
    print(f"DAY 3 CRITIC EVALUATION - {mode.upper()} MODE")
    print("=" * 60)
    print()
    
    # Initialize agents
    print("Initializing agents...")
    schema_linker = SchemaLinker()
    sql_generator = SQLGenerator(prompt_version="v1")
    critic = CriticAgent(confidence_threshold=0.7)
    
    # Load test dataset
    test_cases = load_test_dataset(dataset_path)
    print(f"Loaded {len(test_cases)} test questions\n")
    
    # Run evaluation
    results = []
    validation_times = []
    
    for i, test_case in enumerate(test_cases, 1):
        question = test_case["question"]
        complexity = test_case.get("complexity", "unknown")
        
        print(f"[{i}/{len(test_cases)}] {complexity.upper()}: {question}")
        
        try:
            # Step 1: Schema Linking (skip for adversarial mode if schema provided)
            if mode == "adversarial" and "schema" in test_case:
                filtered_schema = test_case["schema"]
                print(f"  → Schema: (provided)")
            else:
                start_time = time.time()
                filtered_schema = schema_linker.link_schema(question)
                schema_time = (time.time() - start_time) * 1000
                
                retrieved_tables = list(filtered_schema.keys())
                print(f"  → Schema Linker: {retrieved_tables}")
            
            # Step 2: SQL Generation (or use pre-written for adversarial)
            if mode == "adversarial" and "sql" in test_case:
                generated_sql = test_case["sql"]
                generation_time = 0
                print(f"  → SQL: (pre-written) {generated_sql[:60]}...")
            else:
                start_time = time.time()
                generated_sql = sql_generator.generate(question, filtered_schema)
                generation_time = (time.time() - start_time) * 1000
                print(f"  → SQL: {generated_sql[:60]}...")
            
            # Step 3: 🆕 CRITIC VALIDATION
            start_time = time.time()
            validation_result = critic.validate(generated_sql, filtered_schema, question)
            validation_time = (time.time() - start_time) * 1000
            validation_times.append(validation_time)
            
            if validation_result.is_valid:
                print(f"  → Critic: ✓ VALID (confidence: {validation_result.confidence:.2f})")
            else:
                print(f"  → Critic: ✗ INVALID (confidence: {validation_result.confidence:.2f})")
                print(f"    Issues: {', '.join(validation_result.issues[:2])}")
            
            # Step 4: Execution (only if valid)
            if validation_result.is_valid:
                execution_result = test_sql_execution(generated_sql, settings.DATABASE_URL)
                
                if execution_result["success"]:
                    print(f"  → Execution: ✓ SUCCESS ({execution_result['execution_time_ms']:.0f}ms, {execution_result.get('row_count', 0)} rows)")
                else:
                    print(f"  → Execution: ✗ FAILED: {execution_result['error_type']}")
                    print(f"    ⚠️ CRITIC MISSED THIS ERROR (False Negative)")
            else:
                # Skipped execution due to low confidence
                print(f"  → Execution: SKIPPED (blocked by Critic)")
                execution_result = {
                    "success": None,
                    "skipped": True,
                    "reason": "Failed validation"
                }
                
                # Check if this was a correct block (true positive) or false positive
                if mode == "adversarial":
                    expected_valid = test_case.get("should_be_valid", False)
                    if not expected_valid:
                        print(f"    ✓ CRITIC CORRECTLY BLOCKED BAD SQL")
            
            # Store result
            result_entry = {
                "id": test_case.get("id", f"q{i}"),
                "question": question,
                "complexity": complexity,
                "generated_sql": generated_sql,
                "validation": {
                    "confidence": validation_result.confidence,
                    "is_valid": validation_result.is_valid,
                    "issues": validation_result.issues,
                    "layer_results": validation_result.layer_results
                },
                "execution": execution_result,
                "validation_time_ms": round(validation_time, 2)
            }
            
            if mode == "normal":
                result_entry.update({
                    "ground_truth_tables": test_case.get("ground_truth_tables", []),
                    "retrieved_tables": list(filtered_schema.keys()),
                    "schema_linking_time_ms": round(schema_time, 2) if 'schema_time' in locals() else 0,
                    "sql_generation_time_ms": round(generation_time, 2)
                })
            else:  # adversarial
                result_entry.update({
                    "expected_issue": test_case.get("expected_issue"),
                    "should_be_valid": test_case.get("should_be_valid", False)
                })
            
            results.append(result_entry)
        
        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}")
            results.append({
                "id": test_case.get("id", f"q{i}"),
                "question": question,
                "complexity": complexity,
                "error": str(e),
                "validation": {"confidence": 0, "is_valid": False, "issues": [str(e)]}
            })
        
        print()
    
    # Calculate metrics
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    
    # Validation metrics
    total = len(results)
    valid_queries = sum(1 for r in results if r.get("validation", {}).get("is_valid"))
    invalid_queries = total - valid_queries
    avg_confidence = sum(r.get("validation", {}).get("confidence", 0) for r in results) / total if total > 0 else 0
    
    print(f"\n📊 Validation Results:")
    print(f"  Valid queries: {valid_queries}/{total} ({valid_queries/total*100:.1f}%)")
    print(f"  Invalid queries: {invalid_queries}/{total} ({invalid_queries/total*100:.1f}%)")
    print(f"  Average confidence: {avg_confidence:.2f}")
    print(f"  Average validation latency: {sum(validation_times)/len(validation_times):.1f}ms")
    
    # Execution metrics (only for valid queries)
    executed_queries = [r for r in results if r.get("execution", {}).get("success") is not None]
    if executed_queries:
        successful = sum(1 for r in executed_queries if r.get("execution", {}).get("success"))
        failed = len(executed_queries) - successful
        
        print(f"\n🔧 Execution Results (on valid queries only):")
        print(f"  Successful: {successful}/{len(executed_queries)} ({successful/len(executed_queries)*100:.1f}%)")
        print(f"  Failed: {failed}/{len(executed_queries)} ({failed/len(executed_queries)*100:.1f}%)")
        
        # False negatives: Valid by Critic but failed execution
        false_negatives = [r for r in results if r.get("validation", {}).get("is_valid") and not r.get("execution", {}).get("success")]
        if false_negatives:
            print(f"\n  ⚠️ False Negatives: {len(false_negatives)} (Critic missed these errors)")
    
    # Blocked queries
    blocked_queries = [r for r in results if not r.get("validation", {}).get("is_valid")]
    if blocked_queries:
        print(f"\n🛡️ Critic Performance:")
        print(f"  Queries blocked: {len(blocked_queries)}")
        
        if mode == "adversarial":
            # For adversarial, check detection rate
            should_be_blocked = [r for r in results if not r.get("should_be_valid", False)]
            correctly_blocked = [r for r in blocked_queries if not r.get("should_be_valid", False)]
            detection_rate = len(correctly_blocked) / len(should_be_blocked) * 100 if should_be_blocked else 0
            
            print(f"  Detection rate: {len(correctly_blocked)}/{len(should_be_blocked)} ({detection_rate:.1f}%)")
            
            # False positives in adversarial mode
            false_positives = [r for r in blocked_queries if r.get("should_be_valid", False)]
            if false_positives:
                print(f"  False positives: {len(false_positives)}")
        else:
            # For normal mode, estimate based on execution results
            # True positives: blocked AND would have failed
            # We can't know for sure, but we know 0 valid queries failed
            print(f"  Prevented execution errors: Check against known failures")
    
    # Error distribution
    all_issues = []
    for r in results:
        all_issues.extend(r.get("validation", {}).get("issues", []))
    
    if all_issues:
        print(f"\n📋 Issues Detected by Critic:")
        issue_types = {}
        for issue in all_issues:
            issue_type = issue.split(':')[0] if ':' in issue else issue[:30]
            issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
        
        for issue_type, count in sorted(issue_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {issue_type}: {count}")
    
    # Save results
    output_data = {
        "metadata": {
            "mode": mode,
            "total_queries": total,
            "valid_queries": valid_queries,
            "invalid_queries": invalid_queries,
            "avg_confidence": round(avg_confidence, 3),
            "avg_validation_latency_ms": round(sum(validation_times)/len(validation_times), 2) if validation_times else 0,
            "critic_threshold": 0.7
        },
        "results": results
    }
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n💾 Results saved to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run Day 3 Critic evaluation')
    parser.add_argument('--mode', choices=['normal', 'adversarial', 'both'], default='normal',
                        help='Evaluation mode (default: normal)')
    args = parser.parse_args()
    
    # Create output directory
    Path("evaluation_results").mkdir(parents=True, exist_ok=True)
    
    if args.mode in ['normal', 'both']:
        # Run on Day 2 baseline questions
        print("\n🔵 Running NORMAL evaluation (Day 2 baseline questions)...\n")
        run_evaluation(
            dataset_path="backend/app/evaluation/datasets/core_eval.json",
            output_path="backend/evaluation_results/day3_normal_results.json",
            mode="normal"
        )
    
    if args.mode in ['adversarial', 'both']:
        # Run on adversarial test set
        print("\n\n🔴 Running ADVERSARIAL evaluation (intentionally broken queries)...\n")
        run_evaluation(
            dataset_path="backend/app/evaluation/datasets/adversarial_tests.json",
            output_path="backend/evaluation_results/day3_adversarial_results.json",
            mode="adversarial"
        )
