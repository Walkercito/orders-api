import pytest

from src.constants import MAX_ROWS
from src.query.sql_guard import UnsafeQueryError, validate_sql

CAP = f"LIMIT {MAX_ROWS}"
NOT_SELECT = "Solo se permiten consultas SELECT"
FORBIDDEN_TABLE = "Tabla no permitida"
NOT_ONE_STATEMENT = "exactamente una sentencia"
NO_DATA = "debe leer al menos una"


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        pytest.param("SELECT * FROM orders", f"SELECT * FROM orders {CAP}", id="orders"),
        pytest.param(
            "SELECT month, total_amount FROM monthly_sales_by_country LIMIT 12",
            "SELECT month, total_amount FROM monthly_sales_by_country LIMIT 12",
            id="monthly-view-keeps-small-limit",
        ),
        pytest.param(
            "select customer from Top_Customers;",
            f"SELECT customer FROM Top_Customers {CAP}",
            id="top-view-any-case",
        ),
        pytest.param(
            "WITH c AS (SELECT * FROM orders) SELECT COUNT(*) FROM c",
            f"WITH c AS (SELECT * FROM orders) SELECT COUNT(*) FROM c {CAP}",
            id="cte",
        ),
        pytest.param(
            "WITH RECURSIVE m(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM m WHERE n < 12) "
            "SELECT n, amount FROM m JOIN orders ON order_id = n",
            "WITH RECURSIVE m(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM m WHERE n < 12) "
            f"SELECT n, amount FROM m JOIN orders ON order_id = n {CAP}",
            id="recursive-cte",
        ),
        pytest.param(
            "WITH a AS (SELECT * FROM b), b AS (SELECT * FROM orders) SELECT * FROM a",
            "WITH a AS (SELECT * FROM b), b AS (SELECT * FROM orders) "
            f"SELECT * FROM a {CAP}",
            id="cte-forward-reference",
        ),
        pytest.param(
            "SELECT country FROM orders UNION SELECT country FROM top_customers",
            f"SELECT country FROM orders UNION SELECT country FROM top_customers {CAP}",
            id="union",
        ),
        pytest.param(
            f"SELECT * FROM orders LIMIT {MAX_ROWS + 1} OFFSET 5",
            f"SELECT * FROM orders {CAP} OFFSET 5",
            id="clamps-large-limit",
        ),
        pytest.param(
            "SELECT * FROM orders LIMIT -1",
            f"SELECT * FROM orders {CAP}",
            id="clamps-negative",
        ),
    ],
)
def test_accepts_read_only_select(sql: str, expected: str) -> None:
    assert validate_sql(sql) == expected


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        pytest.param("DELETE FROM orders", NOT_SELECT, id="delete"),
        pytest.param("DROP TABLE orders", NOT_SELECT, id="drop"),
        pytest.param("UPDATE orders SET amount = 0", NOT_SELECT, id="update"),
        pytest.param("PRAGMA table_info(orders)", NOT_SELECT, id="pragma"),
        pytest.param("ATTACH DATABASE 'x.db' AS x", NOT_SELECT, id="attach"),
        pytest.param("VACUUM", NOT_SELECT, id="vacuum"),
        pytest.param(
            "SELECT * FROM orders; DROP TABLE orders",
            NOT_ONE_STATEMENT,
            id="multi-statement",
        ),
        pytest.param("", NOT_ONE_STATEMENT, id="empty"),
        pytest.param("SELEC * FROM orders", "no se puede analizar", id="parse-error"),
        pytest.param(
            "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
            "no permitida: DELETE",
            id="delete-in-cte",
        ),
        pytest.param(
            "SELECT * INTO copy FROM orders", "no permitida: INTO", id="select-into"
        ),
        pytest.param("SELECT 1 AS tablas, 2 AS vistas", NO_DATA, id="literals-only"),
        pytest.param(
            "SELECT 'orders' UNION SELECT 'top_customers'", NO_DATA, id="literal-union"
        ),
        pytest.param(
            "WITH orders AS (SELECT 1 AS x) SELECT * FROM orders",
            NO_DATA,
            id="cte-named-like-a-table",
        ),
        pytest.param("SELECT * FROM sqlite_master", FORBIDDEN_TABLE, id="sqlite-master"),
        pytest.param("SELECT * FROM customers", FORBIDDEN_TABLE, id="unknown-table"),
        pytest.param("SELECT * FROM main.orders", FORBIDDEN_TABLE, id="schema-qualified"),
        pytest.param(
            "SELECT * FROM pragma_table_info('orders')",
            FORBIDDEN_TABLE,
            id="table-function",
        ),
        pytest.param(
            "SELECT name FROM sqlite_master WHERE name IN "
            "(WITH sqlite_master AS (SELECT 'x') SELECT * FROM sqlite_master)",
            FORBIDDEN_TABLE,
            id="cte-shadows-system-table",
        ),
        pytest.param(
            "SELECT (WITH secret AS (SELECT 1) SELECT 1), * FROM secret",
            FORBIDDEN_TABLE,
            id="cte-out-of-scope",
        ),
        pytest.param(
            "WITH secret AS (SELECT 1) SELECT * FROM main.secret",
            FORBIDDEN_TABLE,
            id="schema-qualified-cte-name",
        ),
    ],
)
def test_rejects_unsafe_sql(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeQueryError, match=reason):
        validate_sql(sql)
