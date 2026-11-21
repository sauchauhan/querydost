# ============================================================
# database.py | EVERYTHING THAT TALKS TO THE DATABASE
# ============================================================
#
# The model NEVER touches the database. It asks a tool, the tool calls
# the functions below, and these functions follow the rules from .env.
#
# What is in here:
#   get_engine(for_agent)   → the agent's READ login, or the APPROVER's write login
#   get_dialect_name()      → "PostgreSQL", "SQLite"... so the model writes the right SQL flavour
#   list_tables()           → every table / view the agent may use (found automatically)
#   describe_table(name)    → columns, types, keys, joins, comments, sample rows
#   check_read_sql(sql)     → Python safety check: is this ONE SELECT and nothing else?
#   run_read_query(sql)     → runs a SELECT inside a transaction that is ALWAYS rolled back
#   check_change_sql(sql)   → safety check for a proposed INSERT / UPDATE / DELETE
#   run_approved_change(sql)→ runs a change with the APPROVER login, only after a human clicked Approve
#   write_audit(...)        → one line per event in audit_log.txt
#
# SQLAlchemy is the library that lets ONE piece of code talk to SQLite,
# PostgreSQL, MySQL, SQL Server, Oracle and more. You give it a URL, it does the rest.
# sqlglot is a library that READS SQL like a compiler does, so we can check
# what a query really does instead of just looking at its first word.
# ============================================================

import re
import sqlite3
from datetime import datetime
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlalchemy import create_engine, inspect, text, select, event
from sqlalchemy import table as sa_table, column as sa_column
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

import connection
import settings


# ============================================================
# 1. CONNECTIONS
# ============================================================
# ENGINES → we create each engine once and reuse it (an engine manages connections)
ENGINES = {}


# SQLite has no logins, so we copy the idea: the agent opens the file READ-ONLY.
# .as_uri()  → "file:///D:/.../hr_company.db", the safe way to pass a path with spaces
# "?mode=ro" → SQLite itself refuses every write on this connection
def make_sqlite_engine(file_path, read_only):
    file_uri = Path(file_path).resolve().as_uri()
    if read_only:
        file_uri = file_uri + "?mode=ro"

    def connect():
        return sqlite3.connect(file_uri, uri=True, check_same_thread=False)

    return create_engine("sqlite://", creator=connect, poolclass=NullPool)


# ------------------------------------------------------------
# SCHEMA AND ROLE: run once on every new connection
#   PostgreSQL → SET search_path (default schema) and SET ROLE
#   Oracle     → ALTER SESSION SET CURRENT_SCHEMA
#   SQL Server / MySQL → the login's default schema / the database name decides
#   Snowflake  → role and schema are already in the URL
# Names are checked first: letters, digits, _ and $ only, so nothing can be injected.
# ------------------------------------------------------------
def is_safe_name(name):
    return re.match(r"^[A-Za-z0-9_$]+$", name) is not None


def session_setup_commands(backend, schemas, role):
    names = list(schemas) + [role]
    for i in range(len(names)):
        if names[i] != "" and not is_safe_name(names[i]):
            raise ValueError("Schema or role name '" + names[i] + "' has unusual characters. "
                             "Use letters, digits and _ only.")
    commands = []
    if backend == "postgresql":
        if len(schemas) > 0:
            commands.append("SET search_path TO " + ", ".join(schemas) + ", public")
        if role != "":
            commands.append("SET ROLE " + role)
    if backend == "oracle" and len(schemas) > 0:
        commands.append("ALTER SESSION SET CURRENT_SCHEMA = " + schemas[0])
    return commands


# event.listens_for(engine, "connect") → "run this function every time a NEW connection opens"
# dbapi_connection.commit() → save the SET, or the next rollback would undo it
# schemas / role default to the saved settings; the connection screen passes its own
def add_session_setup(engine, schemas=None, role=None):
    if schemas is None:
        schemas = settings.SCHEMAS
    if role is None:
        role = settings.DB_ROLE
    commands = session_setup_commands(engine.dialect.name, schemas, role)
    if len(commands) == 0:
        return

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        for i in range(len(commands)):
            cursor.execute(commands[i])
        cursor.close()
        dbapi_connection.commit()


# Forget every engine and cached description (after the connection settings change)
def reset():
    ENGINES.clear()
    CACHE.clear()


