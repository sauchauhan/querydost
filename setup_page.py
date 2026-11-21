# ============================================================
# setup_page.py | THE "CONNECT YOUR DATABASE" SCREEN
# ============================================================
#
# Fill in boxes, click Test, click Save. No URLs, no editing .env by hand.
#
#   1. YOUR DATABASE → type, server, database, login, optional schemas / role
#                      "Test connection" says in plain English what is wrong
#   2. YOUR AI MODEL → provider, model, key. "Test model" sends one tiny message.
#   3. SAVE          → writes QueryDost's own .env file and restarts the agent
#
# app.py shows this screen on first run, when the connection fails,
# or when you click "Change database or model" in the sidebar.
# ============================================================

import importlib
import os

import streamlit as st
from dotenv import load_dotenv

import agent
import connection
import database
import settings


# ------------------------------------------------------------
# AI providers the screen knows. Anything else: edit .env by hand (see .env.example).
#   keys    → the settings this provider needs, with a label and a default
#   package → extra pip package, if any
# ------------------------------------------------------------
PROVIDERS = {
    "openai": {"label": "OpenAI", "model": "gpt-6.1-sol", "package": "",
               "keys": [("OPENAI_API_KEY", "API key", "")]},
    "azure_openai": {"label": "Azure OpenAI (your company's deployment)", "model": "your-deployment-name",
                     "package": "",
                     "keys": [("AZURE_OPENAI_API_KEY", "API key", ""),
                              ("AZURE_OPENAI_ENDPOINT", "Endpoint, e.g. https://name.openai.azure.com/", ""),
                              ("OPENAI_API_VERSION", "API version", "2024-10-21")]},
    "anthropic": {"label": "Claude (Anthropic)", "model": "claude-sonnet-5-5", "package": "langchain-anthropic",
                  "keys": [("ANTHROPIC_API_KEY", "API key", "")]},
    "groq": {"label": "Groq", "model": "llama-3.3-70b-versatile", "package": "langchain-groq",
             "keys": [("GROQ_API_KEY", "API key", "")]},
}

SECRET_WORDS = ["KEY", "PASSWORD"]


# ============================================================
# WRITING THE .env FILE
# ============================================================
# Keeps every comment and every other line. Replaces "KEY=..." lines it owns,
# and adds the ones that are missing at the end.
# Values are written in double quotes, so # @ and spaces in passwords are safe.
def quote_value(value):
    value = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"' + value + '"'


