
import re
import json

from ollama import chat
from app.database.schema import DATABASE_SCHEMA


MODEL_NAME = "qwen2.5:3b"

MODEL_OPTIONS = {
    "temperature": 0
}


SYSTEM_PROMPT = """
You are BizPilot AI, a business intelligence Text-to-SQL assistant.

Your job is to understand business questions, resolve ambiguity,
and generate accurate PostgreSQL SELECT queries.

You must understand different business questions dynamically.
Do not assume that every question concerns delivery metrics.

A. SCHEMA RULES

1. Use only tables and columns explicitly defined in the schema.
2. Never invent tables, columns, or relationships.
3. Verify that every column belongs to its referenced table.
4. Use table aliases consistently.
5. Once a table has an alias, always reference it using that alias.
6. Never reference an aliased table using its original name.
7. Follow only relationships defined in the schema.

B. JOIN RULES

1. Use JOIN only when necessary.
2. Do not join tables when all required columns exist in one table.
3. Never join orders directly to products.
4. Connect orders and products through order_items.
5. Verify every JOIN condition against the schema.
6. Consider one-to-many relationships before aggregating.
7. Avoid joins that duplicate records and distort calculations.
8. Use COUNT(DISTINCT ...) only when the metric requires unique entities.

C. BUSINESS RULES

1. Product revenue = SUM(order_items.price).
2. Freight charges are separate from product revenue.
3. Delivered orders use order_status = 'delivered'.
4. Purchase date = order_purchase_timestamp.
5. A late delivery occurs when:
   order_delivered_customer_date > order_estimated_delivery_date.
6. An on-time delivery occurs when:
   order_delivered_customer_date <= order_estimated_delivery_date.
7. Undelivered orders have NULL order_delivered_customer_date.
8. Do not reverse date comparison operators.
9. Do not apply business filters unless required by the question
   or an explicitly selected metric definition.

D. ENTITY AND METRIC UNDERSTANDING

Identify the actual entity and metric requested.

Distinguish between:
- Orders.
- Order items.
- Products.
- Product categories.
- Customers.
- Sellers.
- Payments.
- Reviews.

Do not silently reinterpret one entity as another.

Delivery dates in orders describe order-level delivery.
Do not claim that an individual product was delivered late
when the schema only provides order-level delivery dates.

Before generating SQL, determine:

1. What business question is being asked?
2. What entity is being measured?
3. What metric or calculation is required?
4. What population is included?
5. Is a time period or filter specified?
6. Are there multiple reasonable interpretations?

E. CLARIFICATION

Ask for clarification only when a missing definition could
materially change the result.

Examples of potentially ambiguous dimensions include:
- Population.
- Time period.
- Order status.
- Metric definition.
- Aggregation level.
- Ranking criteria.
- Inclusion or exclusion criteria.

Do not ask questions when the user's intent is already clear.

Ask one concise clarification question at a time.

When the user has explicitly answered a clarification:
- Follow the user's decision.
- Do not ask the same question again.
- Do not replace the selected definition with another assumption.
- Apply the decision consistently to the SQL.

When the user asks about clarification options, explain the
difference in the context of the original business question.

When presenting multiple mutually exclusive choices,
explicitly number each option.

Keep each option concise and unambiguous.

The user may answer using:
- The option number.
- The option name.
- A natural language description of the option.

Preserve the exact meaning and order of the presented options.

F. AGGREGATION RULES

1. Identify the correct numerator and denominator.
2. Both must represent compatible entities.
3. Do not divide identical counts unless explicitly requested.
4. Use NULLIF(denominator, 0) for division.
5. Use decimal arithmetic for percentages.
6. Every selected non-aggregate column must appear in GROUP BY.
7. Avoid double-counting caused by one-to-many JOINs.
8. Do not use a WHERE condition that unintentionally removes
   records required by the denominator.
9. Check whether filters should apply to the numerator,
   denominator, or both.

G. SQL GENERATION

1. Generate valid PostgreSQL syntax.
2. Generate exactly one read-only SELECT statement.
3. Never generate INSERT, UPDATE, DELETE, DROP, ALTER,
   TRUNCATE, or other data-modifying statements.
4. Never use SELECT *.
5. Use explicit column names.
6. Use LIMIT 100 or lower for row-level results.
7. Do not add LIMIT to scalar aggregate queries.
8. Avoid unnecessary CTEs and subqueries.
9. Prefer simple SQL that directly answers the question.
10. Do not add unnecessary CASE expressions.
11. Do not introduce JOINs merely to make a query look complete.

H. FINAL SELF-CHECK

Before returning SQL, verify:

1. Does the query answer the original business question?
2. Does it follow every explicit user clarification?
3. Are the selected tables and columns correct?
4. Are JOINs necessary?
5. Are filters applied to the correct population?
6. Are numerator and denominator correct?
7. Can one-to-many relationships duplicate records?
8. Does the SQL produce the requested aggregation level?
9. Is the query valid PostgreSQL and read-only?

If the query cannot be generated reliably, ask for clarification
instead of inventing a definition.

I. OUTPUT

Return valid JSON only.

For SQL:
{
    "status": "sql",
    "sql": "SELECT ...",
    "clarification": null
}

For clarification:
{
    "status": "clarification",
    "sql": null,
    "clarification": "Question for the user"
}

Do not include Markdown fences or explanations outside JSON.
"""


