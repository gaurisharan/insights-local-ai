import streamlit as st
import psycopg2
import requests
import pandas as pd
import plotly.express as px
import re

# Database Configuration
DB_CONFIG = {
    "dbname": "postgres", # Database name
    "user": "username", # ENTER DB USERNAME HERE
    "password": "yourpassword", # ENTER DATABASE PASSWORD HERE
    "host": "localhost", # Database host
    "port": "5432",    # Database port
}

# Connect to PostgreSQL
def connect_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        st.error(f"Connection failed: {e}")
        return None

# System Prompt for SQL Generation
SYSTEM_PROMPT = """
### SYSTEM MESSAGE ###
You are an AI SQL assistant for PostgreSQL.

Rules:
1️⃣ Only return **pure SQL queries**—no explanations, no labels, NO PREFIXES like "Solution:" or "Answer:".
2️⃣ Ensure queries are **safe and efficient** (no `DROP`, `DELETE`, etc.).
3️⃣ 100% Accuracy - Every query must be valid for PostgreSQL.
4️⃣ Use **LIKE** instead of `=` for case-insensitive string matching.
5️⃣ Use **EXISTS** instead of `IN` for large subqueries when necessary.
6️⃣ Ensure all queries are formatted as clean, single-line SQL with NO newlines affecting execution.
7️⃣ **Do not use Python variables** in queries.

### SYSTEM MESSAGE ENDS ###
"""

# Schema Information
SCHEMA_INFO = """
TABLE transactions (
    mti TEXT COLLATE pg_catalog."default" CHECK (mti IN ('FETCH', 'PAYMENT')),
    txn_date DATE,
    ref_id TEXT COLLATE pg_catalog."default" NOT NULL,
    bou_id TEXT COLLATE pg_catalog."default",
    bou_name TEXT COLLATE pg_catalog."default" CHECK (bou_name IN ('Federal Bank Limited', 'Canara Bank', 'ICICI Bank Limited', 'AU Small Finance Bank Limited', 'Union Bank of India', 'HDFC Bank Limited', 'Indian Overseas Bank', 'IndusInd Bank Limited', 'Bank of Baroda', 'IDBI Bank Limited', 'Punjab National Bank', 'Standard Chartered Bank', 'State Bank of India', 'DBS Bank India Limited', 'Airtel Payments Bank Limited', 'Axis Bank Limited', 'IDFC FIRST Bank Limited', 'YES Bank Limited', 'Bandhan Bank Limited')),
    cou_id TEXT COLLATE pg_catalog."default",
    cou_name TEXT COLLATE pg_catalog."default" CHECK (cou_name IN ('Airtel Payments Bank', 'Amazon Pay', 'Axis Bank', 'Bajaj Finserv', 'Bank of Baroda', 'Cred', 'FreeCharge', 'Google Pay', 'HDFC Bank', 'ICICI Bank', 'MobiKwik', 'Paytm Payments Bank', 'PhonePe', 'Punjab National Bank (PNB)', 'State Bank of India (SBI)', 'Union Bank of India')),
    txn_amount NUMERIC(10,2)
);
"""

def format_sql_query(sql_query):
    """
    Ensures proper spacing between SQL keywords and clauses in the query,
    preserving string literals and avoiding partial word matches.
    """
    # Step 1: Protect string literals using placeholders
    string_literals = []
    def replace_literal(match):
        string_literals.append(match.group(0))
        return f"%%LITERAL_{len(string_literals)-1}%%"
    
    modified_sql = re.sub(r"'([^']|'')*'", replace_literal, sql_query)

    # Step 2: Fix unintended spaces within words (outside literals)
    modified_sql = re.sub(r"(\w)\s{2,}(\w)", r"\1 \2", modified_sql)  # Multiple spaces
    modified_sql = re.sub(r"(\b\w+\b)\s+(\b\w+\b)", r"\1 \2", modified_sql)  # Preserve word boundaries

    # Step 3: Format SQL keywords with proper spacing (whole words only)
    keywords = [
        "SELECT", "FROM", "WHERE", "AND", "OR", 
        "GROUP BY", "ORDER BY", "HAVING", "LIMIT", 
        "OFFSET", "JOIN", "ON", "EXISTS", "ILIKE"
    ]
    
    for keyword in keywords:
        # Handle multi-word keywords differently
        if " " in keyword:
            parts = keyword.split()
            pattern = rf"(?i)\b({parts[0]})\s+({parts[1]})\b"
            replacement = rf" \1 \2 "
            modified_sql = re.sub(pattern, replacement, modified_sql)
        else:
            # Match whole words only using word boundaries
            pattern = rf"(?i)\b({re.escape(keyword)})\b"
            replacement = rf" \1 "
            modified_sql = re.sub(pattern, replacement, modified_sql)
    
    # Step 4: Clean up extra spaces and final formatting
    modified_sql = re.sub(r"\s+", " ", modified_sql).strip()
    modified_sql = modified_sql.replace(" ;", ";")  # Fix space before semicolon
    
    # Step 5: Restore protected string literals
    for idx, literal in enumerate(string_literals):
        modified_sql = modified_sql.replace(f"%%LITERAL_{idx}%%", literal)
    
    # Ensure final semicolon
    if not modified_sql.endswith(";"):
        modified_sql += ";"
        
    return modified_sql

def prioritize_ilike(sql_query):
    """
    Replaces '=' with 'ILIKE' for string comparisons in the SQL query
    and appends a '%' wildcard to the end of string values.
    Now properly handles quoted strings and only modifies string comparisons.
    """
    # This pattern matches: column = 'value'
    pattern = r"(\b\w+\b)\s*=\s*('[^']+')"
    
    def replace_with_ilike(match):
        column = match.group(1)
        value = match.group(2)
        # Keep the original quotes but add % wildcard
        return f"{column} ILIKE {value[:-1]}%'"
    
    # Perform the replacement
    modified_sql = re.sub(pattern, replace_with_ilike, sql_query, flags=re.IGNORECASE)
    
    return modified_sql

