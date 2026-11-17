"""Format query results and generate user-facing business answers."""

import json
import re
from typing import Optional

from ollama import chat

from app.agents.sql_prompts import MODEL_NAME, MODEL_OPTIONS

def format_category_revenue_answer(
    query_result: dict,
    executed_sql: str,
) -> Optional[str]:
    """Format category revenue rows without model-invented units or filters."""
    required_columns = {
        "product_category",
        "items_sold",
        "unique_orders",
        "revenue",
    }
    if not required_columns.issubset(set(query_result.get("columns", []))):
        return None

    data = query_result.get("data") or []
    if not data:
        return "Tidak ada data kategori yang cocok dengan filter query."

    year_match = re.search(r"\b(20\d{2})-01-01\b", executed_sql)
    year = year_match.group(1) if year_match else None
    delivered_only = bool(
        re.search(r"\border_status\s*=\s*'delivered'", executed_sql, re.IGNORECASE)
    )
    if delivered_only:
        scope = "pesanan berstatus delivered"
    elif re.search(r"\border_status\b", executed_sql, re.IGNORECASE):
        scope = "pesanan yang memenuhi filter status pada SQL"
    else:
        scope = "pesanan dari semua status"
    period = f" pada {year}" if year else ""

    lines = [
        f"10 kategori produk dengan revenue tertinggi untuk {scope}{period}:",
        "Revenue ditampilkan sebagai nilai numerik dari database; satuan mata uang tidak tersedia.",
        "",
    ]
    for rank, row in enumerate(data, start=1):
        category = row.get("product_category") or "(kategori tidak diketahui)"
        lines.append(
            f"{rank}. {category} - "
            f"{row.get('items_sold')} item; "
            f"{row.get('unique_orders')} order unik; "
            f"revenue {row.get('revenue')}"
        )
    return "\n".join(lines)


def format_monthly_lateness_answer(query_result: dict) -> Optional[str]:
    """Format monthly delivery metrics using the database values verbatim."""
    required_columns = {
        "purchase_month",
        "delivered_orders_count",
        "late_orders_count",
        "late_orders_percentage",
    }
    if not required_columns.issubset(set(query_result.get("columns", []))):
        return None

    data = query_result.get("data") or []
    if not data:
        return "Tidak ada pesanan delivered pada periode tersebut."

    lines = ["Ringkasan keterlambatan pesanan delivered per bulan:", ""]
    for row in data:
        month = row.get("purchase_month")
        percentage = row.get("late_orders_percentage")
        percentage_text = (
            "tidak tersedia"
            if percentage is None
            else f"{percentage}%"
        )
        lines.append(
            f"{month}: {row.get('delivered_orders_count')} delivered, "
            f"{row.get('late_orders_count')} terlambat, "
            f"persentase {percentage_text}"
        )
    return "\n".join(lines)


def format_repeat_customer_answer(query_result: dict) -> Optional[str]:
    """Format repeat-customer counts without inferring from order totals."""
    required_columns = {
        "customer_state",
        "repeat_customers",
        "customers_with_orders",
        "repeat_customer_percentage",
    }
    if not required_columns.issubset(set(query_result.get("columns", []))):
        return None

    data = query_result.get("data") or []
    if not data:
        return "Tidak ada pelanggan dengan pesanan yang cocok dengan filter query."

    lines = ["Pelanggan berulang per state:", ""]
    for row in data:
        percentage = row.get("repeat_customer_percentage")
        percentage_text = "tidak tersedia" if percentage is None else f"{percentage}%"
        lines.append(
            f"{row.get('customer_state')}: {row.get('repeat_customers')} pelanggan "
            f"berulang dari {row.get('customers_with_orders')} pelanggan unik; "
            f"persentase {percentage_text}"
        )
    return "\n".join(lines)


def generate_answer(
    question: str,
    query_result: dict,
    executed_sql: str = "",
) -> str:
    """
    Generate a natural-language answer based only
    on the executed SQL result.
    """

    repeat_customer_report = format_repeat_customer_answer(query_result)
    if repeat_customer_report is not None:
        return repeat_customer_report

    monthly_lateness_report = format_monthly_lateness_answer(query_result)
    if monthly_lateness_report is not None:
        return monthly_lateness_report

    category_report = format_category_revenue_answer(
        query_result=query_result,
        executed_sql=executed_sql,
    )
    if category_report is not None:
        return category_report

    prompt = f"""
You are BizPilot AI, a business intelligence assistant.

Answer the user's question using ONLY the SQL query result.

USER QUESTION:
{question}

EXECUTED SQL:
{executed_sql or "Not provided"}

SQL QUERY RESULT:
{json.dumps(query_result, default=str, indent=2)}

RULES:

1. Never invent numbers or facts.
2. Explain the actual result accurately.
   Determine filters and population from the EXECUTED SQL, including
   any explicit user clarification. Do not claim a status filter was
   applied when it is absent from the SQL.
3. Do not make unsupported business conclusions.
4. Do not claim a business problem exists unless
   the data supports that conclusion.
5. Explain percentages using their actual numerator
   and denominator when available.
   Never describe a percentage value as a count. For example,
   8.11% is not "8.11 orders". Only report a count when the SQL result
   contains a count value.
6. Distinguish between orders, order items, and products.
7. Do not describe order-level delivery results as
   individual product delivery results.
8. If the result does not answer the question,
   explain the limitation.
9. Use Indonesian when the user asks in Indonesian.
10. Keep the answer clear and concise.
11. Do not assume that a query result of 100 means
    that all business entities have the same outcome.
12. Do not infer additional statistics from a single value.
13. Never convert, rescale, or relabel numeric values as a currency.
    If the schema and result do not specify a currency, report the
    numeric value as returned without a currency symbol or name.
14. Do not repeat the user's full question. Summarize the result directly.
"""

    response = chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        options=MODEL_OPTIONS
    )

    return response.message.content.strip()


class AnswerGenerator:
    """Create concise answers from executed SQL and database rows."""

    def generate(self, question: str, query_result: dict, executed_sql: str = "") -> str:
        return generate_answer(question, query_result, executed_sql)