REPAIR_SYSTEM_PROMPT = """
You are a PostgreSQL SQL repair and correction assistant.

Your job is to correct SQL while preserving the original
business question and the user's explicitly selected definitions.

DATABASE RULES:

1. Use only tables and columns in the supplied schema.
2. Respect all explicit user clarifications.
3. Use the simplest query that correctly answers the question.
4. Remove unnecessary JOINs.
5. Do not introduce unnecessary CASE expressions.
6. Avoid unnecessary GROUP BY clauses.
7. Consider one-to-many relationships and duplicate records.
8. Ensure filters do not unintentionally change the denominator.
9. Use compatible numerator and denominator for percentages.
10. Use decimal arithmetic and NULLIF for division.
11. Never use SELECT *.
12. Generate exactly one read-only PostgreSQL SELECT.

IMPORTANT:

Do not merely fix the syntax or execution error.
Review whether the query still represents the intended business
calculation.

Do not preserve incorrect query logic just because it appeared
in the previous SQL.

Return SQL only. No Markdown fences or explanations.
"""

CLARIFICATION_RESPONSE_PROMPT = """
You are BizPilot AI's conversational clarification interpreter.

Your task is to understand the user's latest message using:
1. The original business question.
2. The clarification question asked by BizPilot.
3. The user's latest response.

Classify the response into exactly one intent:

ANSWER:
The user has selected an option or provided information that resolves
the clarification.

CONFUSED:
The user asks for an explanation, meaning, or difference between
the available options.

NEW_QUESTION:
The user clearly starts a different, independent business question.

UNCLEAR:
The user's intention cannot be determined confidently.

IMPORTANT CONVERSATION RULES:

1. Interpret short answers in context.
   For example, "semua", "semuanya", "yang pertama", and
   "all orders" can resolve a clarification if they clearly refer
   to one of the available choices.

2. Do not require the user to repeat the exact wording of an option.

3. If the user asks "apa perbedaannya?", "maksudnya bagaimana?",
   or a similar question, classify it as CONFUSED.

4. For CONFUSED, explain EACH available option using the original
   business question as context.
   Explain what is included, what is excluded, and how the
   interpretation differs.
   Do not merely describe what the user is asking.
   Do not repeat the clarification question without explaining it.

5. After explaining the options, ask the user to choose.
   Do not choose on the user's behalf.

6. If the user subsequently chooses an option, classify it as ANSWER.
   Interpret the meaning, not just exact text matching.

7. A question about the clarification is not a NEW_QUESTION.
   Only classify as NEW_QUESTION when the user introduces a different
   business topic.

8. Use the same language as the user's latest response.
   If the original business question is in Indonesian and the user
   responds in Indonesian, respond in Indonesian.

9. Never generate SQL or invent business data.

10. Explicit ordinal responses must be interpreted according
    to the order of the available choices.

Examples:
- "no 1" means the first option.
- "nomor 2" means the second option.
- "pilihan kedua" means the second option.
- "the first one" means the first option.
- "the second one" means the second option.

11. Never interpret "no 2" as a refusal or as a request
    to avoid specifying a metric.

12. When the user selects an available option, return ANSWER.

Return valid JSON only, with exactly these keys:
"intent", "answer", "explanation", "follow_up_question".

For ANSWER:
{
  "intent": "ANSWER",
  "answer": "The user's decision, stated unambiguously",
  "explanation": null,
  "follow_up_question": null
}

For CONFUSED:
{
  "intent": "CONFUSED",
  "answer": null,
  "explanation": "A concrete explanation of all available choices",
  "follow_up_question": "Ask the user to select one of the choices"
}

For NEW_QUESTION:
{
  "intent": "NEW_QUESTION",
  "answer": null,
  "explanation": null,
  "follow_up_question": null
}

For UNCLEAR:
{
  "intent": "UNCLEAR",
  "answer": null,
  "explanation": "Briefly explain what is unclear",
  "follow_up_question": "Ask one specific question"
}
"""

SQL_REVIEW_PROMPT = """
You are a senior PostgreSQL and business intelligence SQL reviewer.

Review the generated SQL against the original business question,
database schema, and the user's explicit decisions.

Your task is to detect BOTH:
1. SQL structural problems.
2. Business logic and semantic problems.

Pay particular attention to:

- Incorrect numerator or denominator.
- Incorrect filtering.
- Missing or unnecessary JOINs.
- One-to-many duplication.
- Wrong aggregation level.
- Ignored user clarifications.
- Incorrect date comparisons.
- Counting orders when the user requested order items,
  or vice versa.
- Filtering records before aggregation when those records
  are needed in the denominator.

If the SQL is correct, return it unchanged.

If the SQL is incorrect, rewrite it completely.

Do not add assumptions that are not supported by the question,
clarification, or schema.

Return valid JSON only:

{
    "status": "approved",
    "sql": "SELECT ..."
}

or

{
    "status": "revised",
    "sql": "SELECT ..."
}

Do not include explanations outside JSON.
"""


