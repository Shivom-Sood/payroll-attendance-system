-- =====================================================================
--  File 09: Index optimisation - execution plan BEFORE vs AFTER (Phase 3)
--
--  Report used: the LATE-MARKS REPORT (who checked in after 09:45 in a month).
--  Its core query filters attendance by a DATE RANGE:
--
--     SELECT emp_id, COUNT(*) FROM attendance
--     WHERE att_date BETWEEN '<month start>' AND '<month end>'
--       AND TIME(check_in) > '09:45:00'
--     GROUP BY emp_id;
--
--  The table already has UNIQUE(emp_id, att_date), but that index starts
--  with emp_id, so it CANNOT be used for a filter on att_date alone
--  (leftmost-prefix rule). Without another index MySQL scans every row.
--
--  Part A: real project data (853 rows): the plan changes from scanning all
--          853 rows (type = index) to a range scan of ~231 rows (type = range).
--  Part B: the same query on a scaled copy (1,000 employees x 1 year =
--          365,000 rows) to measure the actual time saved with EXPLAIN ANALYZE.
--          Three stages: no index -> single-column index -> covering index.
-- =====================================================================
USE payroll_db;

-- ---------------------------------------------------------------------
-- PART A: real data
-- ---------------------------------------------------------------------
ANALYZE TABLE attendance;                                 -- refresh optimiser statistics
DROP INDEX idx_att_date ON attendance;                    -- BEFORE: remove the index

EXPLAIN
SELECT emp_id, COUNT(*) AS late_marks
FROM attendance
WHERE att_date BETWEEN '2026-10-01' AND '2026-10-31'
  AND TIME(check_in) > '09:45:00'
GROUP BY emp_id;

CREATE INDEX idx_att_date ON attendance (att_date);       -- AFTER: add it back
ANALYZE TABLE attendance;

EXPLAIN
SELECT emp_id, COUNT(*) AS late_marks
FROM attendance
WHERE att_date BETWEEN '2026-10-01' AND '2026-10-31'
  AND TIME(check_in) > '09:45:00'
GROUP BY emp_id;

-- Salary-slip report filters payroll by month -> idx_pay_month
EXPLAIN SELECT * FROM payroll WHERE pay_month = '2026-10-01';

-- ---------------------------------------------------------------------
-- PART B: scaled benchmark (a temporary copy, dropped at the end)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS attendance_bench;
CREATE TABLE attendance_bench (
    attendance_id  INT AUTO_INCREMENT PRIMARY KEY,
    emp_id         INT      NOT NULL,
    att_date       DATE     NOT NULL,
    check_in       DATETIME NOT NULL,
    check_out      DATETIME NULL,
    UNIQUE KEY uq_bench_emp_date (emp_id, att_date)       -- same as the real table
);

SET SESSION cte_max_recursion_depth = 2000;
INSERT INTO attendance_bench (emp_id, att_date, check_in, check_out)
WITH RECURSIVE emps AS (SELECT 1 AS e UNION ALL SELECT e + 1 FROM emps WHERE e < 1000),
               days AS (SELECT 0 AS d UNION ALL SELECT d + 1 FROM days WHERE d < 364)
SELECT e,
       DATE('2026-01-01') + INTERVAL d DAY,
       TIMESTAMP(DATE('2026-01-01') + INTERVAL d DAY, '09:00:00') + INTERVAL ((e * 7 + d * 13) % 75) MINUTE,
       TIMESTAMP(DATE('2026-01-01') + INTERVAL d DAY, '18:30:00') + INTERVAL ((e * 11 + d * 3) % 90) MINUTE
FROM emps CROSS JOIN days;
ANALYZE TABLE attendance_bench;

SELECT COUNT(*) AS benchmark_rows FROM attendance_bench;

-- Stage 1: no date index -> full table scan
EXPLAIN ANALYZE
SELECT emp_id, COUNT(*) AS late_marks FROM attendance_bench
WHERE att_date BETWEEN '2026-10-01' AND '2026-10-31' AND TIME(check_in) > '09:45:00'
GROUP BY emp_id;

-- Stage 2: single-column index on the filter column -> range scan
CREATE INDEX idx_bench_date ON attendance_bench (att_date);
ANALYZE TABLE attendance_bench;
EXPLAIN ANALYZE
SELECT emp_id, COUNT(*) AS late_marks FROM attendance_bench
WHERE att_date BETWEEN '2026-10-01' AND '2026-10-31' AND TIME(check_in) > '09:45:00'
GROUP BY emp_id;

-- Stage 3: covering index (every column the query needs is in the index,
--          so MySQL never reads the table rows: "Using index")
CREATE INDEX idx_bench_date_cover ON attendance_bench (att_date, emp_id, check_in);
ANALYZE TABLE attendance_bench;
EXPLAIN ANALYZE
SELECT emp_id, COUNT(*) AS late_marks FROM attendance_bench
WHERE att_date BETWEEN '2026-10-01' AND '2026-10-31' AND TIME(check_in) > '09:45:00'
GROUP BY emp_id;

DROP TABLE attendance_bench;
