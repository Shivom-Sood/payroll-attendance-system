-- =====================================================================
--  File 03: Views (reporting layer)
-- =====================================================================
USE payroll_db;

-- ---------------------------------------------------------------------
-- Employee directory: department, manager name, current salary
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_employee_directory AS
SELECT  e.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)  AS employee_name,
        e.email,
        e.designation,
        d.dept_name,
        CONCAT(m.first_name, ' ', m.last_name)  AS manager_name,
        e.hire_date,
        e.status,
        s.basic,
        s.hra,
        s.special_allowance,
        (s.basic + s.hra + s.special_allowance) AS monthly_ctc_fixed
FROM employees e
JOIN departments d            ON d.dept_id = e.dept_id
LEFT JOIN employees m         ON m.emp_id  = e.manager_id
LEFT JOIN salary_structure s  ON s.salary_id = fn_salary_id(e.emp_id, CURDATE());

-- ---------------------------------------------------------------------
-- CORE VIEW: one row per employee per calendar day (from hire date to today)
-- Classifies each day and works out late marks, regular and overtime minutes.
-- Every monthly report and the payroll procedure are built on top of this.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_daily_attendance AS
WITH days AS (
    SELECT  e.emp_id,
            c.cal_date,
            CASE WHEN h.holiday_date IS NOT NULL THEN 'HOLIDAY'
                 WHEN c.is_weekend              THEN 'WEEKEND'
                 ELSE 'WORKING' END                       AS day_type,
            a.attendance_id,
            a.check_in,
            a.check_out,
            a.worked_minutes,
            lt.code                                       AS leave_code,
            lt.is_paid                                    AS leave_is_paid,
            p.shift_start, p.grace_minutes, p.std_work_minutes,
            p.full_day_min_minutes, p.half_day_min_minutes
    FROM employees e
    JOIN calendar c          ON c.cal_date BETWEEN e.hire_date AND CURDATE()
    JOIN payroll_policy p    ON p.policy_id = fn_policy_id(c.cal_date)
    LEFT JOIN holidays h     ON h.holiday_date = c.cal_date
    LEFT JOIN attendance a   ON a.emp_id = e.emp_id AND a.att_date = c.cal_date
    LEFT JOIN leave_requests lr
                             ON lr.emp_id = e.emp_id
                            AND lr.status = 'APPROVED'
                            AND c.cal_date BETWEEN lr.from_date AND lr.to_date
    LEFT JOIN leave_types lt ON lt.leave_type_id = lr.leave_type_id
),
classified AS (
    SELECT  d.*,
            CASE
                WHEN d.day_type <> 'WORKING' AND d.attendance_id IS NOT NULL THEN 'EXTRA_DAY'
                WHEN d.day_type <> 'WORKING'                                 THEN 'OFF'
                WHEN d.attendance_id IS NOT NULL AND d.check_out IS NULL
                     AND d.cal_date = CURDATE()                              THEN 'IN_OFFICE'
                WHEN d.attendance_id IS NOT NULL AND d.check_out IS NULL     THEN 'MISSED_PUNCH'
                WHEN d.worked_minutes >= d.full_day_min_minutes              THEN 'PRESENT'
                WHEN d.worked_minutes >= d.half_day_min_minutes              THEN 'HALF_DAY'
                WHEN d.leave_code IS NOT NULL AND d.leave_is_paid            THEN 'PAID_LEAVE'
                WHEN d.leave_code IS NOT NULL                                THEN 'UNPAID_LEAVE'
                WHEN d.cal_date = CURDATE()                                  THEN 'NOT_MARKED_YET'
                ELSE 'ABSENT'
            END AS day_status
    FROM days d
)
SELECT  emp_id,
        cal_date,
        day_type,
        day_status,
        check_in,
        check_out,
        worked_minutes,
        leave_code,
        -- late mark: checked in after shift start + grace on a working day
        (day_type = 'WORKING' AND check_in IS NOT NULL
         AND TIME(check_in) > ADDTIME(shift_start, SEC_TO_TIME(grace_minutes * 60)))  AS is_late,
        CASE day_status WHEN 'PRESENT' THEN 1 WHEN 'IN_OFFICE' THEN 1
                        WHEN 'HALF_DAY' THEN 0.5 WHEN 'MISSED_PUNCH' THEN 0.5
                        ELSE 0 END                                                    AS present_value,
        CASE day_status WHEN 'PAID_LEAVE' THEN 1 ELSE 0 END                           AS paid_leave_value,
        CASE day_status WHEN 'UNPAID_LEAVE' THEN 1 ELSE 0 END                         AS unpaid_leave_value,
        CASE day_status WHEN 'ABSENT' THEN 1
                        WHEN 'HALF_DAY' THEN 0.5 WHEN 'MISSED_PUNCH' THEN 0.5
                        ELSE 0 END                                                    AS absent_value,
        CASE WHEN day_type = 'WORKING' THEN LEAST(COALESCE(worked_minutes, 0), std_work_minutes)
             ELSE 0 END                                                               AS regular_minutes,
        CASE WHEN day_type = 'WORKING' THEN fn_ot_minutes(cal_date, worked_minutes)
             ELSE 0 END                                                               AS ot_weekday_minutes,
        CASE WHEN day_type <> 'WORKING' THEN fn_ot_minutes(cal_date, worked_minutes)
             ELSE 0 END                                                               AS ot_holiday_minutes