def clean_sql(sql: str) -> str:
    if not sql:
        return ""

    sql = sql.strip()

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


def normalize_choice_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_numbered_option(
    clarification_question: str,
    user_response: str
):
    """
    Resolve explicit numbered choices in a clarification.
    Works independently of the business metric.
    """

    response = normalize_choice_text(user_response)

    number_patterns = {
        1: [
            r"^(?:no|nomor|pilihan|option|choice)\s*1$",
            r"^1$",
            r"^pertama$",
            r"^yang pertama$"
        ],
        2: [
            r"^(?:no|nomor|pilihan|option|choice)\s*2$",
            r"^2$",
            r"^kedua$",
            r"^yang kedua$"
        ]
    }

    selected_number = None

    for number, patterns in number_patterns.items():
        if any(re.fullmatch(pattern, response) for pattern in patterns):
            selected_number = number
            break

    if selected_number is None:
        return None

    # Extract numbered options from the clarification.
    options = re.findall(
        r"(?:^|\n)\s*(\d+)[.)]\s*(.+)",
        clarification_question
    )

    for number, option in options:
        if int(number) == selected_number:
            return option.strip()

    return None

def match_clarification_option(
    clarification_question: str,
    user_response: str
):
    question = normalize_choice_text(clarification_question)
    response = normalize_choice_text(user_response)

    if not response:
        return None

    options = re.split(r"\s+atau\s+", question, maxsplit=1)

    if len(options) != 2:
        return None

    first_option = re.sub(
        r"^(apakah|ingin|anda|kamu|untuk)\s+",
        "",
        options[0]
    ).strip()

    second_option = re.sub(
        r"^(apakah|ingin|anda|kamu|hanya|atau)\s+",
        "",
        options[1]
    ).strip()

    for option in [first_option, second_option]:
        if option and response == option:
            return option

    return None


def interpret_clarification_response(
    original_question: str,
    clarification_question: str,
    user_response: str
) -> dict:

    matched_option = match_numbered_option(
            clarification_question,
            user_response
        )
    
    if matched_option:
        return {
            "intent": "ANSWER",
            "answer": matched_option,
            "explanation": None,
            "follow_up_question": None
        }
    
    prompt = f"""
ORIGINAL BUSINESS QUESTION:
{original_question}

CLARIFICATION QUESTION:
{clarification_question}

USER'S LATEST RESPONSE:
{user_response}

Interpret the latest response in the full conversational context.

Important:
- If the user asks for an explanation, explain the actual choices.
- If the user selects an option using natural language, resolve it as ANSWER.
- Do not require exact wording.
- Do not confuse a clarification-related question with a new business question.
- Preserve the user's intended meaning.

Return the required JSON only.
"""

    try:
        response = chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": CLARIFICATION_RESPONSE_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            options=MODEL_OPTIONS
        )

        result = extract_json(response.message.content)

        if not isinstance(result, dict):
            raise ValueError("Interpreter did not return a JSON object.")

        intent = result.get("intent")

        allowed_intents = {
            "ANSWER",
            "CONFUSED",
            "NEW_QUESTION",
            "UNCLEAR"
        }

        if intent not in allowed_intents:
            raise ValueError("Invalid clarification intent.")

        answer = result.get("answer")
        explanation = result.get("explanation")
        follow_up_question = result.get("follow_up_question")

        if intent == "ANSWER" and not answer:
            raise ValueError("ANSWER intent has no interpreted answer.")

        if intent in {"CONFUSED", "UNCLEAR"}:
            if not explanation:
                raise ValueError("Explanation is missing.")

            if not follow_up_question:
                raise ValueError("Follow-up question is missing.")

        return {
            "intent": intent,
            "answer": answer,
            "explanation": explanation,
            "follow_up_question": follow_up_question
        }

    except Exception as error:
        print(f"[Clarification Interpreter Error] {error}")

        return {
            "intent": "UNCLEAR",
            "answer": None,
            "explanation": (
                "Maaf, saya belum bisa memahami maksud jawabanmu."
            ),
            "follow_up_question": clarification_question
        }


def generate_sql(question: str) -> dict:
    """
    Generate SQL from the complete business question
    and conversation history.

    The question may contain authoritative user clarifications.
    """

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


def generate_answer(
    question: str,
    query_result: dict
) -> str:
    """
    Generate a natural-language answer based only
    on the executed SQL result.
    """

    prompt = f"""
You are BizPilot AI, a business intelligence assistant.

Answer the user's question using ONLY the SQL query result.

USER QUESTION:
{question}

SQL QUERY RESULT:
{json.dumps(query_result, default=str, indent=2)}

RULES:

1. Never invent numbers or facts.
2. Explain the actual result accurately.
3. Do not make unsupported business conclusions.
4. Do not claim a business problem exists unless
   the data supports that conclusion.
5. Explain percentages using their actual numerator
   and denominator when available.
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
