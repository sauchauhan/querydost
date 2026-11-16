# ============================================================
# demo/setup_adventureworks.py | READ-ONLY LOGIN + ANSWER KEY for AdventureWorks
# ============================================================
#
# Run AFTER the AdventureWorks Docker container is up:
#     python demo/setup_adventureworks.py
#
# What it does:
#   1. Logs in as the admin (sa) ONCE and creates a READ-ONLY login for QueryDost
#   2. Logs in as that read-only login and PROVES it cannot delete anything
#   3. Prints the correct answers to 6 test questions, so you can check QueryDost
#
# Needs: pip install pyodbc, and "ODBC Driver 18 for SQL Server" on the machine.
# ============================================================

import pyodbc

# Must match the docker run command
SA_PASSWORD = "QueryDost#2026"

# The login QueryDost will use. Letters and digits only, so it works in a URL as-is.
READER_LOGIN = "querydost_reader"
READER_PASSWORD = "QdReader2026"

SERVER = "localhost,1433"
DATABASE = "AdventureWorks"
DRIVER = "ODBC Driver 18 for SQL Server"


def connect(user, password, database):
    text = ("DRIVER={" + DRIVER + "};SERVER=" + SERVER + ";DATABASE=" + database
            + ";UID=" + user + ";PWD=" + password + ";TrustServerCertificate=yes")
    # autocommit=True → CREATE LOGIN cannot run inside a transaction
    return pyodbc.connect(text, autocommit=True)


# ------------------------------------------------------------
# 1. Create the read-only login (safe to run again)
# ------------------------------------------------------------
# db_datareader → a built-in SQL Server role that can SELECT from every table, and nothing else
admin = connect("sa", SA_PASSWORD, DATABASE)
cursor = admin.cursor()
cursor.execute("IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = '" + READER_LOGIN + "') "
               "CREATE LOGIN " + READER_LOGIN + " WITH PASSWORD = '" + READER_PASSWORD + "', CHECK_POLICY = OFF")
cursor.execute("IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '" + READER_LOGIN + "') "
               "CREATE USER " + READER_LOGIN + " FOR LOGIN " + READER_LOGIN)
cursor.execute("ALTER ROLE db_datareader ADD MEMBER " + READER_LOGIN)
admin.close()
print("1. Read-only login ready:", READER_LOGIN)


# ------------------------------------------------------------
# 2. Prove the read-only login cannot write
# ------------------------------------------------------------
reader = connect(READER_LOGIN, READER_PASSWORD, DATABASE)
cursor = reader.cursor()
try:
    cursor.execute("DELETE FROM Sales.SalesOrderDetail WHERE 1 = 0")
    print("2. WARNING: the read-only login was allowed to run a DELETE. Check the setup.")
except Exception as error:
    print("2. Good: the database refused a DELETE from the read-only login.")

cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES")
print("   Tables + views this login can see:", cursor.fetchone()[0])


# ------------------------------------------------------------
# 3. Answer key: ask QueryDost these questions and compare
# ------------------------------------------------------------
TESTS = [
    ("How many employees do we have?",
     "SELECT COUNT(*) FROM HumanResources.Employee"),

    ("How many products are there in each product category?",
     "SELECT c.Name, COUNT(*) FROM Production.Product p "
     "JOIN Production.ProductSubcategory s ON p.ProductSubcategoryID = s.ProductSubcategoryID "
     "JOIN Production.ProductCategory c ON s.ProductCategoryID = c.ProductCategoryID "
     "GROUP BY c.Name ORDER BY c.Name"),

    ("Which salesperson has the highest sales year to date?",
     "SELECT TOP 1 p.FirstName + ' ' + p.LastName, sp.SalesYTD FROM Sales.SalesPerson sp "
     "JOIN Person.Person p ON sp.BusinessEntityID = p.BusinessEntityID ORDER BY sp.SalesYTD DESC"),

    ("What are the top 3 sales territories by total sales (TotalDue)?",
     "SELECT TOP 3 t.Name, SUM(h.TotalDue) FROM Sales.SalesOrderHeader h "
     "JOIN Sales.SalesTerritory t ON h.TerritoryID = t.TerritoryID "
     "GROUP BY t.Name ORDER BY SUM(h.TotalDue) DESC"),

    ("How many orders were placed in each year?",
     "SELECT YEAR(OrderDate), COUNT(*) FROM Sales.SalesOrderHeader GROUP BY YEAR(OrderDate) ORDER BY 1"),

    ("What is the average list price of products in the Bikes category?",
     "SELECT AVG(p.ListPrice) FROM Production.Product p "
     "JOIN Production.ProductSubcategory s ON p.ProductSubcategoryID = s.ProductSubcategoryID "
     "JOIN Production.ProductCategory c ON s.ProductCategoryID = c.ProductCategoryID "
     "WHERE c.Name = 'Bikes'"),
]

print("\n3. ANSWER KEY (ask QueryDost the question, compare with these numbers)\n")
for i in range(len(TESTS)):
    question = TESTS[i][0]
    sql = TESTS[i][1]
    cursor.execute(sql)
    rows = cursor.fetchall()
    print("Q" + str(i + 1) + ": " + question)
    for r in range(len(rows)):
        print("     ", tuple(rows[r]))
    print()
reader.close()