FROM classified;

-- ---------------------------------------------------------------------
-- REPORT: Monthly attendance per employee
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_monthly_attendance AS
SELECT  da.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)             AS employee_name,
        d.dept_name,
        CAST(DATE_FORMAT(da.cal_date, '%Y-%m-01') AS DATE) AS pay_month,
        SUM(da.day_type = 'WORKING')                       AS working_days_elapsed,
        SUM(da.present_value)                              AS present_days,
        SUM(da.day_status = 'HALF_DAY')                    AS half_days,
        SUM(da.day_status = 'MISSED_PUNCH')                AS missed_punches,
        SUM(da.paid_leave_value)                           AS paid_leave_days,
        SUM(da.unpaid_leave_value)                         AS unpaid_leave_days,
        SUM(da.absent_value)                               AS absent_days,
        SUM(da.is_late)                                    AS late_marks,
        SUM(da.day_status = 'EXTRA_DAY')                   AS extra_days_worked,
        ROUND(SUM(COALESCE(da.worked_minutes, 0)) / 60, 2) AS total_hours,
        ROUND(SUM(da.regular_minutes) / 60, 2)             AS regular_hours,
        ROUND(SUM(da.ot_weekday_minutes) / 60, 2)          AS ot_hours_weekday,
        ROUND(SUM(da.ot_holiday_minutes) / 60, 2)          AS ot_hours_holiday
FROM v_daily_attendance da
JOIN employees   e ON e.emp_id  = da.emp_id
JOIN departments d ON d.dept_id = e.dept_id
GROUP BY da.emp_id, employee_name, d.dept_name, pay_month;

-- ---------------------------------------------------------------------
-- REPORT: Late marks per employee per month, with the actual dates
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_late_marks AS
SELECT  da.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)                   AS employee_name,
        CAST(DATE_FORMAT(da.cal_date, '%Y-%m-01') AS DATE)       AS pay_month,
        COUNT(*)                                                 AS late_marks,
        GROUP_CONCAT(CONCAT(DATE_FORMAT(da.cal_date, '%d %b'), ' (', TIME_FORMAT(da.check_in, '%H:%i'), ')')
                     ORDER BY da.cal_date SEPARATOR ', ')        AS late_on
FROM v_daily_attendance da
JOIN employees e ON e.emp_id = da.emp_id
WHERE da.is_late
GROUP BY da.emp_id, employee_name, pay_month;

-- ---------------------------------------------------------------------
-- REPORT: Salary slip (one row per employee per processed month)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_salary_slip AS
SELECT  p.payroll_id,
        p.pay_month,
        DATE_FORMAT(p.pay_month, '%M %Y')         AS month_label,
        e.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)    AS employee_name,
        e.designation,
        d.dept_name,
        e.hire_date,
        p.working_days, p.present_days, p.paid_leave_days, p.unpaid_leave_days,
        p.absent_days, p.lop_days, p.late_marks,
        p.regular_hours, p.ot_hours_weekday, p.ot_hours_holiday,
        p.basic, p.hra, p.special_allowance, p.ot_pay, p.gross_earnings,
        p.lop_deduction, p.late_deduction, p.pf, p.tds, p.total_deductions,
        p.net_salary, p.status, p.processed_on
