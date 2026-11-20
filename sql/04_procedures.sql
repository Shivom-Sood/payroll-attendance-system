-- =====================================================================
--  File 04: Stored procedures
--  All business rules live here, so the Python app stays thin.
--  Errors are raised with SIGNAL SQLSTATE '45000' and a readable message.
-- =====================================================================
USE payroll_db;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Fill the calendar table for a date range (recursive CTE)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_fill_calendar $$
CREATE PROCEDURE sp_fill_calendar(IN p_start DATE, IN p_end DATE)
BEGIN
    SET SESSION cte_max_recursion_depth = 10000;
    INSERT IGNORE INTO calendar (cal_date, is_weekend)
    WITH RECURSIVE dates AS (
        SELECT p_start AS d
        UNION ALL
        SELECT d + INTERVAL 1 DAY FROM dates WHERE d < p_end
    )
    SELECT d, DAYOFWEEK(d) IN (1, 7) FROM dates;
END $$

-- ---------------------------------------------------------------------
-- Add an employee with salary structure and app login, in ONE transaction
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_add_employee $$
CREATE PROCEDURE sp_add_employee(
    IN p_first VARCHAR(40), IN p_last VARCHAR(40), IN p_email VARCHAR(100),
    IN p_phone VARCHAR(15), IN p_gender CHAR(1),   IN p_hire_date DATE,
    IN p_dept_id INT,       IN p_designation VARCHAR(60), IN p_manager_id INT,
    IN p_basic DECIMAL(10,2), IN p_hra DECIMAL(10,2), IN p_special DECIMAL(10,2),
    IN p_username VARCHAR(30), IN p_password VARCHAR(100), IN p_role VARCHAR(10),
    OUT p_emp_id INT)
BEGIN
    DECLARE v_salt CHAR(32);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF CHAR_LENGTH(p_password) < 6 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Password must be at least 6 characters';
    END IF;
    IF p_basic IS NULL OR p_basic <= 0 OR p_hra < 0 OR p_special < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Basic must be positive and allowances cannot be negative';
    END IF;

    START TRANSACTION;
        INSERT INTO employees (first_name, last_name, email, phone, gender, hire_date,
                               dept_id, designation, manager_id)
        VALUES (p_first, p_last, p_email, p_phone, p_gender, p_hire_date,
                p_dept_id, p_designation, p_manager_id);
        SET p_emp_id = LAST_INSERT_ID();

        INSERT INTO salary_structure (emp_id, basic, hra, special_allowance, effective_from)
        VALUES (p_emp_id, p_basic, p_hra, p_special, p_hire_date);

        SET v_salt = MD5(CONCAT(RAND(), NOW(6), p_username));
        INSERT INTO app_users (emp_id, username, password_hash, salt, role)
        VALUES (p_emp_id, p_username, SHA2(CONCAT(v_salt, p_password), 256), v_salt, p_role);
    COMMIT;
END $$

