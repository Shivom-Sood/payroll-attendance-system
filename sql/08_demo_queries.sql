-- =====================================================================
--  File 08: Demo / viva queries
--  Each query shows a DBMS concept from the course on real project data.
--  Run them one at a time in MySQL Workbench.
-- =====================================================================
USE payroll_db;

-- Q1. INNER + SELF JOIN: every employee with department and manager
SELECT e.emp_id, CONCAT(e.first_name,' ',e.last_name) AS employee,
       d.dept_name, CONCAT(m.first_name,' ',m.last_name) AS manager
FROM employees e
JOIN departments d    ON d.dept_id = e.dept_id
LEFT JOIN employees m ON m.emp_id  = e.manager_id
ORDER BY d.dept_name, e.emp_id;

-- Q2. GROUP BY + HAVING: departments whose October OT pay exceeded Rs 5,000
SELECT d.dept_name, SUM(p.ot_pay) AS ot_pay
FROM payroll p JOIN employees e ON e.emp_id = p.emp_id
JOIN departments d ON d.dept_id = e.dept_id
WHERE p.pay_month = '2026-10-01'
GROUP BY d.dept_name
HAVING SUM(p.ot_pay) > 5000;

-- Q3. NON-CORRELATED SUBQUERY: employees earning above the company's average net salary (Oct)
SELECT employee_name, net_salary
FROM v_salary_slip
WHERE pay_month = '2026-10-01'
  AND net_salary > (SELECT AVG(net_salary) FROM payroll WHERE pay_month = '2026-10-01')
ORDER BY net_salary DESC;

-- Q4. CORRELATED SUBQUERY: employees who worked more OT than their department's average
SELECT o.employee_name, o.dept_name, o.total_ot_hours
FROM v_overtime_summary o
WHERE o.pay_month = '2026-10-01'
  AND o.total_ot_hours > (SELECT AVG(i.total_ot_hours) FROM v_overtime_summary i
                          WHERE i.pay_month = o.pay_month AND i.dept_name = o.dept_name);

-- Q5. EXISTS / NOT EXISTS: employees with no late mark in October
SELECT e.emp_id, CONCAT(e.first_name,' ',e.last_name) AS employee
FROM employees e
WHERE e.hire_date <= '2026-10-31'
  AND NOT EXISTS (SELECT 1 FROM v_late_marks l
                  WHERE l.emp_id = e.emp_id AND l.pay_month = '2026-10-01');

-- Q6. SET OPERATION (UNION): one list of everyone who was away on any day in Oct, with the reason
SELECT emp_id, cal_date, 'Approved leave' AS reason FROM v_daily_attendance
 WHERE day_status IN ('PAID_LEAVE','UNPAID_LEAVE') AND cal_date BETWEEN '2026-10-01' AND '2026-10-31'
UNION
SELECT emp_id, cal_date, 'Absent without leave' FROM v_daily_attendance
 WHERE day_status = 'ABSENT' AND cal_date BETWEEN '2026-10-01' AND '2026-10-31'
ORDER BY cal_date;

-- Q7. WINDOW FUNCTIONS: rank by net salary inside each department + running payroll total
SELECT dept_name, employee_name, net_salary,
       RANK() OVER (PARTITION BY dept_name ORDER BY net_salary DESC)  AS rank_in_dept,
       SUM(net_salary) OVER (ORDER BY net_salary DESC)                AS running_total
FROM v_salary_slip WHERE pay_month = '2026-10-01';

-- Q8. LAG(): month-on-month change in each employee's net salary
SELECT employee_name, month_label, net_salary,
       net_salary - LAG(net_salary) OVER (PARTITION BY emp_id ORDER BY pay_month) AS change_vs_last_month
FROM v_salary_slip ORDER BY emp_id, pay_month;

-- Q9. CTE: top overtime earner in every department (ROW_NUMBER guarantees one row each)
WITH ranked AS (
    SELECT dept_name, employee_name, total_ot_hours, ot_pay,
           ROW_NUMBER() OVER (PARTITION BY dept_name ORDER BY total_ot_hours DESC) AS rn
    FROM v_overtime_summary WHERE pay_month = '2026-10-01'
)
SELECT dept_name, employee_name, total_ot_hours, ot_pay FROM ranked WHERE rn = 1;

-- Q10. RECURSIVE CTE: reporting chain from a junior employee up to the top
WITH RECURSIVE chain AS (
    SELECT emp_id, first_name, manager_id, 0 AS level FROM employees WHERE emp_id = 1012
    UNION ALL
    SELECT e.emp_id, e.first_name, e.manager_id, c.level + 1
    FROM employees e JOIN chain c ON e.emp_id = c.manager_id
)
SELECT level, emp_id, first_name FROM chain;

-- Q11. Stored procedure + function calls
CALL sp_salary_slip(1004, 2026, 10);
SELECT fn_working_days(2026, 10) AS oct_working_days,
       fn_annual_tax(1500000, '2026-10-31') AS tax_on_15_lakh_taxable;

-- Q12. Index in action: EXPLAIN shows idx_att_date being used
EXPLAIN SELECT * FROM attendance WHERE att_date BETWEEN '2026-10-01' AND '2026-10-31';

-- Q13. Audit trail written by triggers
SELECT * FROM audit_log ORDER BY log_id DESC LIMIT 10;
