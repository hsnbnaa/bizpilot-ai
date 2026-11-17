"""Parsing and cleanup helpers for structured LLM responses."""

import json
import re

def clean_sql(sql: str) -> str:
    if not sql:
        return ""

    sql = sql.strip()

    # Prefer an explicit SQL code block when the model wraps SQL in prose.
    fenced_blocks = re.findall(
        r"```(?:sql|postgres(?:ql)?)?\s*(.*?)```",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_blocks:
        sql = fenced_blocks[0].strip()
    else:
        # Some model responses append prose after a closing fence without
        # opening a fence around the SQL.
        sql = re.split(r"\n\s*```", sql, maxsplit=1)[0].strip()

    sql = re.sub(
        r"^```(?:sql)?\s*",
        "",
        sql,
        flags=re.IGNORECASE
    )

    sql = re.sub(r"\s*```$", "", sql)

    return sql.strip().rstrip(";")


def clean_json_response(content: str) -> str:
    content = content.strip()

    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content,
        flags=re.IGNORECASE
    )

    content = re.sub(r"\s*```$", "", content)

    return content.strip()


def extract_json(content: str) -> dict:
    """
    Extract JSON from an LLM response.
    """

    content = clean_json_response(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Handle additional text surrounding a JSON object.
    start = content.find("{")
    end = content.rfind("}")

    if start != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not parse valid JSON from model response.")


def parse_generation_response(response_text: str) -> dict:
    try:
        result = extract_json(response_text)

        status = result.get("status")

        if status == "sql":
            sql = clean_sql(result.get("sql", ""))

            if not sql:
                raise ValueError("Empty SQL returned by model.")

            return {
                "status": "sql",
                "sql": sql,
                "clarification": None
            }

        if status == "clarification":
            clarification = result.get("clarification")

            if not clarification:
                clarification = (
                    "Bisa jelaskan lebih lanjut definisi "
                    "atau cakupan analisis yang diinginkan?"
                )

            return {
                "status": "clarification",
                "sql": None,
                "clarification": clarification
            }

    except (ValueError, TypeError, AttributeError):
        pass

    content = clean_json_response(response_text)

    # Raw SQL fallback.
    if re.match(r"^\s*SELECT\b", content, re.IGNORECASE):
        return {
            "status": "sql",
            "sql": clean_sql(content),
            "clarification": None
        }

    return {
        "status": "clarification",
        "sql": None,
        "clarification": (
            "Aku belum bisa menentukan definisi analisisnya. "
            "Bisa jelaskan sedikit lebih lanjut?"
        )
    }
