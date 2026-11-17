"""Deterministic SQL templates for well-defined business metrics."""

import re

def explicit_lateness_percentage_query(question: str):
    """Build a safe order-level query for an explicit lateness percentage."""
    parts = question.split("AUTHORITATIVE USER CLARIFICATION:", 1)
    original = parts[0].lower()
    decision = parts[1].lower() if len(parts) == 2 else ""
    has_percentage = re.search(
        r"\b(persen(?:tase)?|percentage|percent)\b", original
    )
    has_lateness = re.search(
        r"\b(terlambat|keterlambatan|telat|late|lateness)\b", original
    )
    has_delivered = re.search(r"\b(delivered|terkirim)\b", original)
    has_order = re.search(r"\b(pesanan|orders?|order)\b", original)
    all_orders_pattern = r"\b(semua|seluruh)\s+pesanan\b|\ball\s+(the\s+)?orders?\b"
    chose_all_orders = re.search(all_orders_pattern, decision)
    chose_delivered = re.search(r"\b(delivered|terkirim)\b", decision)
    asked_for_all_orders = re.search(all_orders_pattern, original)
    has_period = re.search(
        r"\b(tahun|bul(an)?|minggu|year|month|week|daily|monthly|yearly|"
        r"terakhir|last|since|between)\b",
        original + " " + decision,
    )

    if not all((has_percentage, has_lateness, has_order)) or has_period:
        return None

    if chose_all_orders:
        use_all_orders_denominator = True
    elif chose_delivered:
        use_all_orders_denominator = False
    elif has_delivered:
        use_all_orders_denominator = False
    else:
        use_all_orders_denominator = bool(asked_for_all_orders)

    # With no explicit population choice, only take this path when the
    # user explicitly named delivered orders or all orders.
    if not (has_delivered or asked_for_all_orders or chose_all_orders):
        return None

    query = (
        "SELECT ROUND(\n"
        "    COUNT(*) FILTER (\n"
        "        WHERE o.order_status = 'delivered'\n"
        "          AND o.order_delivered_customer_date > "
        "o.order_estimated_delivery_date\n"
        "    ) * 100.0 / NULLIF(COUNT(*), 0),\n"
        "    2\n"
        ") AS late_order_percentage\n"
        "FROM orders AS o"
    )
    if not use_all_orders_denominator:
        query += "\nWHERE o.order_status = 'delivered'"
    return query


def explicit_monthly_delivery_lateness_query(question: str):
    """Build monthly delivered and late-order metrics for an explicit year."""
    lowered = question.lower()
    year_match = re.search(r"\b(20\d{2})\b", lowered)
    asks_months = re.search(
        r"\b(setiap|tiap|per)\s+bulan\b|\b(each|every)\s+month\b|\bmonthly\b",
        lowered,
    )
    asks_late = re.search(r"\b(terlambat|keterlambatan|telat|late)\b", lowered)
    asks_delivered = re.search(r"\b(delivered|terkirim)\b", lowered)
    asks_percentage = re.search(
        r"\b(persen(?:tase)?|percentage|percent)\b", lowered
    )
    if not all((year_match, asks_months, asks_late, asks_delivered, asks_percentage)):
        return None

    year = int(year_match.group(1))
    month_expression = "DATE_TRUNC('month', o.order_purchase_timestamp)"
    late_condition = (
        "o.order_delivered_customer_date > o.order_estimated_delivery_date"
    )
    return (
        f"SELECT {month_expression}::date AS purchase_month,\n"
        "       COUNT(*) AS delivered_orders_count,\n"
        f"       COUNT(*) FILTER (WHERE {late_condition}) AS late_orders_count,\n"
        f"       ROUND(COUNT(*) FILTER (WHERE {late_condition}) * 100.0 "
        "/ NULLIF(COUNT(*), 0), 2) AS late_orders_percentage\n"
        "FROM orders AS o\n"
        "WHERE o.order_status = 'delivered'\n"
        "  AND o.order_purchase_timestamp >= "
        f"TIMESTAMP '{year}-01-01'\n"
        "  AND o.order_purchase_timestamp < "
        f"TIMESTAMP '{year + 1}-01-01'\n"
        f"GROUP BY {month_expression}\n"
        "ORDER BY purchase_month"
    )