# for_agent=True  → the agent's login (DATABASE_URL). Used for every question.
# for_agent=False → the approver's login. Used ONLY after a human clicked Approve.
def get_engine(for_agent):
    key = "agent" if for_agent else "approver"
    if key in ENGINES:
        return ENGINES[key]

    url = make_url(settings.DATABASE_URL)
    if url.get_backend_name() == "sqlite":
        engine = make_sqlite_engine(url.database, read_only=for_agent)
    elif for_agent:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    else:
        if settings.APPROVER_DATABASE_URL == "":
            raise ValueError("No APPROVER_DATABASE_URL in .env, so changes cannot be saved. "
                             "Ask your DBA for a separate login that may write, and add it.")
        engine = create_engine(settings.APPROVER_DATABASE_URL, pool_pre_ping=True)

    add_session_setup(engine)
    ENGINES[key] = engine
    return engine


# ------------------------------------------------------------
# TEST A CONNECTION (used by the connection screen)
# Returns {"ok": True/False, "message": "...", "tables": number}
# Opens its OWN short-lived connection, so nothing is cached or changed.
# ------------------------------------------------------------
def test_connection(url, db_type, schemas, role):
    result = {"ok": False, "message": "", "tables": 0}
    try:
        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite":
            if not Path(parsed.database).exists():
                result["message"] = "The SQLite file was not found: " + str(parsed.database)
                return result
            engine = make_sqlite_engine(parsed.database, read_only=True)
        else:
            engine = create_engine(url, poolclass=NullPool)
        add_session_setup(engine, schemas, role)
        with engine.connect() as conn:
            inspector = inspect(conn)
            if len(schemas) == 0:
                schemas = []
                all_schemas = inspector.get_schema_names()
                for i in range(len(all_schemas)):
                    if not is_system_schema(all_schemas[i]):
                        schemas.append(all_schemas[i])
            count = 0
            for s in range(len(schemas)):
                try:
                    count = count + len(inspector.get_table_names(schema=schemas[s]))
                    count = count + len(inspector.get_view_names(schema=schemas[s]))
                except Exception:
                    pass
        engine.dispose()
        result["ok"] = True
        result["tables"] = count
        result["message"] = "Connected. Found " + str(count) + " tables and views."
        if count == 0:
            result["message"] = ("Connected, but this login can see 0 tables. Ask your DBA to grant "
                                 "SELECT on the tables or views you need, or check the Schemas field.")
    except Exception as error:
        result["message"] = connection.friendly_error(db_type, error)
        result["details"] = str(error)
    return result


# The URL with the password hidden, safe to show on screen
def get_safe_url():
    return make_url(settings.DATABASE_URL).render_as_string(hide_password=True)


# ============================================================
# 2. WHICH SQL "FLAVOUR" DOES THIS DATABASE SPEAK?
# ============================================================
# SQL Server says "SELECT TOP 10", most others say "LIMIT 10". We tell the model which.
FRIENDLY_NAMES = {"sqlite": "SQLite", "postgresql": "PostgreSQL", "mysql": "MySQL",
                  "mariadb": "MariaDB", "mssql": "Microsoft SQL Server (T-SQL)",
                  "oracle": "Oracle", "snowflake": "Snowflake", "duckdb": "DuckDB"}

# the names sqlglot uses for the same databases
SQLGLOT_NAMES = {"sqlite": "sqlite", "postgresql": "postgres", "mysql": "mysql",
                 "mariadb": "mysql", "mssql": "tsql", "oracle": "oracle",
                 "snowflake": "snowflake", "duckdb": "duckdb"}


def get_backend():
    return get_engine(for_agent=True).dialect.name


def get_dialect_name():
    return FRIENDLY_NAMES.get(get_backend(), get_backend())


def get_sqlglot_dialect():
    return SQLGLOT_NAMES.get(get_backend(), None)


# ============================================================
# 3. FIND THE TABLES AUTOMATICALLY
# ============================================================
# inspect(engine) → asks the database itself: which schemas, tables, columns, keys exist?
# Tables in the default schema keep their plain name ("employees").
# Tables in other schemas get "schema.table" ("sales.customer").
SYSTEM_SCHEMAS = ["information_schema", "pg_catalog", "pg_toast", "sys", "guest",
                  "mysql", "performance_schema", "crdb_internal"]

# CACHE → describing tables is slow on big databases, so we remember the answers
CACHE = {}


def clear_cache():
    CACHE.clear()


def is_system_schema(schema):
    name = schema.lower()
    if name in SYSTEM_SCHEMAS:
        return True
    return name.startswith("pg_") or name.startswith("db_")


