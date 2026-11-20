-- =====================================================================
--  File 05: Triggers (integrity rules + audit trail)
-- =====================================================================
USE payroll_db;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Attendance: only active employees, not before joining, not in future,
-- and never inside a month whose payroll is already PAID
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_attendance_before_insert $$
CREATE TRIGGER trg_attendance_before_insert
BEFORE INSERT ON attendance
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(10);
    DECLARE v_hire DATE;

    SELECT status, hire_date INTO v_status, v_hire FROM employees WHERE emp_id = NEW.emp_id;

    IF v_status <> 'ACTIVE' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Attendance can only be recorded for active employees';
    END IF;
    IF NEW.att_date < v_hire THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Attendance date is before the joining date';
    END IF;
    IF NEW.att_date > CURDATE() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Attendance cannot be recorded for a future date';
    END IF;
    IF EXISTS (SELECT 1 FROM payroll
               WHERE emp_id = NEW.emp_id AND status = 'PAID'
                 AND pay_month = DATE_FORMAT(NEW.att_date, '%Y-%m-01')) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'That month is already paid; attendance is locked';
    END IF;
END $$

DROP TRIGGER IF EXISTS trg_attendance_before_update $$
CREATE TRIGGER trg_attendance_before_update
BEFORE UPDATE ON attendance
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM payroll
               WHERE emp_id = OLD.emp_id AND status = 'PAID'
                 AND pay_month = DATE_FORMAT(OLD.att_date, '%Y-%m-01')) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'That month is already paid; attendance is locked';
    END IF;
END $$

-- ---------------------------------------------------------------------
-- Leave: no overlapping requests (pending or approved) for the same employee
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_leave_before_insert $$
CREATE TRIGGER trg_leave_before_insert
BEFORE INSERT ON leave_requests
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM leave_requests
               WHERE emp_id = NEW.emp_id
                 AND status IN ('PENDING', 'APPROVED')
                 AND NEW.from_date <= to_date
                 AND NEW.to_date   >= from_date) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Leave overlaps an existing pending or approved request';
    END IF;
END $$

-- Audit every leave decision
DROP TRIGGER IF EXISTS trg_leave_after_update $$
CREATE TRIGGER trg_leave_after_update
AFTER UPDATE ON leave_requests
FOR EACH ROW
BEGIN
    IF NEW.status <> OLD.status THEN
        INSERT INTO audit_log (table_name, record_id, action, details, changed_by)
        VALUES ('leave_requests', NEW.leave_id, NEW.status,
                CONCAT('emp ', NEW.emp_id, ': ', NEW.from_date, ' to ', NEW.to_date,
                       ' reviewed by emp ', COALESCE(NEW.reviewed_by, '-')),
                COALESCE(@app_user, USER()));
    END IF;
END $$

-- ---------------------------------------------------------------------
-- Salary: audit every new revision and every change
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_salary_after_insert $$
CREATE TRIGGER trg_salary_after_insert
AFTER INSERT ON salary_structure
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, record_id, action, details, changed_by)
    VALUES ('salary_structure', NEW.salary_id, 'INSERT',
            CONCAT('emp ', NEW.emp_id, ': basic ', NEW.basic, ', hra ', NEW.hra,
                   ', special ', NEW.special_allowance, ' from ', NEW.effective_from),
                COALESCE(@app_user, USER()));
END $$

DROP TRIGGER IF EXISTS trg_salary_after_update $$
CREATE TRIGGER trg_salary_after_update
AFTER UPDATE ON salary_structure
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, record_id, action, details, changed_by)
    VALUES ('salary_structure', NEW.salary_id, 'UPDATE',
            CONCAT('emp ', NEW.emp_id, ': basic ', OLD.basic, ' -> ', NEW.basic,
                   ', hra ', OLD.hra, ' -> ', NEW.hra,
                   ', special ', OLD.special_allowance, ' -> ', NEW.special_allowance),
                COALESCE(@app_user, USER()));
END $$

-- ---------------------------------------------------------------------
-- Payroll: a PAID row can never be changed or deleted
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_payroll_before_update $$
CREATE TRIGGER trg_payroll_before_update
BEFORE UPDATE ON payroll
FOR EACH ROW
BEGIN
    IF OLD.status = 'PAID' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Paid payroll records are locked';
    END IF;
END $$

DROP TRIGGER IF EXISTS trg_payroll_before_delete $$
CREATE TRIGGER trg_payroll_before_delete
BEFORE DELETE ON payroll
FOR EACH ROW
BEGIN
    IF OLD.status = 'PAID' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Paid payroll records are locked';
    END IF;
END $$

DROP TRIGGER IF EXISTS trg_payroll_after_update $$
CREATE TRIGGER trg_payroll_after_update
AFTER UPDATE ON payroll
FOR EACH ROW
BEGIN
    IF NEW.status = 'PAID' AND OLD.status <> 'PAID' THEN
        INSERT INTO audit_log (table_name, record_id, action, details, changed_by)
        VALUES ('payroll', NEW.payroll_id, 'PAID',
                CONCAT('emp ', NEW.emp_id, ' month ', DATE_FORMAT(NEW.pay_month, '%Y-%m'),
                       ' net ', NEW.net_salary),
                COALESCE(@app_user, USER()));
    END IF;
END $$

DELIMITER ;