def explicit_repeat_customer_by_state_query(question: str):
    """Count repeat buyers by state using the stable customer identifier."""
    parts = question.split("AUTHORITATIVE USER CLARIFICATION:", 1)
    original = parts[0].lower()
    decision = parts[1].lower() if len(parts) == 2 else ""
    year_match = re.search(r"\b(20\d{2})\b", original)
    asks_state = re.search(r"\b(state|states|provinsi)\b", original)
    asks_customers = re.search(r"\b(pelanggan|customers?)\b", original)
    asks_repeat = re.search(
        r"minimal\s+dua|setidaknya\s+dua|at\s+least\s+two|"
        r"minimal\s+2|at\s+least\s+2",
        original,
    )
    asks_percentage = re.search(
        r"\b(persen(?:tase)?|percentage|percent)\b", original
    )
    if not all(
        (year_match, asks_state, asks_customers, asks_repeat, asks_percentage)
    ):
        return None

    all_statuses = re.search(
        r"all\s+(orders|statuses)|include\s+all|semua\s+(order|pesanan|status)|"
        r"seluruh\s+(order|pesanan|status)",
        decision,
    )
    delivered_only = re.search(
        r"\b(only\s+delivered|hanya\s+delivered|delivered\s+orders?)\b",
        decision,
    )
    filter_status = bool(delivered_only or (not all_statuses and re.search(
        r"\b(delivered|terkirim)\b", original
    )))

    year = int(year_match.group(1))
    status_filter = "\n  AND o.order_status = 'delivered'" if filter_status else ""
    return (
        "WITH customer_order_counts AS (\n"
        "    SELECT c.customer_state, c.customer_unique_id,\n"
        "           COUNT(DISTINCT o.order_id) AS order_count\n"
        "    FROM customers AS c\n"
        "    JOIN orders AS o ON o.customer_id = c.customer_id\n"
        "    WHERE c.customer_unique_id IS NOT NULL\n"
        "      AND o.order_purchase_timestamp >= "
        f"TIMESTAMP '{year}-01-01'\n"
        "      AND o.order_purchase_timestamp < "
        f"TIMESTAMP '{year + 1}-01-01'"
        f"{status_filter}\n"
        "    GROUP BY c.customer_state, c.customer_unique_id\n"
        ")\n"
        "SELECT customer_state,\n"
        "       COUNT(*) FILTER (WHERE order_count >= 2) AS repeat_customers,\n"
        "       COUNT(*) AS customers_with_orders,\n"
        "       ROUND(COUNT(*) FILTER (WHERE order_count >= 2) * 100.0 / "
        "NULLIF(COUNT(*), 0), 2) AS repeat_customer_percentage\n"
        "FROM customer_order_counts\n"
        "GROUP BY customer_state\n"
        "ORDER BY repeat_customer_percentage DESC, customer_state"
    )


def explicit_order_years_query(question: str):
    """Return distinct purchase years when the user asks which years have orders."""
    lowered = question.lower()
    asks_year_list = re.search(
        r"\b(tahun\s+(?:berapa|apa)\s+(?:aja|saja)|tahun\s+berapa|"
        r"which\s+years|what\s+years|years?\s+(?:are\s+)?present)\b",
        lowered,
    )
    mentions_orders = re.search(
        r"\b(order(?:nya)?|orders?|pesanan)\b", lowered
    )
    if not (asks_year_list and mentions_orders):
        return None

    return (
        "SELECT DISTINCT EXTRACT(YEAR FROM o.order_purchase_timestamp)::INTEGER "
        "AS order_year\n"
        "FROM orders AS o\n"
        "WHERE o.order_purchase_timestamp IS NOT NULL\n"
        "ORDER BY order_year"
    )


