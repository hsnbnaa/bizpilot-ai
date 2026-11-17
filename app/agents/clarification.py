"""Interpret user responses to BizPilot clarification questions."""

import re

from ollama import chat

from app.agents.sql_prompts import (
    CLARIFICATION_RESPONSE_PROMPT, MODEL_NAME, MODEL_OPTIONS,
)
from app.agents.sql_parsing import extract_json

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

    # A request for years in which orders exist does not need a status
    # choice. Treat a user restatement that mentions orders and years as
    # confirmation to inspect all orders.
    clarification_context = normalize_choice_text(clarification_question)
    response_context = normalize_choice_text(user_response)
    original_context = normalize_choice_text(original_question)
    asks_years = re.search(
        r"\b(tahun|years?)\b.*\b(berapa|apa|which|what)\b|"
        r"\b(berapa|apa|which|what)\b.*\b(tahun|years?)\b",
        original_context,
    )
    mentions_order_and_year = (
        re.search(r"\b(order(?:nya)?|orders?|pesanan)\b", response_context)
        and re.search(r"\b(di)?tahun\b|\byears?\b", response_context)
    )
    clarification_is_about_status = re.search(
        r"\b(status|delivered|terkirim)\b", clarification_context
    )
    if asks_years and mentions_order_and_year and clarification_is_about_status:
        return {
            "intent": "ANSWER",
            "answer": (
                "Tampilkan tahun order berdasarkan "
                "order_purchase_timestamp untuk semua status."
            ),
            "explanation": None,
            "follow_up_question": None,
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
            # Preserve a clear user choice when the model omits its
            # answer field instead of trapping the conversation in a loop.
            answer = user_response.strip()
            if not answer:
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


class ClarificationInterpreter:
    """Coordinate clarification response interpretation."""

    def interpret(self, original_question: str, clarification_question: str, user_response: str) -> dict:
        return interpret_clarification_response(
            original_question, clarification_question, user_response
        )
