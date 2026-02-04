"""
Test suite for Schema Linker retrieval quality
"""

import sys
from pathlib import Path

# Add backend to Python path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.agents.schema_linker import SchemaLinker


def test_schema_retrieval_quality():
    """Test if Schema Linker retrieves relevant tables"""
    
    linker = SchemaLinker()
    linker.index_schema(reset=True)
    
    # Ground truth: what tables SHOULD be retrieved
    test_cases = [
        {
            "question": "What are the top 10 products by revenue?",
            "expected_tables": {"products", "order_items"}
        },
        {
            "question": "Show me customer information",
            "expected_tables": {"customers"}
        },
        {
            "question": "Find orders from last month",
            "expected_tables": {"orders"}
        },
        {
            "question": "Which products have low stock?",
            "expected_tables": {"products"}
        },
        {
            "question": "Show customer reviews and ratings",
            "expected_tables": {"reviews", "products"}
        }
    ]
    
    print("\n" + "="*60)
    print("SCHEMA RETRIEVAL QUALITY TEST")
    print("="*60)
    
    total_recall = 0
    total_precision = 0
    
    for i, test in enumerate(test_cases, 1):
        question = test["question"]
        expected = test["expected_tables"]
        
        # Get actual retrieval
        retrieved = linker.link_schema(question, top_k=10)
        retrieved_tables = set(retrieved.keys())
        
        # Calculate metrics
        correct = expected & retrieved_tables
        recall = len(correct) / len(expected) if expected else 0
        precision = len(correct) / len(retrieved_tables) if retrieved_tables else 0
        
        total_recall += recall
        total_precision += precision
        
        print(f"\n{i}. {question}")
        print(f"   Expected: {expected}")
        print(f"   Retrieved: {retrieved_tables}")
        print(f"   Recall: {recall:.2%}")
        print(f"   Precision: {precision:.2%}")
    
    avg_recall = total_recall / len(test_cases)
    avg_precision = total_precision / len(test_cases)
    
    print("\n" + "="*60)
    print(f"OVERALL METRICS")
    print("="*60)
    print(f"Average Recall: {avg_recall:.2%} (Target: ≥85%)")
    print(f"Average Precision: {avg_precision:.2%} (Target: ≥70%)")
    
    if avg_recall >= 0.85:
        print("✓ Recall target MET!")
    else:
        print("✗ Recall below target")
    
    if avg_precision >= 0.70:
        print("✓ Precision target MET!")
    else:
        print("✗ Precision below target")


if __name__ == "__main__":
    test_schema_retrieval_quality()
