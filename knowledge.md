# Business knowledge for QueryDost

The model already knows SQL. It does NOT know what YOUR company means by
"active", "leave left", "quarter" or "sale". Write it here in plain English.
This whole file goes to the model as-is. Click "Reload knowledge.md" in the app after editing.

Three sections work best:
1. Glossary: what your words mean in tables and columns
2. Example questions with the correct SQL (your dashboard queries are perfect for this)
3. Extra rules for your data

Everything below is for the demo HR database. Replace it with your own.

## Glossary
- "Leave balance" or "leave left" means employees.leave_days.
- "Pending request" means leave_requests.status = 'Pending'.
- "Team" or "department" means employees.dept.
- "Office" or "city" means employees.location.
- employees.joined is stored as text in 'YYYY-MM' format.

## Example questions and correct SQL

Question: How many employees are in each department?
SQL: SELECT dept, COUNT(*) AS employees FROM employees GROUP BY dept ORDER BY employees DESC

Question: Show all pending leave requests with employee names.
SQL: SELECT e.name, r.from_date, r.to_date, r.days, r.reason
     FROM leave_requests r JOIN employees e ON r.emp_id = e.emp_id
     WHERE r.status = 'Pending'

## Rules for this data
- Never show salary_lpa. Salary is confidential.
