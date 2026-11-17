"""SQL generation, semantic review, and repair services."""

import re

from ollama import chat

from app.agents.sql_prompts import (
    MODEL_NAME, MODEL_OPTIONS, REPAIR_SYSTEM_PROMPT, SQL_REVIEW_PROMPT, SYSTEM_PROMPT,
)
from app.agents.sql_parsing import clean_sql, extract_json, parse_generation_response
from app.database.schema import DATABASE_SCHEMA
from app.agents.query_templates import (
    explicit_lateness_percentage_query,
    explicit_monthly_delivery_lateness_query,
    explicit_repeat_customer_by_state_query,
    explicit_order_years_query,
    explicit_annual_order_count_query,
    explicit_category_revenue_query,
)

def generate_sql(question: str) -> dict:
    """
    Generate SQL from the complete business question
    and conversation history.

    The question may contain authoritative user clarifications.
    """

    deterministic_query = explicit_repeat_customer_by_state_query(question)
    if not deterministic_query:
        deterministic_query = explicit_monthly_delivery_lateness_query(question)
    if not deterministic_query:
        deterministic_query = explicit_category_revenue_query(question)
    if not deterministic_query:
        deterministic_query = explicit_annual_order_count_query(question)
    if not deterministic_query:
        deterministic_query = explicit_order_years_query(question)
    if not deterministic_query:
        deterministic_query = explicit_lateness_percentage_query(question)
    if deterministic_query:
        return {
            "status": "sql",
            "sql": deterministic_query,
            "clarification": None,
            "deterministic": True,
        }

    prompt = f"""
DATABASE SCHEMA:
{DATABASE_SCHEMA}

BUSINESS QUESTION AND CONVERSATION CONTEXT:
{question}

INTERPRETATION REQUIREMENTS:

1. Read the entire conversation context.
2. Identify the original business question.
3. Identify all explicit user decisions.
4. Distinguish user decisions from assistant explanations.
5. Treat explicit user decisions as authoritative.
6. Do not ask again about already resolved definitions.
7. Do not infer that a clarification applies to a different
   metric or question unless the conversation establishes it.
8. If the user changes their decision, follow the latest
   explicit decision.
9. Generate SQL only when the business meaning is sufficiently clear.
10. If clarification is needed, ask only one concise question.
11. If the user selected the total number of orders, count all orders
    across every order_status. Do not filter to delivered orders.

Before returning SQL, check whether the query's filters,
joins, and aggregations actually implement the requested
business calculation.

Return the required JSON format only.
"""

    try:
        response = chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            options=MODEL_OPTIONS
        )

        return parse_generation_response(
            response.message.content
        )

    except Exception as error:
        print(f"[SQL Generation Error] {error}")

        return {
            "status": "clarification",
            "sql": None,
            "clarification": (
                "Terjadi kendala saat memahami pertanyaan. "
                "Bisa coba sampaikan kembali pertanyaanmu?"
            )
        }


def review_sql(
    question: str,
    generated_sql: str
) -> str:
    """
    Review SQL for business logic and semantic correctness.

    This is a second LLM pass, not a replacement for
    deterministic SQL security validation.
    """

    prompt = f"""
DATABASE SCHEMA:
{DATABASE_SCHEMA}

ORIGINAL BUSINESS QUESTION AND CLARIFICATIONS:
{question}

GENERATED SQL:
{generated_sql}

Review the query carefully.

Check whether the SQL actually answers the user's question.
Pay special attention to filters, populations, aggregation,
numerator, denominator, and unnecessary JOINs.

Return the required JSON only.
"""

    response = chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": SQL_REVIEW_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        options=MODEL_OPTIONS
    )

    try:
        result = extract_json(response.message.content)

        status = result.get("status")
        sql = clean_sql(result.get("sql", ""))

        if status not in {"approved", "revised"} or not sql:
            raise ValueError("Invalid SQL review response.")

        return sql

    except (ValueError, TypeError, AttributeError):
        # Do not silently replace a generated query with
        # malformed reviewer output.
        print("[SQL Review] Invalid review response. Using original SQL.")
        return clean_sql(generated_sql)


def repair_sql(
    question: str,
    failed_sql: str,
    error_message: str
) -> str:
    """
    Repair a failed query while preserving its business meaning.
    """

    prompt = f"""
DATABASE SCHEMA:
{DATABASE_SCHEMA}

ORIGINAL BUSINESS QUESTION AND CLARIFICATIONS:
{question}

FAILED SQL:
{failed_sql}

DATABASE ERROR:
{error_message}

Fix the SQL.

Review both its syntax and its business logic.
Do not preserve incorrect filtering or aggregation.

Return one PostgreSQL SELECT query only.
"""

    response = chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": REPAIR_SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        options=MODEL_OPTIONS
    )

    return clean_sql(response.message.content)


class SQLGenerationService:
    """Generate, review, and repair read-only SQL statements."""

    def generate(self, question: str) -> dict:
        return generate_sql(question)

    def review(self, question: str, generated_sql: str) -> str:
        return review_sql(question, generated_sql)

    def repair(self, question: str, failed_sql: str, error_message: str) -> str:
        return repair_sql(question, failed_sql, error_message)