FROM payroll p
JOIN employees   e ON e.emp_id  = p.emp_id
JOIN departments d ON d.dept_id = e.dept_id;

-- ---------------------------------------------------------------------
-- REPORT: Overtime summary, ranked within each month (window function)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_overtime_summary AS
SELECT  p.pay_month,
        e.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)                    AS employee_name,
        d.dept_name,
        p.ot_hours_weekday,
        p.ot_hours_holiday,
        p.ot_hours_weekday + p.ot_hours_holiday                   AS total_ot_hours,
        p.ot_pay,
        RANK() OVER (PARTITION BY p.pay_month
                     ORDER BY p.ot_hours_weekday + p.ot_hours_holiday DESC) AS ot_rank_in_company,
        ROUND(100 * p.ot_pay / NULLIF(SUM(p.ot_pay) OVER (PARTITION BY p.pay_month), 0), 1)
                                                                  AS pct_of_month_ot_pay
FROM payroll p
JOIN employees   e ON e.emp_id  = p.emp_id
JOIN departments d ON d.dept_id = e.dept_id;

-- ---------------------------------------------------------------------
-- REPORT: Payroll expenditure statement by department and month
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_payroll_expenditure AS
SELECT  p.pay_month,
        d.dept_name,
        COUNT(*)                     AS headcount,
        SUM(p.gross_earnings)        AS total_gross,
        SUM(p.ot_pay)                AS total_ot_pay,
        SUM(p.lop_deduction + p.late_deduction) AS total_attendance_deductions,
        SUM(p.pf)                    AS total_pf,
        SUM(p.tds)                   AS total_tds,
        SUM(p.net_salary)            AS total_net_paid,
        ROUND(100 * SUM(p.gross_earnings)
              / SUM(SUM(p.gross_earnings)) OVER (PARTITION BY p.pay_month), 1) AS pct_of_company_gross
FROM payroll p
JOIN employees   e ON e.emp_id  = p.emp_id
JOIN departments d ON d.dept_id = e.dept_id
GROUP BY p.pay_month, d.dept_name;

-- ---------------------------------------------------------------------
-- Leave requests with names and number of working days covered
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_leave_requests AS
SELECT  lr.leave_id,
        lr.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)  AS employee_name,
        lt.code                                 AS leave_code,
        lt.leave_name,
        lt.is_paid,
        lr.from_date,
        lr.to_date,
        (SELECT COUNT(*) FROM calendar c
          WHERE c.cal_date BETWEEN lr.from_date AND lr.to_date
            AND c.is_weekend = FALSE
            AND c.cal_date NOT IN (SELECT holiday_date FROM holidays)) AS working_days,
        lr.reason,
        lr.status,
        lr.applied_on,
        CONCAT(r.first_name, ' ', r.last_name)  AS reviewed_by_name,
        lr.reviewed_on
FROM leave_requests lr
JOIN employees   e  ON e.emp_id = lr.emp_id
JOIN leave_types lt ON lt.leave_type_id = lr.leave_type_id
LEFT JOIN employees r ON r.emp_id = lr.reviewed_by;

-- ---------------------------------------------------------------------
-- Leave balance for the current calendar year (paid leave types)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_leave_balance AS
SELECT  e.emp_id,
        CONCAT(e.first_name, ' ', e.last_name)          AS employee_name,
        lt.code                                         AS leave_code,
        lt.leave_name,
        lt.annual_quota,
        COALESCE(SUM(CASE WHEN v.status = 'APPROVED' THEN v.working_days END), 0) AS used_days,
        COALESCE(SUM(CASE WHEN v.status = 'PENDING'  THEN v.working_days END), 0) AS pending_days,
        lt.annual_quota
          - COALESCE(SUM(CASE WHEN v.status = 'APPROVED' THEN v.working_days END), 0) AS remaining_days
FROM employees e
CROSS JOIN leave_types lt
LEFT JOIN v_leave_requests v
       ON v.emp_id = e.emp_id
      AND v.leave_code = lt.code
      AND YEAR(v.from_date) = YEAR(CURDATE())
WHERE lt.annual_quota IS NOT NULL
GROUP BY e.emp_id, employee_name, lt.code, lt.leave_name, lt.annual_quota;