-- ---------------------------------------------------------------------
-- Salary revision (adds a new row; history is kept)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_update_salary $$
CREATE PROCEDURE sp_update_salary(
    IN p_emp_id INT, IN p_basic DECIMAL(10,2), IN p_hra DECIMAL(10,2),
    IN p_special DECIMAL(10,2), IN p_effective_from DATE)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;            -- undo the salary row AND its audit-log row
        RESIGNAL;
    END;

    IF NOT EXISTS (SELECT 1 FROM employees WHERE emp_id = p_emp_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Employee not found';
    END IF;
    IF p_basic IS NULL OR p_basic <= 0 OR p_hra < 0 OR p_special < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Basic must be positive and allowances cannot be negative';
    END IF;
    IF EXISTS (SELECT 1 FROM payroll
               WHERE emp_id = p_emp_id AND status = 'PAID'
                 AND pay_month >= DATE_FORMAT(p_effective_from, '%Y-%m-01')) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot back-date a revision into an already paid month';
    END IF;

    START TRANSACTION;
        INSERT INTO salary_structure (emp_id, basic, hra, special_allowance, effective_from)
        VALUES (p_emp_id, p_basic, p_hra, p_special, p_effective_from)
        ON DUPLICATE KEY UPDATE basic = p_basic, hra = p_hra, special_allowance = p_special;
    COMMIT;
END $$

-- ---------------------------------------------------------------------
-- Daily check-in / check-out (uses the current server time)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_check_in $$
CREATE PROCEDURE sp_check_in(IN p_emp_id INT)
BEGIN
    IF EXISTS (SELECT 1 FROM attendance WHERE emp_id = p_emp_id AND att_date = CURDATE()) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Already checked in today';
    END IF;
    INSERT INTO attendance (emp_id, att_date, check_in)
    VALUES (p_emp_id, CURDATE(), NOW());
    SELECT 'Checked in' AS message, NOW() AS at_time;
END $$

DROP PROCEDURE IF EXISTS sp_check_out $$
CREATE PROCEDURE sp_check_out(IN p_emp_id INT)
BEGIN
    DECLARE v_id INT;
    DECLARE v_out DATETIME;

    SELECT attendance_id, check_out INTO v_id, v_out
    FROM attendance WHERE emp_id = p_emp_id AND att_date = CURDATE();

    IF v_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You have not checked in today';
    ELSEIF v_out IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Already checked out today';
    ELSEIF (SELECT check_in FROM attendance WHERE attendance_id = v_id) >= NOW() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Check-out must be later than check-in';
    END IF;

    UPDATE attendance SET check_out = NOW() WHERE attendance_id = v_id;

    SELECT 'Checked out' AS message, check_in, check_out,
           CONCAT(FLOOR(worked_minutes / 60), 'h ', MOD(worked_minutes, 60), 'm') AS worked,
           fn_ot_minutes(att_date, worked_minutes) AS ot_minutes_today
    FROM attendance WHERE attendance_id = v_id;
END $$

-- ---------------------------------------------------------------------
-- HR correction of an attendance record (e.g. missed punch)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_upsert_attendance $$
CREATE PROCEDURE sp_upsert_attendance(
    IN p_emp_id INT, IN p_date DATE, IN p_check_in DATETIME, IN p_check_out DATETIME)
BEGIN
    INSERT INTO attendance (emp_id, att_date, check_in, check_out)
    VALUES (p_emp_id, p_date, p_check_in, p_check_out)
    ON DUPLICATE KEY UPDATE check_in = p_check_in, check_out = p_check_out;
END $$

-- ---------------------------------------------------------------------
-- Apply for leave (balance checked for paid leave types)
-- Overlapping requests are blocked by trigger trg_leave_before_insert.
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_apply_leave $$
CREATE PROCEDURE sp_apply_leave(
    IN p_emp_id INT, IN p_code VARCHAR(5), IN p_from DATE, IN p_to DATE, IN p_reason VARCHAR(200))
BEGIN
    DECLARE v_type_id INT;
    DECLARE v_quota INT;
    DECLARE v_requested INT;
    DECLARE v_used INT;

    SELECT leave_type_id, annual_quota INTO v_type_id, v_quota
    FROM leave_types WHERE code = p_code;

    IF v_type_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown leave type';
    END IF;
    IF p_to < p_from THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'End date is before start date';
    END IF;
    IF YEAR(p_from) <> YEAR(p_to) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Split leave that crosses a year end into two requests';
    END IF;

    SELECT COUNT(*) INTO v_requested
    FROM calendar c
    WHERE c.cal_date BETWEEN p_from AND p_to
      AND c.is_weekend = FALSE
      AND c.cal_date NOT IN (SELECT holiday_date FROM holidays);

    IF v_requested = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Selected dates contain no working days';
    END IF;

    IF v_quota IS NOT NULL THEN
        -- days already approved or pending for this type in the same year
        SELECT COALESCE(SUM(working_days), 0) INTO v_used
        FROM v_leave_requests
        WHERE emp_id = p_emp_id AND leave_code = p_code
          AND status IN ('APPROVED', 'PENDING')
          AND YEAR(from_date) = YEAR(p_from);

        IF v_used + v_requested > v_quota THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Insufficient leave balance for this leave type';
        END IF;
    END IF;

    INSERT INTO leave_requests (emp_id, leave_type_id, from_date, to_date, reason)
    VALUES (p_emp_id, v_type_id, p_from, p_to, p_reason);

    SELECT LAST_INSERT_ID() AS leave_id, v_requested AS working_days, 'PENDING' AS status;
END $$

-- ---------------------------------------------------------------------
-- Approve / reject a leave request (HR only, not your own)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_review_leave $$
CREATE PROCEDURE sp_review_leave(IN p_leave_id INT, IN p_reviewer INT, IN p_decision VARCHAR(10))
BEGIN
    DECLARE v_status VARCHAR(10);
    DECLARE v_emp INT;

    IF p_decision NOT IN ('APPROVED', 'REJECTED') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Decision must be APPROVED or REJECTED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app_users WHERE emp_id = p_reviewer AND role = 'HR_ADMIN') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only HR admins can review leave';
    END IF;

    SELECT status, emp_id INTO v_status, v_emp FROM leave_requests WHERE leave_id = p_leave_id;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Leave request not found';
    ELSEIF v_status <> 'PENDING' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Leave request was already reviewed';
    ELSEIF v_emp = p_reviewer THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You cannot review your own leave';
    END IF;

    UPDATE leave_requests
    SET status = p_decision, reviewed_by = p_reviewer, reviewed_on = NOW()
    WHERE leave_id = p_leave_id;
