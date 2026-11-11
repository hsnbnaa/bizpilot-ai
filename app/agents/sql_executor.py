from sqlalchemy import text

from app.database.connection import engine


def execute_sql(sql: str):

    with engine.connect() as connection:

        result = connection.execute(
            text(sql)
        )

        rows = [
            dict(row)
            for row in result.mappings().fetchall()
        ]

        return {
            "columns": list(result.keys()),
            "row_count": len(rows),
            "data": rows
        }