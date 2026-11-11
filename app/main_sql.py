
from sqlalchemy.exc import SQLAlchemyError

from app.agents.sql_agent import (
    generate_sql,
    interpret_clarification_response,
    repair_sql,
    review_sql,
    generate_answer
)

from app.agents.sql_validator import validate_sql
from app.agents.sql_executor import execute_sql


MAX_SQL_RETRIES = 2
MAX_CLARIFICATION_ROUNDS = 3
MAX_CLARIFICATION_INTERACTIONS = 8


def ask_business_question(question: str):

    original_question = question
    active_question = question
    resolved_question = question

    clarification_rounds = 0
    clarification_interactions = 0

    # ==========================================
    # 1. GENERATE SQL OR REQUEST CLARIFICATION
    # ==========================================

    print("\n[1] Understanding business question...")

    while True:

        print("\n[DEBUG] Resolved Business Question:")
        print(resolved_question)
        
        generation_result = generate_sql(resolved_question)

        if not isinstance(generation_result, dict):
            raise ValueError(
                "generate_sql() must return a dictionary."
            )

        response_status = generation_result.get("status")

        # --------------------------------------
        # CLARIFICATION REQUIRED
        # --------------------------------------

        if response_status == "clarification":

            clarification_rounds += 1

            if clarification_rounds > MAX_CLARIFICATION_ROUNDS:
                raise RuntimeError(
                    "Maximum clarification rounds reached."
                )

            clarification_message = generation_result.get(
                "clarification"
            )

            if not clarification_message:
                raise ValueError(
                    "Clarification message is empty."
                )

            current_clarification = clarification_message

            print("\n[Clarification Required]")
            print(current_clarification)

            # ----------------------------------
            # UNDERSTAND USER RESPONSE
            # ----------------------------------

            while True:

                if clarification_interactions >= MAX_CLARIFICATION_INTERACTIONS:
                    raise RuntimeError(
                        "Maximum clarification interactions reached."
                    )

                user_response = input("\nYour response: ").strip()

                if not user_response:
                    print("[BizPilot] Please provide a response.")
                    continue

                clarification_interactions += 1

                interpretation = interpret_clarification_response(
                    original_question=active_question,
                    clarification_question=current_clarification,
                    user_response=user_response
                )

                intent = interpretation.get("intent")

                # ==============================
                # USER ANSWERED THE QUESTION
                # ==============================

                if intent == "ANSWER":

                    user_answer = interpretation.get("answer")

                    if not user_answer:
                        print(
                            "\n[BizPilot] I couldn't identify "
                            "your answer. Could you clarify?"
                        )
                        continue

                    # Keep both the original response and
                    # the interpreted decision.
                    resolved_question = (
                        f"{resolved_question}\n\n"
                        "AUTHORITATIVE USER CLARIFICATION:\n"
                        f"Original user response: {user_response}\n"
                        f"Interpreted decision: {user_answer}\n"
                        "The user's explicit decision is authoritative. "
                        "Follow it when generating and reviewing SQL. "
                        "Do not override it or ask the same clarification again."
                    )

                    print("\n[BizPilot] Clarification understood.")
                    print("[BizPilot] Updating business question...")

                    break

                # ==============================
                # USER IS CONFUSED
                # ==============================

                elif intent == "CONFUSED":

                    explanation = interpretation.get("explanation")
                    follow_up = interpretation.get("follow_up_question")

                    print("\n[BizPilot Explanation]")
                    print(explanation)

                    if follow_up:
                        print(f"\n[BizPilot] {follow_up}")

                    # Jangan mengubah current_clarification.
                    # Konteks pilihan awal harus tetap dipertahankan.
                    continue

                # ==============================
                # USER ASKED A NEW QUESTION
                # ==============================

                elif intent == "NEW_QUESTION":

                    active_question = user_response
                    resolved_question = user_response

                    print(
                        "\n[BizPilot] Starting a new business question..."
                    )

                    break

                # ==============================
                # RESPONSE IS UNCLEAR
                # ==============================

                elif intent == "UNCLEAR":
                    explanation = interpretation.get("explanation")
                    follow_up = interpretation.get("follow_up_question")

                    print("\n[BizPilot]")
                    print(explanation or "Maaf, saya belum memahami jawabanmu.")

                    if follow_up:
                        print(f"\n[BizPilot] {follow_up}")

                    # Pertahankan current_clarification.
                    # Pengguna masih perlu menjawab klarifikasi awal.
                    continue

                else:
                    raise ValueError(
                        f"Unknown clarification intent: {intent}"
                    )

            # ----------------------------------
            # HANDLE NEW QUESTION OR ANSWER
            # ----------------------------------

            if intent == "NEW_QUESTION":

                clarification_rounds = 0
                clarification_interactions = 0

            # Generate SQL again using the updated context.
            continue

        # --------------------------------------
        # SQL GENERATED
        # --------------------------------------

        elif response_status == "sql":

            current_sql = generation_result.get("sql")

            if not current_sql:
                raise ValueError(
                    "Generated SQL is empty."
                )

            break

        else:
            raise ValueError(
                f"Unknown generation response status: {response_status}"
            )

    # ==========================================
    # 2. REVIEW, VALIDATE, AND EXECUTE SQL
    # ==========================================

    query_result = None
    safe_sql = None

    for attempt in range(MAX_SQL_RETRIES + 1):

        print(f"\nGenerated SQL (Attempt {attempt + 1}):")
        print(current_sql)

        # --------------------------------------
        # SEMANTIC SQL REVIEW
        # --------------------------------------

        print("\n[2] Reviewing SQL business logic...")

        # current_sql = review_sql(
        #     question=resolved_question,
        #     generated_sql=current_sql
        # )

        print("\n[SQL Review Result]")
        print(current_sql)

        # --------------------------------------
        # SECURITY AND STRUCTURAL VALIDATION
        # --------------------------------------

        print("\n[3] Validating SQL...")

        # Validation errors must not be bypassed by
        # automatically asking the LLM to repair unsafe SQL.
        safe_sql = validate_sql(current_sql)

        print("SQL validation successful.")

        # --------------------------------------
        # EXECUTE SQL
        # --------------------------------------

        print("\n[4] Executing SQL...")

        try:

            query_result = execute_sql(safe_sql)

            print("\nQuery result:")
            print(query_result)

            break

        except SQLAlchemyError as error:

            print("\nSQL Execution Error:")
            print(error)

            if attempt >= MAX_SQL_RETRIES:
                raise RuntimeError(
                    f"SQL failed after {MAX_SQL_RETRIES + 1} attempts. "
                    f"Last error: {error}"
                ) from error

            print(
                f"\n[Repair] Asking LLM to fix SQL "
                f"(Retry {attempt + 1}/{MAX_SQL_RETRIES})..."
            )

            current_sql = repair_sql(
                question=resolved_question,
                failed_sql=current_sql,
                error_message=str(error)
            )

            if not current_sql:
                raise RuntimeError(
                    "SQL repair returned an empty query."
                )

            # The repaired SQL will go through:
            # 1. Semantic review
            # 2. SQL validation
            # 3. SQL execution
            # on the next iteration.

    if query_result is None:
        raise RuntimeError(
            "SQL execution did not produce a result."
        )

    # ==========================================
    # 3. GENERATE BUSINESS ANSWER
    # ==========================================

    print("\n[5] Generating business answer...")

    answer = generate_answer(
        resolved_question,
        query_result
    )

    # ==========================================
    # 4. RETURN RESULT
    # ==========================================

    return {
        "question": original_question,
        "resolved_question": resolved_question,
        "sql": safe_sql,
        "result": query_result,
        "answer": answer
    }


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    question = input(
        "Ask your business question: "
    ).strip()

    if not question:

        print("Please enter a business question.")

    else:

        try:

            response = ask_business_question(question)

            print("\n========== BIZPILOT AI ==========")

            print("\nAnswer:")
            print(response["answer"])

            print("\nSQL:")
            print(response["sql"])

        except Exception as error:

            print("\nError:")
            print(error)
