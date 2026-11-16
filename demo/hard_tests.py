# ============================================================
# demo/hard_tests.py | ANSWER KEY for 6 HARD AdventureWorks questions
# ============================================================
#
# Run:   python demo/hard_tests.py
# (after demo/setup_adventureworks.py has created the read-only login)
#
# Each question tests something simple text-to-SQL tools get wrong:
#   H1 → "top 1 per group" (window function over an aggregate, 4 tables)
#   H2 → year-over-year growth (conditional aggregation, 5-table join chain)
#   H3 → "did X but NOT Y" (anti-join, the classic trap)
#   H4 → two different facts compared (sales vs quota tables, two CTEs)
#   H5 → a long join path to filter by country (5 tables, the country is 4 hops away)
#   H6 → "current" and "most recent" (history tables, the easiest place to double-count)
# ============================================================

import pyodbc

READER_LOGIN = "querydost_reader"
READER_PASSWORD = "QdReader2026"
CONNECTION = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost,1433;DATABASE=AdventureWorks;"
              "UID=" + READER_LOGIN + ";PWD=" + READER_PASSWORD + ";TrustServerCertificate=yes")

TESTS = [
    ("H1", "For each sales territory, which single product earned the most revenue in 2013, and how much?",
     """WITH ranked AS (
            SELECT t.Name AS Territory, p.Name AS Product, SUM(d.LineTotal) AS Revenue,
                   ROW_NUMBER() OVER (PARTITION BY t.Name ORDER BY SUM(d.LineTotal) DESC) AS rn
            FROM Sales.SalesOrderDetail d
            JOIN Sales.SalesOrderHeader h ON d.SalesOrderID = h.SalesOrderID
            JOIN Sales.SalesTerritory t ON h.TerritoryID = t.TerritoryID
            JOIN Production.Product p ON d.ProductID = p.ProductID
            WHERE YEAR(h.OrderDate) = 2013
            GROUP BY t.Name, p.Name)
        SELECT Territory, Product, ROUND(Revenue, 2) FROM ranked WHERE rn = 1 ORDER BY Territory"""),

    ("H2", "Which product category grew the most in sales revenue from 2012 to 2013, in percentage terms? "
           "Show every category with its 2012 revenue, 2013 revenue and growth %.",
     """SELECT c.Name,
               ROUND(SUM(CASE WHEN YEAR(h.OrderDate) = 2012 THEN d.LineTotal ELSE 0 END), 2) AS Rev2012,
               ROUND(SUM(CASE WHEN YEAR(h.OrderDate) = 2013 THEN d.LineTotal ELSE 0 END), 2) AS Rev2013,
               ROUND((SUM(CASE WHEN YEAR(h.OrderDate) = 2013 THEN d.LineTotal ELSE 0 END)
                    - SUM(CASE WHEN YEAR(h.OrderDate) = 2012 THEN d.LineTotal ELSE 0 END)) * 100.0
                    / NULLIF(SUM(CASE WHEN YEAR(h.OrderDate) = 2012 THEN d.LineTotal ELSE 0 END), 0), 1) AS GrowthPct
        FROM Sales.SalesOrderDetail d
        JOIN Sales.SalesOrderHeader h ON d.SalesOrderID = h.SalesOrderID
        JOIN Production.Product p ON d.ProductID = p.ProductID
        JOIN Production.ProductSubcategory s ON p.ProductSubcategoryID = s.ProductSubcategoryID
        JOIN Production.ProductCategory c ON s.ProductCategoryID = c.ProductCategoryID
        GROUP BY c.Name ORDER BY GrowthPct DESC"""),

    ("H3", "How many customers placed at least one order in 2012 but no orders at all in 2013?",
     """SELECT COUNT(DISTINCT h.CustomerID)
        FROM Sales.SalesOrderHeader h
        WHERE YEAR(h.OrderDate) = 2012
          AND NOT EXISTS (SELECT 1 FROM Sales.SalesOrderHeader h2
                          WHERE h2.CustomerID = h.CustomerID AND YEAR(h2.OrderDate) = 2013)"""),

    ("H4", "Which salespeople beat their 2013 sales quota? Compare each person's total 2013 order subtotal "
           "with the sum of their 2013 quotas, and show their attainment %.",
     """WITH sales AS (
            SELECT SalesPersonID, SUM(SubTotal) AS Sales2013 FROM Sales.SalesOrderHeader
            WHERE YEAR(OrderDate) = 2013 AND SalesPersonID IS NOT NULL GROUP BY SalesPersonID),
        quota AS (
            SELECT BusinessEntityID, SUM(SalesQuota) AS Quota2013 FROM Sales.SalesPersonQuotaHistory
            WHERE YEAR(QuotaDate) = 2013 GROUP BY BusinessEntityID)
        SELECT p.FirstName + ' ' + p.LastName, ROUND(s.Sales2013, 2), ROUND(q.Quota2013, 2),
               ROUND(s.Sales2013 * 100.0 / q.Quota2013, 1) AS AttainmentPct
        FROM sales s
        JOIN quota q ON s.SalesPersonID = q.BusinessEntityID
        JOIN Person.Person p ON p.BusinessEntityID = s.SalesPersonID
        ORDER BY AttainmentPct DESC"""),

    ("H5", "For orders shipped to the United Kingdom, what is the average number of days between order date "
           "and ship date for each shipping method, and how many orders used each method?",
     """SELECT sm.Name, ROUND(AVG(CAST(DATEDIFF(day, h.OrderDate, h.ShipDate) AS FLOAT)), 2), COUNT(*)
        FROM Sales.SalesOrderHeader h
        JOIN Purchasing.ShipMethod sm ON h.ShipMethodID = sm.ShipMethodID
        JOIN Person.Address a ON h.ShipToAddressID = a.AddressID
        JOIN Person.StateProvince sp ON a.StateProvinceID = sp.StateProvinceID
        JOIN Person.CountryRegion cr ON sp.CountryRegionCode = cr.CountryRegionCode
        WHERE cr.Name = 'United Kingdom'
        GROUP BY sm.Name ORDER BY sm.Name"""),

    ("H6", "Using each employee's most recent pay rate and their current department, "
           "which 3 departments have the highest average pay rate? Show the number of employees too.",
     """WITH latest AS (
            SELECT BusinessEntityID, Rate,
                   ROW_NUMBER() OVER (PARTITION BY BusinessEntityID ORDER BY RateChangeDate DESC) AS rn
            FROM HumanResources.EmployeePayHistory),
        current_dept AS (
            SELECT BusinessEntityID, DepartmentID FROM HumanResources.EmployeeDepartmentHistory
            WHERE EndDate IS NULL)
        SELECT TOP 3 d.Name, ROUND(AVG(l.Rate), 2), COUNT(*)
        FROM latest l
        JOIN current_dept c ON l.BusinessEntityID = c.BusinessEntityID
        JOIN HumanResources.Department d ON c.DepartmentID = d.DepartmentID
        WHERE l.rn = 1
        GROUP BY d.Name ORDER BY AVG(l.Rate) DESC"""),
]

conn = pyodbc.connect(CONNECTION)
cursor = conn.cursor()
print("HARD TESTS: ANSWER KEY\n")
for i in range(len(TESTS)):
    test_id = TESTS[i][0]
    question = TESTS[i][1]
    cursor.execute(TESTS[i][2])
    rows = cursor.fetchall()
    print(test_id + ": " + question)
    if test_id == "H4":
        print("      (ALL salespeople shown. Beat quota = AttainmentPct above 100.)")
    if len(rows) == 0:
        print("      (no rows: the correct answer is 'none')")
    for r in range(len(rows)):
        print("     ", tuple(rows[r]))
    print()
conn.close()
