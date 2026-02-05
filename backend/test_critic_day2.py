from app.agents.critic import CriticAgent

# Schema from Day 2
schema = {
    "products": {
        "columns": {
            "product_id": "INTEGER",
            "name": "VARCHAR", 
            "price": "DECIMAL",
            "category_id": "INTEGER"
        },
        "primary_keys": ["product_id"],
        "foreign_keys": {}
    },
    "order_items": {
        "columns": {
            "order_item_id": "INTEGER",
            "product_id": "INTEGER",
            "quantity": "INTEGER"
        },
        "primary_keys": ["order_item_id"],
        "foreign_keys": {}
    }
}

# The Day 2 failure SQL
bad_sql = """
SELECT category_id, product_id, SUM(price * stock_quantity) AS revenue
FROM products
JOIN order_items ON products.id = order_items.product_id
GROUP BY category_id, product_id
"""

critic = CriticAgent()
result = critic.validate(bad_sql, schema)

print("Day 2 Failure Test:")
print(f"SQL: {bad_sql[:80]}...")
print(f"Result: {result}")
print(f"\nDid it catch the error? {'✅ YES' if not result.is_valid else '❌ NO'}")
print(f"Issues found: {result.issues}")
