"""
Day 2 Evaluation Script
Tests SQL Generator on 20 baseline questions
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
        
        # Try to fetch results (will fail for non-SELECT queries)
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


def run_evaluation(dataset_path: str, output_path: str):
    """Run full Day 2 evaluation."""
    
    print("=" * 60)
    print("DAY 2 SQL GENERATOR - BASELINE EVALUATION")
    print("=" * 60)
    print()
    
    # Initialize agents
    print("Initializing agents...")
    schema_linker = SchemaLinker()
    sql_generator = SQLGenerator(prompt_version="v1")
    
    # Load test dataset
    test_cases = load_test_dataset(dataset_path)
    print(f"Loaded {len(test_cases)} test questions\n")
    
    # Run evaluation
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        question = test_case["question"]
        complexity = test_case.get("complexity", "unknown")
        
        print(f"[{i}/{len(test_cases)}] {complexity.upper()}: {question}")
        
        try:
            # Step 1: Schema Linking
            start_time = time.time()
            filtered_schema = schema_linker.link_schema(question)
            schema_time = (time.time() - start_time) * 1000
            
            retrieved_tables = list(filtered_schema.keys())
            print(f"  → Schema Linker: {retrieved_tables}")
            
            # Step 2: SQL Generation
            start_time = time.time()
            generated_sql = sql_generator.generate(question, filtered_schema)
            generation_time = (time.time() - start_time) * 1000
            
            print(f"  → SQL: {generated_sql[:80]}...")
            
            # Step 3: Execution
            execution_result = test_sql_execution(generated_sql, settings.DATABASE_URL)
            
            if execution_result["success"]:
                print(f"  ✓ SUCCESS ({execution_result['execution_time_ms']:.0f}ms, {execution_result.get('row_count', 0)} rows)")
            else:
                print(f"  ✗ FAILED: {execution_result['error_type']}")
                print(f"    {execution_result['error_message'][:100]}")
            
            # Store result
            results.append({
                "id": test_case.get("id", f"q{i}"),
                "question": question,
                "complexity": complexity,
                "ground_truth_tables": test_case.get("ground_truth_tables", []),
                "retrieved_tables": retrieved_tables,
                "generated_sql": generated_sql,
                "execution_success": execution_result["success"],
                "error_type": execution_result.get("error_type"),
                "error_message": execution_result.get("error_message"),
                "schema_linking_time_ms": round(schema_time, 2),
                "sql_generation_time_ms": round(generation_time, 2),
                "execution_time_ms": execution_result["execution_time_ms"]
            })
        
        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}")
            results.append({
                "id": test_case.get("id", f"q{i}"),
                "question": question,
                "complexity": complexity,
                "error": str(e),
                "execution_success": False
            })
        
        print()
    
    # Calculate metrics
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    
    total = len(results)
    successful = sum(1 for r in results if r.get("execution_success"))
    
    print(f"\nOverall Success Rate: {successful}/{total} ({successful/total*100:.1f}%)")
    
    # By complexity
    print("\nBy Complexity:")
    for complexity in ["simple", "medium", "hard"]:
        subset = [r for r in results if r.get("complexity") == complexity]
        if subset:
            success_count = sum(1 for r in subset if r.get("execution_success"))
            print(f"  {complexity.capitalize()}: {success_count}/{len(subset)} ({success_count/len(subset)*100:.1f}%)")
    
    # Error distribution
    errors = [r.get("error_type") for r in results if not r.get("execution_success") and r.get("error_type")]
    if errors:
        print("\nError Types:")
        from collections import Counter
        error_counts = Counter(errors)
        for error_type, count in error_counts.most_common():
            print(f"  {error_type}: {count}")
    
    # Save results
    with open(output_path, 'w') as f:
        json.dump({
            "metadata": {
                "total_queries": total,
                "successful_queries": successful,
                "overall_success_rate": round(successful/total, 3),
                "prompt_version": "v1"
            },
            "results": results
        }, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    # Paths
    dataset_path = "app/evaluation/datasets/core_eval.json"
    output_path = "evaluation_results/day2_baseline_results.json"
    
    # Create output directory
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Run evaluation
    run_evaluation(dataset_path, output_path)
