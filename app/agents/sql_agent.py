"""Public BizPilot agent API; implementation lives in focused services."""

from app.agents.answer_generation import AnswerGenerator
from app.agents.clarification import (
    ClarificationInterpreter,
    interpret_clarification_response,
    match_clarification_option,
    match_numbered_option,
    normalize_choice_text,
)
from app.agents.sql_generation import SQLGenerationService
from app.agents.sql_parsing import (
    clean_json_response,
    clean_sql,
    extract_json,
    parse_generation_response,
)

_sql_service = SQLGenerationService()
_clarification_service = ClarificationInterpreter()
_answer_service = AnswerGenerator()

def generate_sql(question: str) -> dict:
    return _sql_service.generate(question)

def review_sql(question: str, generated_sql: str) -> str:
    return _sql_service.review(question, generated_sql)

def repair_sql(question: str, failed_sql: str, error_message: str) -> str:
    return _sql_service.repair(question, failed_sql, error_message)

def interpret_clarification_response(
    original_question: str, clarification_question: str, user_response: str
) -> dict:
    return _clarification_service.interpret(
        original_question, clarification_question, user_response
    )

def generate_answer(
    question: str, query_result: dict, executed_sql: str = ""
) -> str:
    return _answer_service.generate(question, query_result, executed_sql)