def is_allowed(full_name):
    if len(settings.ALLOWED_TABLES) == 0:
        return True
    bare_name = full_name.split(".")[-1]
    for i in range(len(settings.ALLOWED_TABLES)):
        allowed = settings.ALLOWED_TABLES[i].lower()
        if allowed == full_name.lower() or allowed == bare_name.lower():
            return True
    return False


def list_tables():
    if "tables" in CACHE:
        return CACHE["tables"]

    inspector = inspect(get_engine(for_agent=True))
    default_schema = inspector.default_schema_name

    if len(settings.SCHEMAS) > 0:
        schemas = settings.SCHEMAS
    else:
        schemas = []
        all_schemas = inspector.get_schema_names()
        for i in range(len(all_schemas)):
            if not is_system_schema(all_schemas[i]):
                schemas.append(all_schemas[i])

    names = []
    for s in range(len(schemas)):
        schema = schemas[s]
        # try / except → skip a schema this login is not allowed to read
        try:
            found = inspector.get_table_names(schema=schema) + inspector.get_view_names(schema=schema)
        except Exception:
            continue
        for t in range(len(found)):
            if schema == default_schema:
                full_name = found[t]
            else:
                full_name = schema + "." + found[t]
            if is_allowed(full_name):
                names.append(full_name)

    names.sort()
    CACHE["tables"] = names
    return names


# "sales.customer" → ("sales", "customer").   "employees" → (None, "employees")
def split_name(full_name):
    if "." in full_name:
        parts = full_name.split(".", 1)
        return parts[0], parts[1]
    return None, full_name


# Find the real name, whatever case the model typed it in
def find_table(name):
    tables = list_tables()
    for i in range(len(tables)):
        if tables[i].lower() == name.strip().lower():
            return tables[i]
    return None


# Long text in sample rows wastes tokens. Keep the first 60 characters.
def short_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    value = str(value)
    if len(value) > 60:
        return value[:60] + "..."
    return value


# ============================================================
# 4. DESCRIBE ONE TABLE FOR THE MODEL
# ============================================================
# Example of what the model receives:
#   Table sales.customer  (Current customer information)
#   Columns:
#     - customerid INTEGER  PRIMARY KEY
#     - territoryid INTEGER  -- ID of the territory
#   Joins:
#     - sales.customer.territoryid = sales.salesterritory.territoryid
#   Sample rows:
#     (1, 1, ...)
def describe_table(full_name):
    cache_key = "describe:" + full_name
    if cache_key in CACHE:
        return CACHE[cache_key]

    engine = get_engine(for_agent=True)
    inspector = inspect(engine)
    schema, name = split_name(full_name)

    # ---- table comment (not every database has comments) ----
    title = "Table " + full_name
    try:
        comment = inspector.get_table_comment(name, schema=schema).get("text")
        if comment:
            title = title + "  (" + comment + ")"
    except Exception:
        pass
    lines = [title, "Columns:"]

    # ---- columns, types, primary key ----
    key_columns = []
    try:
        key_columns = inspector.get_pk_constraint(name, schema=schema).get("constrained_columns") or []
    except Exception:
        pass
    # SQLAlchemy can silently SKIP columns with a custom type (e.g. AdventureWorks "Name").
    # So we also ask the database's own catalog, which lists EVERY column, and merge.
    columns = inspector.get_columns(name, schema=schema)
    catalog = get_catalog_columns(schema, name, inspector.default_schema_name)
    columns = merge_columns(columns, catalog)
    column_names = []
    for c in range(len(columns)):
        column = columns[c]
        column_names.append(column["name"])
        try:
            type_text = str(column["type"])
        except Exception:
            type_text = "NULL"
        if type_text == "NULL":
            type_text = catalog_type(catalog, column["name"])
        line = "  - " + column["name"] + " " + type_text
        if column["name"] in key_columns:
            line = line + "  PRIMARY KEY"
        if column.get("comment"):
            line = line + "  -- " + column["comment"]
        lines.append(line)

    # ---- joins (foreign keys): the model's map for correct JOINs ----
    try:
        foreign_keys = inspector.get_foreign_keys(name, schema=schema)
    except Exception:
        foreign_keys = []
    if len(foreign_keys) > 0:
        lines.append("Joins:")
    for f in range(len(foreign_keys)):
        fk = foreign_keys[f]
        other_table = fk["referred_table"]
        if fk.get("referred_schema"):
            other_table = fk["referred_schema"] + "." + other_table
        for k in range(len(fk["constrained_columns"])):
            lines.append("  - " + full_name + "." + fk["constrained_columns"][k] + " = "
                         + other_table + "." + fk["referred_columns"][k])

    # ---- sample rows ----
    # sa_table / sa_column → describe the table by NAME only (no reading of types),
    # so custom-type columns are included and SQLAlchemy still writes LIMIT or TOP for us.
    # Binary / XML / spatial columns are skipped: no use to the model, and some drivers cannot read them.
    if settings.SAMPLE_ROWS > 0:
        try:
            sample_columns = []
            for c in range(len(column_names)):
                if catalog_type(catalog, column_names[c]) not in SKIP_IN_SAMPLES:
                    sample_columns.append(sa_column(column_names[c]))
            sample_table = sa_table(name, *sample_columns, schema=schema)
            with engine.connect() as conn:
                rows = conn.execute(select(*sample_columns).select_from(sample_table)
                                    .limit(settings.SAMPLE_ROWS)).fetchall()
                conn.rollback()
            sampled_names = []
            for c in range(len(sample_columns)):
                sampled_names.append(sample_columns[c].name)
            if len(rows) > 0:
                lines.append("Sample rows (" + ", ".join(sampled_names) + "):")
            for r in range(len(rows)):
                values = []
                for v in range(len(rows[r])):
                    values.append(short_value(rows[r][v]))
                lines.append("  " + str(tuple(values)))
        except Exception:
            lines.append("(Sample rows not available for this table.)")

    result = "\n".join(lines)
    CACHE[cache_key] = result
    return result


