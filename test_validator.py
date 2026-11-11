from app.agents.sql_validator import validate_sql

sql = """
SELECT
    ROUND(
        COUNT(*) FILTER (
            WHERE order_delivered_customer_date >
                  order_estimated_delivery_date
        ) * 100.0 / NULLIF(COUNT(*), 0),
        2
    ) AS late_order_percentage
FROM orders
WHERE order_status = 'delivered'
LIMIT 100;
"""

print(validate_sql(sql))