
import sqlglot
from sqlglot import exp


ALLOWED_TABLES = {
    "customers",
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
    "products",
    "sellers",
    "geolocation",
    "product_category_name_translation"
}


FORBIDDEN_EXPRESSIONS = {
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "Command",
    "Into"
}


def contains_aggregate(select_expression):
    """
    Check whether a SELECT projection contains an aggregate function,
    including aggregates nested inside ROUND, CASE, arithmetic, etc.

    Nested SELECT statements are excluded because their aggregation
    does not necessarily make the outer query a scalar aggregate.
    """

    for node in select_expression.walk():

        if isinstance(node, exp.Select):
            continue

        if isinstance(node, exp.AggFunc):
            return True

    return False


def is_scalar_aggregate(query):
    """
    A scalar aggregate has aggregate functions in its outer SELECT
    projections and no outer GROUP BY clause.
    """

    has_group_by = query.args.get("group") is not None

    has_aggregate = any(
        contains_aggregate(projection)
        for projection in query.expressions
    )

    return has_aggregate and not has_group_by


def validate_sql(sql: str) -> str:

    try:
        statements = sqlglot.parse(
            sql,
            read="postgres"
        )

        # ======================================
        # 1. ONLY ONE SQL STATEMENT
        # ======================================

        if len(statements) != 1 or statements[0] is None:
            raise ValueError(
                "Only one SQL statement is allowed."
            )

        query = statements[0]

        # ======================================
        # 2. ONLY SELECT QUERIES
        # ======================================

        if not isinstance(query, exp.Select):
            raise ValueError(
                "Only SELECT queries are allowed."
            )

        # ======================================
        # 3. REJECT FORBIDDEN OPERATIONS
        # ======================================

        for node in query.walk():

            if node.__class__.__name__ in FORBIDDEN_EXPRESSIONS:
                raise ValueError(
                    f"Forbidden SQL operation: "
                    f"{node.__class__.__name__}"
                )

        # ======================================
        # 4. VALIDATE REFERENCED TABLES
        # ======================================

        cte_names = {
            cte.alias_or_name.lower()
            for cte in query.find_all(exp.CTE)
        }

        for table in query.find_all(exp.Table):

            table_name = table.name.lower()

            if (
                table_name not in ALLOWED_TABLES
                and table_name not in cte_names
            ):
                raise ValueError(
                    f"Unauthorized table: {table_name}"
                )

        # ======================================
        # 5. PREVENT SELECT *
        # ======================================

        for select in query.find_all(exp.Select):

            for projection in select.expressions:

                if isinstance(projection, exp.Star):
                    raise ValueError(
                        "SELECT * is not allowed."
                    )

                if (
                    isinstance(projection, exp.Column)
                    and isinstance(projection.this, exp.Star)
                ):
                    raise ValueError(
                        "SELECT table.* is not allowed."
                    )

        # ======================================
        # 6. HANDLE SCALAR AGGREGATE QUERIES
        # ======================================

        scalar_aggregate = is_scalar_aggregate(query)

        if scalar_aggregate:

            # A scalar aggregate should return one aggregated result.
            # Remove unnecessary LIMIT added by the LLM.
            query.set("limit", None)

        else:

            # Add a default LIMIT for row-level or grouped queries.
            if query.args.get("limit") is None:
                query = query.limit(100)

        # ======================================
        # 7. ENFORCE MAXIMUM LIMIT
        # ======================================

        limit = query.args.get("limit")

        if limit is not None:

            limit_value = limit.expression

            if not isinstance(limit_value, exp.Literal):
                raise ValueError(
                    "LIMIT must be a numeric literal."
                )

            if not limit_value.is_int:
                raise ValueError(
                    "LIMIT must be an integer."
                )

            if int(limit_value.this) < 0:
                raise ValueError(
                    "LIMIT cannot be negative."
                )

            if int(limit_value.this) > 100:
                raise ValueError(
                    "Maximum LIMIT is 100."
                )

        # ======================================
        # 8. RETURN VALIDATED SQL
        # ======================================

        return query.sql(dialect="postgres")

    except sqlglot.errors.ParseError as error:

        raise ValueError(
            f"Invalid SQL syntax: {error}"
        ) from error
