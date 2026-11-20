-- =====================================================================
--  File 07: Role-based access control at the DATABASE level (DCL)
--
--  Two layers of security in this project:
--   1. The Python app logs users in (app_users table) and shows an HR or
--      an Employee menu. It connects with the limited 'payroll_app' account.
--   2. This file: MySQL roles, so even someone using MySQL Workbench directly
--      can only do what their role allows.
--        payroll_hr        -> full read/write on payroll_db
--        payroll_employee  -> ONLY the v_my_* views and sp_my_* procedures,
--                             which show the logged-in user's own rows
--
--  The v_my_* views use SQL SECURITY DEFINER and filter on USER(), the
--  account that is actually connected. So 'rahul' can read v_my_payslips,
--  but sees only Rahul's slips and has no access to the payroll table.
-- =====================================================================
USE payroll_db;

-- ---------------------------------------------------------------------
-- Helper: emp_id of the connected MySQL account (matched to app_users.username)
-- ---------------------------------------------------------------------
DELIMITER $$
DROP FUNCTION IF EXISTS fn_current_emp_id $$
CREATE FUNCTION fn_current_emp_id()
RETURNS INT
READS SQL DATA
SQL SECURITY DEFINER
BEGIN
    DECLARE v_id INT;
    SELECT emp_id INTO v_id FROM app_users
    WHERE username = SUBSTRING_INDEX(USER(), '@', 1) AND is_active;
    RETURN v_id;
END $$
DELIMITER ;

-- ---------------------------------------------------------------------
-- Self-service views (row-level security through the definer + USER())
-- ---------------------------------------------------------------------
CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_my_profile AS
SELECT * FROM v_employee_directory WHERE emp_id = fn_current_emp_id();

CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_my_attendance AS
SELECT cal_date, day_type, day_status, check_in, check_out, worked_minutes, is_late,
       ot_weekday_minutes + ot_holiday_minutes AS ot_minutes
FROM v_daily_attendance WHERE emp_id = fn_current_emp_id();

CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_my_payslips AS
SELECT * FROM v_salary_slip WHERE emp_id = fn_current_emp_id();

CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_my_leaves AS
SELECT * FROM v_leave_requests WHERE emp_id = fn_current_emp_id();

CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_my_leave_balance AS
SELECT * FROM v_leave_balance WHERE emp_id = fn_current_emp_id();

-- ---------------------------------------------------------------------
-- Self-service procedures (act only on the caller's own emp_id)
-- ---------------------------------------------------------------------
DELIMITER $$
DROP PROCEDURE IF EXISTS sp_my_check_in $$
CREATE PROCEDURE sp_my_check_in() SQL SECURITY DEFINER
BEGIN
    CALL sp_check_in(fn_current_emp_id());
END $$

DROP PROCEDURE IF EXISTS sp_my_check_out $$
CREATE PROCEDURE sp_my_check_out() SQL SECURITY DEFINER
BEGIN
    CALL sp_check_out(fn_current_emp_id());
END $$

DROP PROCEDURE IF EXISTS sp_my_apply_leave $$
CREATE PROCEDURE sp_my_apply_leave(IN p_code VARCHAR(5), IN p_from DATE, IN p_to DATE, IN p_reason VARCHAR(200))
SQL SECURITY DEFINER
BEGIN
    CALL sp_apply_leave(fn_current_emp_id(), p_code, p_from, p_to, p_reason);
END $$
DELIMITER ;

-- ---------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------
DROP ROLE IF EXISTS 'payroll_hr', 'payroll_employee', 'payroll_app_role';
CREATE ROLE 'payroll_hr', 'payroll_employee', 'payroll_app_role';

-- HR: read everything and run every procedure; write only to operational
-- tables (audit_log, policy and tax slabs stay read-only)
GRANT SELECT, EXECUTE ON payroll_db.* TO 'payroll_hr';
GRANT INSERT, UPDATE, DELETE ON payroll_db.employees        TO 'payroll_hr';
GRANT INSERT, UPDATE, DELETE ON payroll_db.salary_structure TO 'payroll_hr';
GRANT INSERT, UPDATE, DELETE ON payroll_db.attendance       TO 'payroll_hr';
GRANT INSERT, UPDATE, DELETE ON payroll_db.leave_requests   TO 'payroll_hr';
GRANT INSERT, UPDATE, DELETE ON payroll_db.holidays         TO 'payroll_hr';
GRANT INSERT, UPDATE, DELETE ON payroll_db.payroll          TO 'payroll_hr';
GRANT INSERT, UPDATE         ON payroll_db.app_users        TO 'payroll_hr';

-- Employee: only their own data, through the self-service objects
GRANT SELECT  ON payroll_db.v_my_profile       TO 'payroll_employee';
GRANT SELECT  ON payroll_db.v_my_attendance    TO 'payroll_employee';
GRANT SELECT  ON payroll_db.v_my_payslips      TO 'payroll_employee';
GRANT SELECT  ON payroll_db.v_my_leaves        TO 'payroll_employee';
GRANT SELECT  ON payroll_db.v_my_leave_balance TO 'payroll_employee';
GRANT EXECUTE ON PROCEDURE payroll_db.sp_my_check_in    TO 'payroll_employee';
GRANT EXECUTE ON PROCEDURE payroll_db.sp_my_check_out   TO 'payroll_employee';
GRANT EXECUTE ON PROCEDURE payroll_db.sp_my_apply_leave TO 'payroll_employee';
-- read-only helper functions used inside the views above
-- (MySQL checks EXECUTE on functions referenced by a view against the caller)
GRANT EXECUTE ON FUNCTION payroll_db.fn_current_emp_id TO 'payroll_employee';
GRANT EXECUTE ON FUNCTION payroll_db.fn_policy_id      TO 'payroll_employee';
GRANT EXECUTE ON FUNCTION payroll_db.fn_is_working_day TO 'payroll_employee';
GRANT EXECUTE ON FUNCTION payroll_db.fn_ot_minutes     TO 'payroll_employee';
GRANT EXECUTE ON FUNCTION payroll_db.fn_salary_id      TO 'payroll_employee';

-- The Python app's service account: read everything, change data only via procedures
GRANT SELECT, EXECUTE ON payroll_db.* TO 'payroll_app_role';

-- ---------------------------------------------------------------------
-- Demo MySQL accounts (passwords are for local demo only)
-- ---------------------------------------------------------------------
DROP USER IF EXISTS 'payroll_app'@'localhost', 'neha'@'localhost', 'rahul'@'localhost';

CREATE USER 'payroll_app'@'localhost' IDENTIFIED BY 'App@2026';
CREATE USER 'neha'@'localhost'        IDENTIFIED BY 'hr@1234';
CREATE USER 'rahul'@'localhost'       IDENTIFIED BY 'emp@1234';

GRANT 'payroll_app_role' TO 'payroll_app'@'localhost';
GRANT 'payroll_hr'       TO 'neha'@'localhost';
GRANT 'payroll_employee' TO 'rahul'@'localhost';

SET DEFAULT ROLE ALL TO 'payroll_app'@'localhost', 'neha'@'localhost', 'rahul'@'localhost';

-- Try it:
--   mysql -u rahul -p'emp@1234' payroll_db -e "SELECT month_label, net_salary FROM v_my_payslips;"
--   mysql -u rahul -p'emp@1234' payroll_db -e "SELECT * FROM payroll;"   -- ERROR 1142: denied