END $$

-- ---------------------------------------------------------------------
-- MONTHLY PAYROLL RUN
--   1. month must be over, and not already paid
--   2. attendance figures come from v_daily_attendance
--   3. salary  = fixed pay + overtime pay
--                - loss of pay (absent / unpaid leave / days before joining)
--                - late-mark deduction - PF - TDS
--   Re-running replaces PROCESSED rows for that month (all in one transaction).
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_generate_payroll $$
CREATE PROCEDURE sp_generate_payroll(IN p_year INT, IN p_month INT)
BEGIN
    DECLARE v_start DATE;
    DECLARE v_end   DATE;
    DECLARE v_wd    INT;
    DECLARE v_rate_w, v_rate_h DECIMAL(3,2);
    DECLARE v_late_per_half INT;
    DECLARE v_pf_rate DECIMAL(4,3);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_month NOT BETWEEN 1 AND 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Month must be 1-12';
    END IF;

    SET v_start = MAKEDATE(p_year, 1) + INTERVAL (p_month - 1) MONTH;
    SET v_end   = LAST_DAY(v_start);

    IF v_end >= CURDATE() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payroll can only be generated after the month has ended';
    END IF;
    IF EXISTS (SELECT 1 FROM payroll WHERE pay_month = v_start AND status = 'PAID') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payroll for this month is already PAID and locked';
    END IF;

    CALL sp_fill_calendar(v_start, v_end);
    SET v_wd = fn_working_days(p_year, p_month);

    SELECT ot_rate_weekday, ot_rate_holiday, late_marks_per_half_day, pf_rate
      INTO v_rate_w, v_rate_h, v_late_per_half, v_pf_rate
    FROM payroll_policy WHERE policy_id = fn_policy_id(v_end);

    START TRANSACTION;

    DELETE FROM payroll WHERE pay_month = v_start AND status = 'PROCESSED';

    INSERT INTO payroll (
        emp_id, pay_month, working_days, present_days, paid_leave_days, unpaid_leave_days,
        absent_days, lop_days, late_marks, regular_hours, ot_hours_weekday, ot_hours_holiday,
        basic, hra, special_allowance, ot_pay, gross_earnings,
        lop_deduction, late_deduction, pf, tds, total_deductions, net_salary)
    WITH att AS (                       -- attendance totals for the month
        SELECT  emp_id,
                SUM(present_value)       AS present_days,
                SUM(paid_leave_value)    AS paid_leave_days,
                SUM(unpaid_leave_value)  AS unpaid_leave_days,
                SUM(absent_value)        AS absent_days,
                SUM(is_late)             AS late_marks,
                SUM(regular_minutes)     / 60 AS regular_hours,
                SUM(ot_weekday_minutes)  / 60 AS ot_hours_weekday,
                SUM(ot_holiday_minutes)  / 60 AS ot_hours_holiday
        FROM v_daily_attendance
        WHERE cal_date BETWEEN v_start AND v_end
        GROUP BY emp_id
    ),
    base AS (                           -- salary in force + attendance
        SELECT  e.emp_id,
                s.basic, s.hra, s.special_allowance,
                s.basic + s.hra + s.special_allowance            AS fixed_pay,
                COALESCE(a.present_days, 0)                      AS present_days,
                COALESCE(a.paid_leave_days, 0)                   AS paid_leave_days,
                COALESCE(a.unpaid_leave_days, 0)                 AS unpaid_leave_days,
                COALESCE(a.absent_days, 0)                       AS absent_days,
                COALESCE(a.late_marks, 0)                        AS late_marks,
                COALESCE(a.regular_hours, 0)                     AS regular_hours,
                COALESCE(a.ot_hours_weekday, 0)                  AS ot_hours_weekday,
                COALESCE(a.ot_hours_holiday, 0)                  AS ot_hours_holiday
        FROM employees e
        JOIN salary_structure s ON s.salary_id = fn_salary_id(e.emp_id, v_end)
        LEFT JOIN att a         ON a.emp_id = e.emp_id
        WHERE e.status = 'ACTIVE' AND e.hire_date <= v_end
    ),
    rates AS (                          -- per-day and per-hour rates, LOP days
        SELECT  b.*,
                b.fixed_pay / v_wd                                         AS per_day,
                b.basic / (v_wd * 8)                                       AS per_hour,
                GREATEST(v_wd - b.present_days - b.paid_leave_days, 0)     AS lop_days
        FROM base b
    ),
    earnings AS (
        SELECT  r.*,
                ROUND(r.per_hour * (r.ot_hours_weekday * v_rate_w
                                  + r.ot_hours_holiday * v_rate_h), 2)     AS ot_pay,
                ROUND(r.per_day * r.lop_days, 2)                           AS lop_deduction,
                ROUND(FLOOR(r.late_marks / v_late_per_half) * 0.5 * r.per_day, 2) AS late_deduction,
                ROUND(v_pf_rate * r.basic * (v_wd - r.lop_days) / v_wd, 2) AS pf
        FROM rates r
    ),
    final AS (
        SELECT  e.*,
                e.fixed_pay + e.ot_pay                                     AS gross_earnings,
                fn_monthly_tds(e.fixed_pay + e.ot_pay - e.lop_deduction - e.late_deduction,
                               v_end)                                      AS tds
        FROM earnings e
    )
    SELECT  emp_id, v_start, v_wd, present_days, paid_leave_days, unpaid_leave_days,
            absent_days, lop_days, late_marks,
            ROUND(regular_hours, 2), ROUND(ot_hours_weekday, 2), ROUND(ot_hours_holiday, 2),
            basic, hra, special_allowance, ot_pay, gross_earnings,
            lop_deduction, late_deduction, pf, tds,
            lop_deduction + late_deduction + pf + tds                      AS total_deductions,
            gross_earnings - (lop_deduction + late_deduction + pf + tds)   AS net_salary
    FROM final;

    COMMIT;

    SELECT DATE_FORMAT(v_start, '%M %Y') AS payroll_month,
           v_wd                          AS working_days,
           COUNT(*)                      AS employees_processed,
           SUM(gross_earnings)           AS total_gross,
           SUM(net_salary)               AS total_net
    FROM payroll WHERE pay_month = v_start;