# INFORMATION_SCHEMA.COLUMNS → a standard view (SQL Server, PostgreSQL, MySQL) listing
# EVERY column in order, with its BASE type (e.g. nvarchar for a custom "Name" type).
# SQLite does not have it, so there we simply get an empty list.
def get_catalog_columns(schema, name, default_schema):
    found = []
    sql = ("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
           "WHERE TABLE_NAME = :table_name AND TABLE_SCHEMA = :schema_name ORDER BY ORDINAL_POSITION")
    try:
        with get_engine(for_agent=True).connect() as conn:
            rows = conn.execute(text(sql), {"table_name": name,
                                            "schema_name": schema or default_schema}).fetchall()
            conn.rollback()
        for r in range(len(rows)):
            found.append({"name": str(rows[r][0]), "type": str(rows[r][1]).upper()})
    except Exception:
        pass
    return found


SKIP_IN_SAMPLES = ["XML", "GEOGRAPHY", "GEOMETRY", "HIERARCHYID", "VARBINARY", "BINARY",
                   "IMAGE", "TIMESTAMP", "ROWVERSION", "BYTEA", "BLOB", "LONGBLOB"]


def catalog_type(catalog, column_name):
    for i in range(len(catalog)):
        if catalog[i]["name"] == column_name:
            return catalog[i]["type"]
    return "CUSTOM TYPE"


# Keep the database's column ORDER, use SQLAlchemy's details where it has them,
# and add back every column SQLAlchemy skipped.
def merge_columns(inspected, catalog):
    if len(catalog) == 0:
        return inspected
    by_name = {}
    for i in range(len(inspected)):
        by_name[inspected[i]["name"]] = inspected[i]
    merged = []
    for i in range(len(catalog)):
        column_name = catalog[i]["name"]
        if column_name in by_name:
            merged.append(by_name[column_name])
        else:
            merged.append({"name": column_name, "type": catalog[i]["type"], "comment": None})
    return merged


# "full" or "lookup" (see SCHEMA_MODE in .env)
def get_schema_mode():
    if settings.SCHEMA_MODE in ["full", "lookup"]:
        return settings.SCHEMA_MODE
    if len(list_tables()) <= settings.FULL_SCHEMA_MAX_TABLES:
        return "full"
    return "lookup"


def get_full_schema_text():
    tables = list_tables()
    parts = []
    for i in range(len(tables)):
        parts.append(describe_table(tables[i]))
    return "\n\n".join(parts)


# ============================================================
# 5. PYTHON SAFETY CHECK FOR READ QUERIES
# ============================================================
# Returns "" if the SQL is safe, otherwise the reason it was blocked.
#
# Why parse instead of checking the first word?
#   "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x"
#   starts with WITH, looks harmless, and deletes data in PostgreSQL.
#   sqlglot reads the whole query and finds the DELETE hidden inside.
#
# getattr(exp, "Name", None) → use the class if this sqlglot version has it
def sqlglot_classes(names):
    found = []
    for i in range(len(names)):
        one_class = getattr(exp, names[i], None)
        if one_class is not None:
            found.append(one_class)
    return tuple(found)


