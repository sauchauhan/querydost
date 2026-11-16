# ============================================================
# demo/create_demo_db.py | CREATE or RESET the demo HR database
# ============================================================
#
# Run:   python demo/create_demo_db.py
#
# Creates demo/hr_company.db (overwrites it if it exists).
# Run it again any time to undo changes made during a demo.
#
# WHAT IS INSIDE: two tables
#   1. employees       → 20 employees
#      emp_id | name | dept | role | joined | leave_days | location | salary_lpa
#   2. leave_requests  → 15 leave requests (Approved / Rejected / Pending)
#      leave_requests.emp_id links to employees.emp_id (a real FOREIGN KEY,
#      so QueryDost can discover the join by itself)
# ============================================================

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "hr_company.db"
conn = sqlite3.connect(DB_PATH)

conn.execute("DROP TABLE IF EXISTS leave_requests")
conn.execute("DROP TABLE IF EXISTS employees")

# ---------------- TABLE 1: employees ----------------
conn.execute("""CREATE TABLE employees (
    emp_id TEXT PRIMARY KEY, name TEXT, dept TEXT, role TEXT,
    joined TEXT, leave_days INTEGER, location TEXT, salary_lpa REAL)""")

employees = [
    ("EMP001", "Priya", "Engineering", "Senior Developer", "2021-03", 12, "Pune", 24.0),
    ("EMP002", "Rahul", "Marketing", "Campaign Manager", "2022-08", 3, "Mumbai", 16.5),
    ("EMP003", "Amit", "Engineering", "Tech Lead", "2019-06", 18, "Pune", 32.0),
    ("EMP004", "Sneha", "HR", "HR Business Partner", "2023-01", 0, "Bengaluru", 14.0),
    ("EMP005", "Vikram", "Projects", "Project Manager", "2018-11", 15, "Mumbai", 28.5),
    ("EMP006", "Ananya", "Finance", "Financial Analyst", "2022-02", 9, "Pune", 12.5),
    ("EMP007", "Karthik", "Engineering", "Data Engineer", "2020-07", 7, "Chennai", 21.0),
    ("EMP008", "Meera", "Procurement", "Procurement Lead", "2017-04", 20, "Ahmedabad", 22.0),
    ("EMP009", "Arjun", "Projects", "Site Engineer", "2023-06", 5, "Hyderabad", 9.5),
    ("EMP010", "Neha", "Marketing", "Content Strategist", "2021-09", 11, "Delhi", 13.0),
    ("EMP011", "Rohan", "Engineering", "QA Engineer", "2022-12", 6, "Pune", 11.0),
    ("EMP012", "Kavya", "HR", "Talent Acquisition", "2020-03", 14, "Bengaluru", 12.0),
    ("EMP013", "Siddharth", "Finance", "Finance Manager", "2016-08", 16, "Mumbai", 30.0),
    ("EMP014", "Pooja", "Projects", "Planning Engineer", "2021-01", 8, "Pune", 15.5),
    ("EMP015", "Aditya", "Engineering", "DevOps Engineer", "2019-10", 10, "Hyderabad", 23.0),
    ("EMP016", "Ishita", "Procurement", "Vendor Manager", "2023-03", 4, "Ahmedabad", 10.5),
    ("EMP017", "Manish", "Projects", "Safety Officer", "2018-05", 13, "Mumbai", 14.5),
    ("EMP018", "Divya", "Finance", "Accounts Executive", "2024-01", 2, "Chennai", 7.5),
    ("EMP019", "Harsh", "Engineering", "Solutions Architect", "2015-12", 21, "Pune", 38.0),
    ("EMP020", "Tanvi", "HR", "HR Operations", "2022-05", 9, "Delhi", 9.0),
]
conn.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?)", employees)

# ---------------- TABLE 2: leave_requests ----------------
conn.execute("""CREATE TABLE leave_requests (
    request_id INTEGER PRIMARY KEY,
    emp_id TEXT REFERENCES employees(emp_id),
    from_date TEXT, to_date TEXT, days INTEGER, reason TEXT, status TEXT)""")

leave_requests = [
    (1, "EMP001", "2026-01-12", "2026-01-14", 3, "Family function in Nashik", "Approved"),
    (2, "EMP002", "2026-02-02", "2026-02-11", 8, "Goa trip", "Approved"),
    (3, "EMP004", "2026-03-09", "2026-03-20", 10, "Sister wedding", "Approved"),
    (4, "EMP003", "2026-04-06", "2026-04-07", 2, "IPL match in Mumbai", "Approved"),
    (5, "EMP007", "2026-04-20", "2026-04-24", 5, "Hometown visit, Madurai", "Approved"),
    (6, "EMP009", "2026-05-04", "2026-05-15", 10, "Manali trek", "Rejected"),
    (7, "EMP010", "2026-05-18", "2026-05-19", 2, "Personal work", "Approved"),
    (8, "EMP005", "2026-06-01", "2026-06-05", 5, "Kids summer vacation", "Approved"),
    (9, "EMP014", "2026-07-13", "2026-07-14", 2, "Medical appointment", "Approved"),
    (10, "EMP002", "2026-08-24", "2026-08-28", 5, "Ganpati festival", "Rejected"),
    (11, "EMP012", "2026-09-07", "2026-09-09", 3, "House shifting in Bengaluru", "Approved"),
    (12, "EMP018", "2026-10-19", "2026-10-23", 5, "Diwali at home", "Pending"),
    (13, "EMP001", "2026-11-09", "2026-11-13", 5, "Diwali in Jaipur", "Pending"),
    (14, "EMP016", "2026-11-16", "2026-11-20", 5, "Friend wedding, Udaipur", "Pending"),
    (15, "EMP019", "2026-12-21", "2026-12-31", 9, "Year-end Kerala trip", "Pending"),
]
conn.executemany("INSERT INTO leave_requests VALUES (?, ?, ?, ?, ?, ?, ?)", leave_requests)

conn.commit()
conn.close()
print("Demo database ready:", DB_PATH)