END $$

-- ---------------------------------------------------------------------
-- Mark a processed month as PAID (locks it via trigger)
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_mark_payroll_paid $$
CREATE PROCEDURE sp_mark_payroll_paid(IN p_year INT, IN p_month INT)
BEGIN
    DECLARE v_start DATE DEFAULT MAKEDATE(p_year, 1) + INTERVAL (p_month - 1) MONTH;
    DECLARE v_rows INT;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;            -- either every employee is marked PAID or none is
        RESIGNAL;
    END;

    IF NOT EXISTS (SELECT 1 FROM payroll WHERE pay_month = v_start) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No payroll generated for this month';
    END IF;

    START TRANSACTION;
        UPDATE payroll SET status = 'PAID' WHERE pay_month = v_start AND status = 'PROCESSED';
        SET v_rows = ROW_COUNT();
    COMMIT;
    SELECT v_rows AS rows_marked_paid;
END $$

-- ---------------------------------------------------------------------
-- Salary slip for one employee and month
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_salary_slip $$
CREATE PROCEDURE sp_salary_slip(IN p_emp_id INT, IN p_year INT, IN p_month INT)
BEGIN
    DECLARE v_start DATE DEFAULT MAKEDATE(p_year, 1) + INTERVAL (p_month - 1) MONTH;
    IF NOT EXISTS (SELECT 1 FROM payroll WHERE emp_id = p_emp_id AND pay_month = v_start) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No salary slip for this employee and month';
    END IF;
    SELECT * FROM v_salary_slip WHERE emp_id = p_emp_id AND pay_month = v_start;
END $$

DELIMITER ;