READ_TYPES = sqlglot_classes(["Query", "Select", "Union", "Intersect", "Except", "Subquery"])
WRITE_TYPES = sqlglot_classes(["Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter",
                               "AlterTable", "TruncateTable", "Command", "Into", "Grant"])


def parse_one_statement(sql):
    statements = sqlglot.parse(sql, read=get_sqlglot_dialect())
    real_statements = []
    for i in range(len(statements)):
        if statements[i] is not None:
            real_statements.append(statements[i])
    return real_statements


# Backup check, used only if sqlglot cannot read this SQL.
# It is stricter on purpose: any data-changing word anywhere blocks the query.
# re.search(r"\bDELETE\b", ...) → finds DELETE as a whole word (not inside "deleted_at")
WRITE_WORDS = ["INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "TRUNCATE",
               "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "INTO", "CALL"]


def simple_read_check(cleaned):
    if ";" in cleaned:
        return "Only ONE SQL statement is allowed at a time"
    first_word = cleaned.split()[0].upper()
    if first_word != "SELECT" and first_word != "WITH":
        return "Only SELECT queries are allowed. Got: " + first_word
    for i in range(len(WRITE_WORDS)):
        if re.search(r"\b" + WRITE_WORDS[i] + r"\b", cleaned.upper()):
            return "The query contains " + WRITE_WORDS[i] + ", which is not allowed"
    return ""


def check_read_sql(sql):
    cleaned = sql.strip().rstrip(";").strip()
    if cleaned == "":
        return "Empty query"

    try:
        statements = parse_one_statement(cleaned)
    except Exception as error:
        write_audit("sqlglot could not read query, using backup check", cleaned, str(error).split("\n")[0])
        return simple_read_check(cleaned)

    if len(statements) != 1:
        return "Only ONE SQL statement is allowed at a time"
    statement = statements[0]

    if not isinstance(statement, READ_TYPES):
        return "Only SELECT queries are allowed. Got: " + statement.key.upper()

    # .find(...) → search the WHOLE query tree for any data-changing piece
    hidden_write = statement.find(*WRITE_TYPES)
    if hidden_write is not None:
        return "The query contains a data change (" + hidden_write.key.upper() + ")"

    return check_tables_in_query(statement)


# If ALLOWED_TABLES is set, a query may only touch those tables.
# Names defined inside the query with WITH (CTEs) are fine.
def check_tables_in_query(statement):
    if len(settings.ALLOWED_TABLES) == 0:
        return ""
    cte_names = []
    ctes = list(statement.find_all(exp.CTE))
    for i in range(len(ctes)):
        cte_names.append(ctes[i].alias.lower())

    tables = list(statement.find_all(exp.Table))
    for i in range(len(tables)):
        name = tables[i].name
        if tables[i].db:
            name = tables[i].db + "." + name
        if name.lower() in cte_names:
            continue
        if not is_allowed(name):
            return "Table " + name + " is not in ALLOWED_TABLES"
    return ""


# ============================================================
# 6. RUN A READ QUERY AS THE AGENT
# ============================================================
# Every read runs inside a transaction that is ROLLED BACK at the end, so even a
# write that slips past every other check is undone. On top of that:
#   PostgreSQL → the transaction is marked READ ONLY + a statement timeout
#   MySQL      → the session is READ ONLY + a statement timeout
#   SQLite     → the file is opened read-only
#   others     → the database login's permissions (ask your DBA for a read-only user)
def apply_read_guards(conn):
    backend = get_backend()
    milliseconds = str(settings.QUERY_TIMEOUT_SECONDS * 1000)
    commands = []
    if backend == "postgresql":
        commands = ["SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = " + milliseconds]
    if backend == "mysql":
        commands = ["SET SESSION TRANSACTION READ ONLY", "SET SESSION MAX_EXECUTION_TIME = " + milliseconds]
    if backend == "mariadb":
        commands = ["SET SESSION TRANSACTION READ ONLY",
                    "SET SESSION max_statement_time = " + str(settings.QUERY_TIMEOUT_SECONDS)]
    for i in range(len(commands)):
        try:
            conn.exec_driver_sql(commands[i])
        except Exception:
            pass
    # MySQL applies READ ONLY to the NEXT transaction, so start a fresh one
    if backend in ["mysql", "mariadb"]:
        conn.rollback()


# text() would treat ":word" inside the SQL as a parameter. "\:" means "a real colon".
def as_sql_text(sql):
    return text(sql.replace(":", "\\:"))


# Turn values the screen and the model cannot handle (Decimal, UUID, bytes) into text
def plain_value(value):
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


# Returns {"ok": True/False, "columns": [...], "rows": [...], "truncated": True/False, "error": "..."}
# skip_code_check=True → used ONLY by the Guardrail tester, to prove the database's own lock works
def run_read_query(sql, skip_code_check=False):
    result = {"ok": False, "columns": [], "rows": [], "truncated": False, "error": ""}

    if settings.CHECK_SQL_IN_CODE and not skip_code_check:
        problem = check_read_sql(sql)
        if problem != "":
            result["error"] = "Blocked by Python safety check: " + problem
            write_audit("BLOCKED by code check", sql, problem)
            return result

    conn = None
    try:
        conn = get_engine(for_agent=True).connect()
        apply_read_guards(conn)
        cursor = conn.execute(as_sql_text(sql))
        if not cursor.returns_rows:
            result["error"] = "This statement does not return rows. Nothing was saved."
            write_audit("NO ROWS (rolled back)", sql)
            return result
        result["columns"] = list(cursor.keys())
        rows = cursor.fetchmany(settings.MAX_ROWS + 1)
    except Exception as error:
        result["error"] = "Database refused: " + str(error).split("\n")[0]
        write_audit("DATABASE ERROR", sql, result["error"])
        return result
    finally:
        # ALWAYS undo, ALWAYS close. Even a successful read is rolled back.
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()

    for r in range(len(rows)):
        if r < settings.MAX_ROWS:
            values = []
            for v in range(len(rows[r])):
                values.append(plain_value(rows[r][v]))
            result["rows"].append(tuple(values))
    result["truncated"] = len(rows) > settings.MAX_ROWS
    result["ok"] = True
    write_audit("READ OK", sql, str(len(result["rows"])) + " rows")
    return result


# ============================================================
# 7. SAFETY CHECK FOR PROPOSED CHANGES
# ============================================================
CHANGE_NAMES = {"insert": "INSERT", "update": "UPDATE", "delete": "DELETE"}


def check_change_sql(sql):
    cleaned = sql.strip().rstrip(";").strip()
    if cleaned == "":
        return "Empty statement"
    try:
        statements = parse_one_statement(cleaned)
    except Exception:
        return "QueryDost could not read this statement, so it will not run it"
    if len(statements) != 1:
        return "Only ONE SQL statement is allowed at a time"
    statement = statements[0]

    change_type = CHANGE_NAMES.get(statement.key, statement.key.upper())
    if change_type not in ["INSERT", "UPDATE", "DELETE"]:
        return change_type + " is never allowed from the chatbot"
    if change_type not in settings.ALLOWED_CHANGE_TYPES:
        return change_type + " is not allowed. Allowed: " + ", ".join(settings.ALLOWED_CHANGE_TYPES)

    # An UPDATE or DELETE without WHERE changes EVERY row. Classic disaster.
    if change_type in ["UPDATE", "DELETE"] and statement.args.get("where") is None:
        return change_type + " without a WHERE clause would change every row"
    return ""


# ============================================================
# 8. RUN A CHANGE AS THE APPROVER (only after a human clicked Approve)
# ============================================================
# engine.begin() → opens a transaction and SAVES it (commit) at the end of the "with" block
# .rowcount      → how many rows were changed
def run_approved_change(sql, approved_by="human"):
    problem = check_change_sql(sql)
    if problem != "":
        write_audit("CHANGE BLOCKED", sql, problem)
        raise ValueError(problem)
    with get_engine(for_agent=False).begin() as conn:
        rows_changed = conn.execute(as_sql_text(sql)).rowcount
    write_audit("CHANGE APPROVED + SAVED", sql, "by " + approved_by + ", rows changed: " + str(rows_changed))
    return rows_changed


# ============================================================
# 9. AUDIT LOG
# ============================================================
# One line per event:  2026-11-17 18:05:12 | READ OK | SELECT dept, COUNT(*) ... | 7 rows
def write_audit(event, sql, detail=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    one_line_sql = " ".join(sql.split())
    line = timestamp + " | " + event + " | " + one_line_sql + " | " + detail + "\n"
    with open(settings.AUDIT_LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(line)