def extract_pure_sql(response_text):
    """
    Extracts pure SQL code from a response by identifying the first SQL reserved word
    and stripping everything before it. Also removes anything after the end of the query.
    """
    # List of common SQL reserved words to identify the start of the query
    sql_reserved_words = [
        "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "WITH",
        "WHERE", "FROM", "JOIN", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION"
    ]
    
    # Create a regex pattern to match any of the reserved words at the start of the query
    start_pattern = r"\b(" + "|".join(sql_reserved_words) + r")\b"
    match_start = re.search(start_pattern, response_text, re.IGNORECASE)
    
    if match_start:
        # Extract everything from the first reserved word
        cleaned_query = response_text[match_start.start():].strip()
        
        # Regex to identify the end of a valid SQL query (e.g., semicolon or end of statement)
        end_pattern = r";|$"
        match_end = re.search(end_pattern, cleaned_query)
        
        if match_end:
            # Extract everything up to the end of the query, including the semicolon
            cleaned_query = cleaned_query[:match_end.end()].strip()
        
        return cleaned_query
    else:
        # If no reserved word is found, return the original response
        return response_text.strip()

# Generate SQL Query from LLM
def generate_sql_query(problem_statement):
    url = "http://localhost:1234/v1/completions"  # LM Studio API URL
    prompt = f"{SYSTEM_PROMPT}\nSchema:\n{SCHEMA_INFO}\nProblem:\n{problem_statement}"
    
    payload = {
        "model": "dolphin3.0-llama3.1-8b",
        "prompt": prompt,
        "max_tokens": 256,
        "temperature": 0.2
    }
    
    response = requests.post(url, json=payload)
    raw_sql = response.json()["choices"][0]["text"].strip()
    print("\n[DEBUG] Raw SQL from LLM:", raw_sql)  # Debugging: Print raw SQL from LLM
    
    # Clean and enforce rules on the SQL query
    pure_sql = extract_pure_sql(raw_sql)  # Remove unwanted prefixes and suffixes
    print("\n[DEBUG] After extract_pure_sql:", pure_sql)  # Debugging: Print after extract_pure_sql
    
    formatted_sql = format_sql_query(pure_sql)  # Ensure proper spacing
    print("\n[DEBUG] After format_sql_query:", formatted_sql)  # Debugging: Print after format_sql_query
    
    final_sql = prioritize_ilike(formatted_sql)  # Replace '=' with 'ILIKE' and append '%'
    print("\n[DEBUG] After prioritize_ilike:", final_sql)  # Debugging: Print after prioritize_ilike
    
    return final_sql

# Execute SQL Query
def execute_query(query):
    conn = connect_db()
    if not conn:
        return None, None
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]  # Extract column names
            return result, column_names  # Return both result and column names
    except Exception as e:
        return f"Query execution failed: {e}", None
    finally:
        conn.close()

# Streamlit Chat UI
st.title("Insights AI")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "query_result" not in st.session_state:
    st.session_state.query_result = None
if "df" not in st.session_state:
    st.session_state.df = None

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Enter your SQL problem statement:"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Generate SQL query from the problem statement
    sql_query = generate_sql_query(user_input)
    sql_query = sql_query.replace("Solution:", "").replace("Answer:", "").strip()
    sql_query = sql_query.replace("\n", "").strip()

    # Print the generated SQL query in the terminal
    print("Generated SQL Query:", sql_query)

    # Execute the generated query directly
    result, column_names = execute_query(sql_query)
    st.session_state.query_result = result

    if isinstance(result, str):
        # If there's an error, display it
        st.session_state.messages.append({"role": "assistant", "content": result})
        with st.chat_message("assistant"):
            st.error(result)
    else:
        # If the query executes successfully, display the results
        df = pd.DataFrame(result, columns=column_names)
        st.session_state.df = df
        st.session_state.messages.append({"role": "assistant", "content": "Here are the results:"})
        with st.chat_message("assistant"):
            st.dataframe(df)

if st.session_state.df is not None:
    st.subheader("Query Results")
    st.dataframe(st.session_state.df)

    # Plotly Visualization
    st.subheader("Visualize Data")
    chart_type = st.selectbox("Select Chart Type", ["Bar", "Line", "Scatter", "Pie"])

    if chart_type == "Bar":
        x_axis = st.selectbox("Select X-axis", st.session_state.df.columns)
        y_axis = st.selectbox("Select Y-axis", st.session_state.df.columns)
        fig = px.bar(st.session_state.df, x=x_axis, y=y_axis, title="Bar Chart")
        st.plotly_chart(fig)

    elif chart_type == "Line":
        x_axis = st.selectbox("Select X-axis", st.session_state.df.columns)
        y_axis = st.selectbox("Select Y-axis", st.session_state.df.columns)
        fig = px.line(st.session_state.df, x=x_axis, y=y_axis, title="Line Chart")
        st.plotly_chart(fig)

    elif chart_type == "Scatter":
        x_axis = st.selectbox("Select X-axis", st.session_state.df.columns)
        y_axis = st.selectbox("Select Y-axis", st.session_state.df.columns)
        fig = px.scatter(st.session_state.df, x=x_axis, y=y_axis, title="Scatter Plot")
        st.plotly_chart(fig)

    elif chart_type == "Pie":
        pie_column = st.selectbox("Select Column for Pie Chart", st.session_state.df.columns)
        fig = px.pie(st.session_state.df, names=pie_column, title="Pie Chart")
        st.plotly_chart(fig)
