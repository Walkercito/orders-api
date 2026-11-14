"""Pure validation of LLM-written SQL: one read-only SELECT over the allowed tables."""

from typing import Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from src.constants import ALLOWED_TABLES, MAX_ROWS

DIALECT: Final = "sqlite"
# Searched in the whole tree, not only the root: sqlglot parses `SELECT ... INTO` and DML
# inside a CTE as a SELECT.
FORBIDDEN_NODES: Final = (
    exp.DML,
    exp.DDL,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Into,
)


class UnsafeQueryError(ValueError):
    """The SQL must not run. The message gives the reason in Spanish, for the API."""


def validate_sql(sql: str) -> str:
    """Return `sql` with LIMIT added or lowered to MAX_ROWS, or raise UnsafeQueryError."""
    query = _parse_single(sql)
    if not isinstance(query, exp.Select | exp.SetOperation):
        raise UnsafeQueryError("Solo se permiten consultas SELECT.")
    if node := query.find(*FORBIDDEN_NODES):
        raise UnsafeQueryError(f"Operación no permitida: {node.key.upper()}.")
    _check_tables(query)
    return _cap_rows(query).sql(dialect=DIALECT)


def _parse_single(sql: str) -> exp.Expr:
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=DIALECT) if s is not None]
    except SqlglotError as exc:
        raise UnsafeQueryError("El SQL no se puede analizar.") from exc
    if len(statements) != 1:
        raise UnsafeQueryError("Se esperaba exactamente una sentencia SQL.")
    return statements[0]


def _check_tables(query: exp.Expr) -> None:
    for table in query.find_all(exp.Table):
        allowed = table.name.lower() in ALLOWED_TABLES or _is_cte_reference(table)
        if table.db or table.catalog or not allowed:
            raise UnsafeQueryError(f"Tabla no permitida: {table.sql(dialect=DIALECT)}.")


def _is_cte_reference(table: exp.Table) -> bool:
    # Same lexical scope as SQLite: a CTE is visible in the statement that owns its WITH,
    # in every CTE body of that WITH and in nested subqueries, and nowhere else. So a CTE
    # inside a subquery cannot hide an outer reference to a real table with the same name.
    name = table.name.lower()
    node = table.parent
    while node is not None:
        with_ = node.args.get("with_")
        if with_ and any(cte.alias_or_name.lower() == name for cte in with_.expressions):
            return True
        node = node.parent
    return False


def _cap_rows(query: exp.Select | exp.SetOperation) -> exp.Select | exp.SetOperation:
    limit = query.args.get("limit")
    rows = limit.expression if limit else None
    # Keep an integer literal within the cap. Replace anything else: no LIMIT, a negative
    # one (unlimited in SQLite) or an expression.
    if isinstance(rows, exp.Literal) and rows.is_int and int(rows.name) <= MAX_ROWS:
        return query
    return query.limit(MAX_ROWS)
