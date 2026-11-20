-- =====================================================================
--  File 02: Stored functions
-- =====================================================================
USE payroll_db;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Policy in force on a given date (latest effective_from <= date)
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_policy_id $$
CREATE FUNCTION fn_policy_id(p_date DATE)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_id INT;
    SELECT policy_id INTO v_id
    FROM payroll_policy
    WHERE effective_from <= p_date
    ORDER BY effective_from DESC
    LIMIT 1;
    RETURN v_id;
END $$

-- ---------------------------------------------------------------------
-- Is the date a working day? (not weekend, not a holiday)
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_is_working_day $$
CREATE FUNCTION fn_is_working_day(p_date DATE)
RETURNS BOOLEAN
READS SQL DATA
BEGIN
    RETURN DAYOFWEEK(p_date) NOT IN (1, 7)               -- 1 = Sunday, 7 = Saturday
       AND NOT EXISTS (SELECT 1 FROM holidays WHERE holiday_date = p_date);
END $$

-- ---------------------------------------------------------------------
-- Number of working days in a month
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_working_days $$
CREATE FUNCTION fn_working_days(p_year INT, p_month INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_start DATE DEFAULT MAKEDATE(p_year, 1) + INTERVAL (p_month - 1) MONTH;
    DECLARE v_count INT;
    SELECT COUNT(*) INTO v_count
    FROM calendar c
    LEFT JOIN holidays h ON h.holiday_date = c.cal_date
    WHERE c.cal_date BETWEEN v_start AND LAST_DAY(v_start)
      AND c.is_weekend = FALSE
      AND h.holiday_date IS NULL;
    RETURN v_count;
END $$

-- ---------------------------------------------------------------------
-- Overtime minutes for one attendance record
--   Weekday : time beyond std_work_minutes, ignored below min_ot_minutes,
--             capped at max_ot_minutes_per_day
--   Weekend/holiday : every minute worked is overtime (capped at one shift)
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_ot_minutes $$
CREATE FUNCTION fn_ot_minutes(p_date DATE, p_worked INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_std, v_min, v_max INT;
    DECLARE v_extra INT;

    IF p_worked IS NULL THEN
        RETURN 0;                           -- no check-out yet, no OT
    END IF;

    SELECT std_work_minutes, min_ot_minutes, max_ot_minutes_per_day
      INTO v_std, v_min, v_max
    FROM payroll_policy WHERE policy_id = fn_policy_id(p_date);

    IF NOT fn_is_working_day(p_date) THEN
        RETURN LEAST(p_worked, v_std);
    END IF;

    SET v_extra = p_worked - v_std;
    IF v_extra < v_min THEN
        RETURN 0;
    END IF;
    RETURN LEAST(v_extra, v_max);
END $$

-- ---------------------------------------------------------------------
-- Annual income tax (simplified new regime) for a given taxable income
--   tax = sum over slabs of rate * (portion of income inside the slab)
--   zero if taxable income <= rebate limit (with marginal relief just above it),
--   then + 4% cess
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_annual_tax $$
CREATE FUNCTION fn_annual_tax(p_taxable DECIMAL(12,2), p_date DATE)
RETURNS DECIMAL(12,2)
READS SQL DATA
BEGIN
    DECLARE v_tax DECIMAL(12,2);
    DECLARE v_rebate_limit, v_cess DECIMAL(12,3);

    SELECT tax_rebate_limit, cess_rate INTO v_rebate_limit, v_cess
    FROM payroll_policy WHERE policy_id = fn_policy_id(p_date);

    IF p_taxable <= v_rebate_limit THEN
        RETURN 0;
    END IF;

    SELECT COALESCE(SUM(rate * GREATEST(0,
               LEAST(p_taxable, COALESCE(upper_limit, p_taxable)) - lower_limit)), 0)
      INTO v_tax
    FROM tax_slabs;

    -- marginal relief: tax may not exceed the income above the rebate limit
    SET v_tax = LEAST(v_tax, p_taxable - v_rebate_limit);

    RETURN ROUND(v_tax * (1 + v_cess), 2);
END $$

-- ---------------------------------------------------------------------
-- Monthly TDS: project this month's taxable pay over a year,
-- subtract standard deduction, compute annual tax, divide by 12
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_monthly_tds $$
CREATE FUNCTION fn_monthly_tds(p_monthly_income DECIMAL(12,2), p_date DATE)
RETURNS DECIMAL(10,2)
READS SQL DATA
BEGIN
    DECLARE v_std_ded DECIMAL(12,2);
    SELECT standard_deduction INTO v_std_ded
    FROM payroll_policy WHERE policy_id = fn_policy_id(p_date);

    RETURN ROUND(fn_annual_tax(GREATEST(p_monthly_income * 12 - v_std_ded, 0), p_date) / 12, 0);
END $$

-- ---------------------------------------------------------------------
-- Salary component in force for an employee on a date
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_salary_id $$
CREATE FUNCTION fn_salary_id(p_emp INT, p_date DATE)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_id INT;
    SELECT salary_id INTO v_id
    FROM salary_structure
    WHERE emp_id = p_emp AND effective_from <= p_date
    ORDER BY effective_from DESC
    LIMIT 1;
    RETURN v_id;
END $$

DELIMITER ;
