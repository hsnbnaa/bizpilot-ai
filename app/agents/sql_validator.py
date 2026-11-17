
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


def is_scalar_aggregate(query):
    """
    A scalar aggregate has only aggregate or constant projections and
    no outer grouping or windowing.
    """

    # Treat only a query whose every outer projection is an aggregate
    # expression (or a literal) as scalar. Windowed aggregates and
    # projections with row-level columns must retain their row limit.
    if (
        query.args.get("group") is not None
        or query.args.get("having") is not None
    ):
        return False

    has_aggregate = False
    for projection in query.expressions:
        aggregates = []
        for node in projection.walk():
            if isinstance(node, exp.Select):
                continue
            if isinstance(node, exp.Window):
                return False
            if isinstance(node, exp.AggFunc):
                aggregates.append(node)
        if aggregates:
            has_aggregate = True
            continue
        # A scalar constant beside an aggregate is still one output row.
        if isinstance(projection, (exp.Literal, exp.Alias)):
            inner = projection.this if isinstance(projection, exp.Alias) else projection
            if isinstance(inner, exp.Literal):
                continue
        return False

    return has_aggregate


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
            schema_name = (table.db or "").lower()
            catalog_name = (table.catalog or "").lower()

            if (
                table_name not in ALLOWED_TABLES
                and table_name not in cte_names
            ):
                raise ValueError(
                    f"Unauthorized table: {table_name}"
                )

            if schema_name not in {"", "public"} or catalog_name:
                raise ValueError("Schema-qualified tables are not allowed.")

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