def explicit_annual_order_count_query(question: str):
    """Build an all-status order count grouped by purchase year."""
    lowered = question.lower()
    mentions_orders = re.search(
        r"\b(order(?:nya)?|orders|pesanan)\b", lowered
    )
    asks_for_count = re.search(
        r"\b(jumlah|banyak|count|number|total)\b", lowered
    )
    asks_per_year = re.search(
        r"\b(tiap|setiap|per)\s+tahun\b|\b(each|every|by)\s+year\b|"
        r"\byearly\b",
        lowered,
    )
    has_period_constraint = re.search(
        r"\b(tahun\s+20\d\d|in\s+20\d\d|between|sejak|sejak\s+tahun|"
        r"since|last\s+\d+)\b",
        lowered,
    )

    if not (mentions_orders and asks_for_count and asks_per_year):
        return None
    if has_period_constraint:
        return None

    return (
        "SELECT EXTRACT(YEAR FROM o.order_purchase_timestamp)::INTEGER "
        "AS order_year, COUNT(*) AS order_count\n"
        "FROM orders AS o\n"
        "WHERE o.order_purchase_timestamp IS NOT NULL\n"
        "GROUP BY EXTRACT(YEAR FROM o.order_purchase_timestamp)\n"
        "ORDER BY order_year"
    )


def explicit_category_revenue_query(question: str):
    """Build the requested category revenue report from order-level tables."""
    parts = question.split("AUTHORITATIVE USER CLARIFICATION:", 1)
    if len(parts) != 2:
        return None

    original = parts[0].lower()
    decision = parts[1].lower()
    year_match = re.search(r"\b(20\d{2})\b", original)
    asks_category = re.search(r"\b(kategori|category|categories)\b", original)
    asks_revenue = re.search(r"\b(revenue|pendapatan)\b", original)
    asks_top_ten = re.search(
        r"\b10\b.*\b(tertinggi|top|highest)\b|"
        r"\b(top|highest)\b.*\b10\b",
        original,
    )
    asks_item_count = re.search(
        r"\b(jumlah|count|number)\b.*\b(item|items)\b", original
    )
    asks_unique_orders = re.search(
        r"\b(order|orders|pesanan)\b.*\b(unik|unique)\b|"
        r"\b(unik|unique)\b.*\b(order|orders|pesanan)\b",
        original,
    )
    if not all(
        (
            year_match,
            asks_category,
            asks_revenue,
            asks_top_ten,
            asks_item_count,
            asks_unique_orders,
        )
    ):
        return None

    all_statuses = re.search(
        r"all\s+(orders|statuses)|include\s+all|semua\s+(order|pesanan|status)|"
        r"seluruh\s+(order|pesanan|status)",
        decision,
    )
    selected_delivered = re.search(r"\b(delivered|terkirim)\b", decision)
    if not (all_statuses or selected_delivered):
        return None

    year = int(year_match.group(1))
    status_filter = ""
    if selected_delivered and not all_statuses:
        status_filter = "\n  AND o.order_status = 'delivered'"
    category_expression = (
        "COALESCE(t.product_category_name_english, p.product_category_name)"
    )
    return (
        f"SELECT {category_expression} AS product_category,\n"
        "       COUNT(*) AS items_sold,\n"
        "       COUNT(DISTINCT o.order_id) AS unique_orders,\n"
        "       SUM(oi.price) AS revenue\n"
        "FROM orders AS o\n"
        "JOIN order_items AS oi ON oi.order_id = o.order_id\n"
        "JOIN products AS p ON p.product_id = oi.product_id\n"
        "LEFT JOIN product_category_name_translation AS t "
        "ON t.product_category_name = p.product_category_name\n"
        "WHERE o.order_purchase_timestamp >= "
        f"TIMESTAMP '{year}-01-01'\n"
        "  AND o.order_purchase_timestamp < "
        f"TIMESTAMP '{year + 1}-01-01'"
        f"{status_filter}\n"
        f"GROUP BY {category_expression}\n"
        "ORDER BY revenue DESC\n"
        "LIMIT 10"
    )