def update_env_file(updates):
    lines = []
    if settings.ENV_FILE.exists():
        lines = settings.ENV_FILE.read_text(encoding="utf-8").splitlines()

    done = []
    for i in range(len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            lines[i] = key + "=" + quote_value(updates[key])
            done.append(key)

    new_lines = []
    for key in updates:
        if key not in done:
            new_lines.append(key + "=" + quote_value(updates[key]))
    if len(new_lines) > 0:
        lines.append("")
        lines.append("# Saved by the QueryDost connection screen")
        lines = lines + new_lines

    settings.ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# After saving: load the new values, re-read settings, forget old connections
def reload_everything():
    load_dotenv(settings.ENV_FILE, override=True)
    importlib.reload(settings)
    database.reset()
    for key in ["agent", "tables"]:
        if key in st.session_state:
            del st.session_state[key]


# ============================================================
# IS THE MODEL SET UP? (used by app.py on first run)
# ============================================================
def model_key_missing():
    provider = settings.LLM_MODEL.split(":", 1)[0]
    if provider not in PROVIDERS:
        return False
    first_key = PROVIDERS[provider]["keys"][0][0]
    return os.getenv(first_key, "").strip() in ["", "sk-..."]


def friendly_model_error(provider, error):
    text = str(error)
    lower = text.lower()
    if "no module named" in lower:
        package = PROVIDERS.get(provider, {}).get("package", "")
        if package == "":
            return "A package is missing: " + text.split("\n")[0]
        return "A package is missing. Run:  pip install " + package
    if ("401" in lower or "api key" in lower or "api_key" in lower or "authentication" in lower
            or "unauthorized" in lower):
        return "The API key was rejected. Copy it again from your provider's dashboard."
    if "deploymentnotfound" in lower or ("deployment" in lower and "not found" in lower):
        return "Azure could not find that deployment. The model name must be your DEPLOYMENT name from Azure."
    if "404" in lower or "model_not_found" in lower or "does not exist" in lower:
        return "This key cannot use that model. Check the model name, or pick a model your account has."
    if "connect" in lower or "resolve" in lower:
        return "Could not reach the provider. Check the endpoint address and your internet / VPN."
    return "The model did not answer: " + text.split("\n")[0][:300]


# ============================================================
# THE SCREEN
# ============================================================
def show(reason="", details=""):
    st.title("🔌 Connect QueryDost")
    st.caption("Fill in the boxes, test, save. QueryDost writes the settings to its own .env file for you.")
    if reason != "":
        st.error(reason)
    if details != "":
        with st.expander("Technical details (for your DBA)"):
            st.code(details[:2000])

    parts = show_database_section()
    st.divider()
    model_name, model_keys = show_model_section()
    st.divider()
    show_save_section(parts, model_name, model_keys)


# ------------------------------------------------------------
# 1. DATABASE
# ------------------------------------------------------------
def show_database_section():
    st.header("1. Your database")
    if settings.DB_PARTS["type"] == "" and not settings.DATABASE_URL.startswith("sqlite"):
        st.info("You are using a DATABASE_URL from .env. The boxes below are filled in from it. "
                "Saving here switches to the boxes.")

    # Pre-fill the boxes: from the plain fields if set, otherwise from the DATABASE_URL
    current = settings.DB_PARTS
    if current["type"] == "":
        current = connection.parts_from_url(settings.DATABASE_URL)
        if current["schema"] == "":
            current["schema"] = settings.DB_PARTS["schema"]

    type_keys = list(connection.DB_TYPES)
    current_type = current["type"] if current["type"] in type_keys else "sqlite"
    db_type = st.selectbox("Database type", type_keys, index=type_keys.index(current_type),
                           format_func=lambda key: connection.DB_TYPES[key]["label"])
    info = connection.DB_TYPES[db_type]
    parts = {"type": db_type}

    if db_type == "sqlite":
        parts["file"] = st.text_input("File path", current["file"] or "demo/hr_company.db",
                                      help="Relative paths start from the QueryDost folder.")
        parts["schema"] = ""
        parts["role"] = ""
        return parts

    left, right = st.columns([3, 1])
    host_label = "Snowflake account (e.g. xy12345.eu-west-1)" if db_type == "snowflake" else "Server / host"
    parts["host"] = left.text_input(host_label, current["host"],
                                    help="For a SQL Server named instance: SERVER\\INSTANCE (leave port blank)")
    if db_type != "snowflake":
        parts["port"] = right.text_input("Port", current["port"], placeholder=info["port"])

    name_label = "Service name" if db_type == "oracle" else "Database name"
    parts["name"] = st.text_input(name_label, current["name"])

    if db_type == "sqlserver":
        parts["windows_login"] = st.checkbox("Use my Windows login (no username / password)",
                                             value=current["windows_login"])
    if not parts.get("windows_login", False):
        left, right = st.columns(2)
        parts["user"] = left.text_input("Username", current["user"],
                                        help="Use a READ-ONLY login. Ask your DBA for one.")
        parts["password"] = right.text_input("Password", current["password"], type="password",
                                             help="Any characters are fine, including @ # / :")

    with st.expander("Optional: schemas, role, driver"):
        parts["schema"] = st.text_input("Schemas (comma separated, blank = all)", current["schema"],
                                        help="Only tables in these schemas are shown to the AI. "
                                             "PostgreSQL and Oracle also use the first one as the default.")
        parts["role"] = ""
        if db_type in ["postgres", "snowflake"]:
            parts["role"] = st.text_input("Role (blank = the login's default role)", current["role"])
        if db_type == "snowflake":
            parts["warehouse"] = st.text_input("Warehouse", current["warehouse"])
        if db_type == "sqlserver":
            parts["odbc_driver"] = st.text_input("ODBC driver", current["odbc_driver"] or
                                                 connection.DEFAULT_SQLSERVER_DRIVER)
            show_installed_odbc_drivers()

    if info["package"] != "":
        st.caption("Needs the Python package: pip install " + info["package"])

    if st.button("🔍 Test connection"):
        run_database_test(parts)
    return parts


# pyodbc.drivers() → the ODBC drivers installed on this computer
def show_installed_odbc_drivers():
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        sql_drivers = []
        for i in range(len(drivers)):
            if "SQL Server" in drivers[i]:
                sql_drivers.append(drivers[i])
        st.caption("SQL Server drivers on this computer: " + (", ".join(sql_drivers) or "none found"))
    except Exception:
        st.caption("pyodbc is not installed yet: pip install pyodbc")


def schemas_list(text_value):
    items = []
    pieces = text_value.split(",")
    for i in range(len(pieces)):
        if pieces[i].strip() != "":
            items.append(pieces[i].strip())
    return items


def run_database_test(parts):
    try:
        url = settings.fix_sqlite_path(connection.build_url(parts))
    except ValueError as error:
        st.error(str(error))
        return False
    with st.spinner("Connecting..."):
        result = database.test_connection(url, parts["type"], schemas_list(parts.get("schema", "")),
                                          parts.get("role", ""))
    if result["ok"] and result["tables"] > 0:
        st.success("✅ " + result["message"])
    elif result["ok"]:
        st.warning("⚠️ " + result["message"])
    else:
        st.error("❌ " + result["message"])
        if result.get("details", "") != "":
            with st.expander("Technical details (for your DBA)"):
                st.code(result["details"][:2000])
    return result["ok"]


# ------------------------------------------------------------
# 2. MODEL
# ------------------------------------------------------------
def show_model_section():
    st.header("2. Your AI model")
    provider_keys = list(PROVIDERS)
    current_provider = settings.LLM_MODEL.split(":", 1)[0]
    current_model = settings.LLM_MODEL.split(":", 1)[1] if ":" in settings.LLM_MODEL else ""
    if current_provider not in provider_keys:
        st.info("Your .env uses " + settings.LLM_MODEL + ". To keep it, edit .env by hand instead of saving here.")
        current_provider = "openai"

    provider = st.selectbox("Provider", provider_keys, index=provider_keys.index(current_provider),
                            format_func=lambda key: PROVIDERS[key]["label"])
    info = PROVIDERS[provider]
    default_model = current_model if provider == current_provider and current_model else info["model"]
    model = st.text_input("Model" + (" (your Azure DEPLOYMENT name)" if provider == "azure_openai" else ""),
                          default_model)

    keys = {}
    for i in range(len(info["keys"])):
        key_name = info["keys"][i][0]
        label = info["keys"][i][1]
        default = os.getenv(key_name, "") or info["keys"][i][2]
        if default == "sk-...":
            default = ""
        is_secret = "KEY" in key_name
        keys[key_name] = st.text_input(label, default, type="password" if is_secret else "default",
                                       key="model_" + key_name)
    if info["package"] != "":
        st.caption("Needs the Python package: pip install " + info["package"])

    model_name = provider + ":" + model.strip()
    if st.button("🔍 Test model"):
        run_model_test(provider, model_name, keys)
    return model_name, keys


def run_model_test(provider, model_name, keys):
    for key_name in keys:
        os.environ[key_name] = keys[key_name]
    with st.spinner("Sending one short test message..."):
        try:
            answer = agent.build_llm(model_name).invoke("Reply with the single word OK.")
            st.success("✅ The model answered. You are good to go.")
            return True
        except Exception as error:
            st.error("❌ " + friendly_model_error(provider, error))
            return False


# ------------------------------------------------------------
# 3. SAVE
# ------------------------------------------------------------
def show_save_section(parts, model_name, model_keys):
    st.header("3. Save")
    st.caption("Saves to " + str(settings.ENV_FILE) + ". The database is tested again first.")
    left, right = st.columns(2)

    if left.button("💾 Save and start", type="primary"):
        if not run_database_test(parts):
            st.error("Not saved. Fix the database connection first.")
            return
        updates = {
            "DATABASE_URL": "",
            "DB_TYPE": parts["type"],
            "DB_FILE": parts.get("file", ""),
            "DB_HOST": parts.get("host", ""),
            "DB_PORT": parts.get("port", ""),
            "DB_NAME": parts.get("name", ""),
            "DB_USER": parts.get("user", ""),
            "DB_PASSWORD": parts.get("password", ""),
            "DB_WINDOWS_LOGIN": "true" if parts.get("windows_login", False) else "false",
            "DB_ODBC_DRIVER": parts.get("odbc_driver", ""),
            "DB_WAREHOUSE": parts.get("warehouse", ""),
            "DB_ROLE": parts.get("role", ""),
            "SCHEMAS": parts.get("schema", ""),
            "LLM_MODEL": model_name,
        }
        for key_name in model_keys:
            updates[key_name] = model_keys[key_name]
        update_env_file(updates)
        reload_everything()
        st.session_state.show_setup = False
        st.session_state.setup_reason = ""
        st.session_state.setup_details = ""
        st.rerun()

    if st.session_state.get("setup_can_cancel", False) and right.button("Cancel"):
        st.session_state.show_setup = False
        st.rerun()
