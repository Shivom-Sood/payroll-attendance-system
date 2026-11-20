-- =====================================================================
--  Overtime-Based Payroll and Attendance Management System
--  File 01: Schema (DDL)
--  Target: MySQL 8.0+ (tested on 8.0, compatible with 9.x)
-- =====================================================================

DROP DATABASE IF EXISTS payroll_db;
CREATE DATABASE payroll_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE payroll_db;

-- ---------------------------------------------------------------------
-- 1. DEPARTMENTS
-- ---------------------------------------------------------------------
CREATE TABLE departments (
    dept_id     INT AUTO_INCREMENT PRIMARY KEY,
    dept_name   VARCHAR(60)  NOT NULL UNIQUE,
    location    VARCHAR(60)  NOT NULL DEFAULT 'Gurugram'
);

-- ---------------------------------------------------------------------
-- 2. EMPLOYEES  (self-referencing FK: manager_id -> emp_id)
-- ---------------------------------------------------------------------
CREATE TABLE employees (
    emp_id       INT AUTO_INCREMENT PRIMARY KEY,
    first_name   VARCHAR(40)  NOT NULL,
    last_name    VARCHAR(40)  NOT NULL,
    email        VARCHAR(100) NOT NULL UNIQUE,
    phone        VARCHAR(15),
    gender       ENUM('M','F','O') NOT NULL,
    hire_date    DATE         NOT NULL,
    dept_id      INT          NOT NULL,
    designation  VARCHAR(60)  NOT NULL,
    manager_id   INT          NULL,
    status       ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
    CONSTRAINT fk_emp_dept    FOREIGN KEY (dept_id)    REFERENCES departments(dept_id),
    CONSTRAINT fk_emp_manager FOREIGN KEY (manager_id) REFERENCES employees(emp_id)
        ON DELETE SET NULL
) AUTO_INCREMENT = 1001;

-- ---------------------------------------------------------------------
-- 3. SALARY STRUCTURE  (history: one row per revision)
--    The row with the latest effective_from <= a date is the one in force.
-- ---------------------------------------------------------------------
CREATE TABLE salary_structure (
    salary_id          INT AUTO_INCREMENT PRIMARY KEY,
    emp_id             INT           NOT NULL,
    basic              DECIMAL(10,2) NOT NULL,
    hra                DECIMAL(10,2) NOT NULL DEFAULT 0,
    special_allowance  DECIMAL(10,2) NOT NULL DEFAULT 0,
    effective_from     DATE          NOT NULL,
    CONSTRAINT fk_sal_emp FOREIGN KEY (emp_id) REFERENCES employees(emp_id) ON DELETE CASCADE,
    CONSTRAINT uq_sal_emp_date UNIQUE (emp_id, effective_from),
    CONSTRAINT chk_sal_positive CHECK (basic > 0 AND hra >= 0 AND special_allowance >= 0)
);

-- ---------------------------------------------------------------------
-- 4. PAYROLL POLICY  (organisational rules, versioned by effective date)
-- ---------------------------------------------------------------------
CREATE TABLE payroll_policy (
    policy_id               INT AUTO_INCREMENT PRIMARY KEY,
    effective_from          DATE         NOT NULL UNIQUE,
    shift_start             TIME         NOT NULL DEFAULT '09:30:00',
    grace_minutes           INT          NOT NULL DEFAULT 15,   -- late if check-in after shift_start + grace
    std_work_minutes        INT          NOT NULL DEFAULT 540,  -- 9 h shift (incl. 1 h break)
    full_day_min_minutes    INT          NOT NULL DEFAULT 480,  -- >= 8 h  -> full day
    half_day_min_minutes    INT          NOT NULL DEFAULT 240,  -- >= 4 h  -> half day
    min_ot_minutes          INT          NOT NULL DEFAULT 30,   -- extra time below this is ignored
    max_ot_minutes_per_day  INT          NOT NULL DEFAULT 240,  -- OT cap per weekday
    ot_rate_weekday         DECIMAL(3,2) NOT NULL DEFAULT 1.50,
    ot_rate_holiday         DECIMAL(3,2) NOT NULL DEFAULT 2.00, -- weekends & holidays
    late_marks_per_half_day INT          NOT NULL DEFAULT 3,    -- every 3 late marks = 0.5 day deduction
    pf_rate                 DECIMAL(4,3) NOT NULL DEFAULT 0.120,-- employee PF on earned basic
    standard_deduction      DECIMAL(10,2) NOT NULL DEFAULT 75000,
    tax_rebate_limit        DECIMAL(12,2) NOT NULL DEFAULT 1200000, -- no tax if taxable <= this (Sec 87A)
    cess_rate               DECIMAL(4,3) NOT NULL DEFAULT 0.040
);

-- ---------------------------------------------------------------------
-- 5. TAX SLABS  (simplified new-regime slabs, annual taxable income)
-- ---------------------------------------------------------------------
CREATE TABLE tax_slabs (
    slab_id      INT AUTO_INCREMENT PRIMARY KEY,
    lower_limit  DECIMAL(12,2) NOT NULL,
    upper_limit  DECIMAL(12,2) NULL,          -- NULL = no upper limit
    rate         DECIMAL(4,3)  NOT NULL,
    CONSTRAINT chk_slab_range CHECK (upper_limit IS NULL OR upper_limit > lower_limit)
);

-- ---------------------------------------------------------------------
-- 6. HOLIDAYS and CALENDAR
-- ---------------------------------------------------------------------
CREATE TABLE holidays (
    holiday_date  DATE        PRIMARY KEY,
    holiday_name  VARCHAR(60) NOT NULL
);

-- One row per date; filled by sp_fill_calendar (recursive CTE).
-- Lets every report treat "working day" consistently.
CREATE TABLE calendar (
    cal_date    DATE    PRIMARY KEY,
    is_weekend  BOOLEAN NOT NULL
);

-- ---------------------------------------------------------------------
-- 7. ATTENDANCE  (one row per employee per day)
--    worked_minutes is a STORED generated column, always consistent.
-- ---------------------------------------------------------------------
CREATE TABLE attendance (
    attendance_id   INT AUTO_INCREMENT PRIMARY KEY,
    emp_id          INT      NOT NULL,
    att_date        DATE     NOT NULL,
    check_in        DATETIME NOT NULL,
    check_out       DATETIME NULL,
    worked_minutes  INT GENERATED ALWAYS AS (TIMESTAMPDIFF(MINUTE, check_in, check_out)) STORED,
    CONSTRAINT fk_att_emp FOREIGN KEY (emp_id) REFERENCES employees(emp_id) ON DELETE CASCADE,
    CONSTRAINT uq_att_emp_date UNIQUE (emp_id, att_date),
    CONSTRAINT chk_att_checkin_date CHECK (DATE(check_in) = att_date),
    CONSTRAINT chk_att_order CHECK (check_out IS NULL OR check_out > check_in)
);

-- ---------------------------------------------------------------------
-- 8. LEAVE TYPES and LEAVE REQUESTS
-- ---------------------------------------------------------------------
CREATE TABLE leave_types (
    leave_type_id  INT AUTO_INCREMENT PRIMARY KEY,
    code           VARCHAR(5)  NOT NULL UNIQUE,
    leave_name     VARCHAR(40) NOT NULL,
    is_paid        BOOLEAN     NOT NULL,
    annual_quota   INT         NULL      -- NULL = no limit (e.g. leave without pay)
);

CREATE TABLE leave_requests (
    leave_id       INT AUTO_INCREMENT PRIMARY KEY,
    emp_id         INT          NOT NULL,
    leave_type_id  INT          NOT NULL,
    from_date      DATE         NOT NULL,
    to_date        DATE         NOT NULL,
    reason         VARCHAR(200),
    status         ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
    applied_on     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by    INT          NULL,
    reviewed_on    DATETIME     NULL,
    CONSTRAINT fk_lv_emp      FOREIGN KEY (emp_id)        REFERENCES employees(emp_id) ON DELETE CASCADE,
    CONSTRAINT fk_lv_type     FOREIGN KEY (leave_type_id) REFERENCES leave_types(leave_type_id),
    CONSTRAINT fk_lv_reviewer FOREIGN KEY (reviewed_by)   REFERENCES employees(emp_id) ON DELETE SET NULL,
    CONSTRAINT chk_lv_dates CHECK (to_date >= from_date)
);

-- ---------------------------------------------------------------------
-- 9. PAYROLL  (one processed row per employee per month)
-- ---------------------------------------------------------------------
CREATE TABLE payroll (
    payroll_id         INT AUTO_INCREMENT PRIMARY KEY,
    emp_id             INT           NOT NULL,
    pay_month          DATE          NOT NULL,      -- always the 1st of the month
    working_days       INT           NOT NULL,
    present_days       DECIMAL(4,1)  NOT NULL,      -- half days count 0.5
    paid_leave_days    DECIMAL(4,1)  NOT NULL,
    unpaid_leave_days  DECIMAL(4,1)  NOT NULL,
    absent_days        DECIMAL(4,1)  NOT NULL,
    lop_days           DECIMAL(4,1)  NOT NULL,      -- loss-of-pay days
    late_marks         INT           NOT NULL,
    regular_hours      DECIMAL(6,2)  NOT NULL,
    ot_hours_weekday   DECIMAL(6,2)  NOT NULL,
    ot_hours_holiday   DECIMAL(6,2)  NOT NULL,
    basic              DECIMAL(10,2) NOT NULL,
    hra                DECIMAL(10,2) NOT NULL,
    special_allowance  DECIMAL(10,2) NOT NULL,
    ot_pay             DECIMAL(10,2) NOT NULL,
    gross_earnings     DECIMAL(10,2) NOT NULL,
    lop_deduction      DECIMAL(10,2) NOT NULL,
    late_deduction     DECIMAL(10,2) NOT NULL,
    pf                 DECIMAL(10,2) NOT NULL,
    tds                DECIMAL(10,2) NOT NULL,
    total_deductions   DECIMAL(10,2) NOT NULL,
    net_salary         DECIMAL(10,2) NOT NULL,
    status             ENUM('PROCESSED','PAID') NOT NULL DEFAULT 'PROCESSED',
    processed_on       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pay_emp FOREIGN KEY (emp_id) REFERENCES employees(emp_id),
    CONSTRAINT uq_pay_emp_month UNIQUE (emp_id, pay_month),
    CONSTRAINT chk_pay_first_day CHECK (DAY(pay_month) = 1),
    CONSTRAINT chk_pay_net CHECK (net_salary >= 0)
);

-- ---------------------------------------------------------------------
-- 10. APP USERS  (login for the Python app; passwords salted + SHA-256)
-- ---------------------------------------------------------------------
CREATE TABLE app_users (
    user_id        INT AUTO_INCREMENT PRIMARY KEY,
    emp_id         INT         NOT NULL UNIQUE,
    username       VARCHAR(30) NOT NULL UNIQUE,
    password_hash  CHAR(64)    NOT NULL,
    salt           CHAR(32)    NOT NULL,
    role           ENUM('HR_ADMIN','EMPLOYEE') NOT NULL DEFAULT 'EMPLOYEE',
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_user_emp FOREIGN KEY (emp_id) REFERENCES employees(emp_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- 11. AUDIT LOG  (written by triggers)
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    table_name  VARCHAR(40)  NOT NULL,
    record_id   INT          NOT NULL,
    action      VARCHAR(20)  NOT NULL,
    details     VARCHAR(255),
    changed_by  VARCHAR(100) NOT NULL DEFAULT (CURRENT_USER()),
    changed_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- INDEXES for frequent lookups (reports filter by employee + date range)
-- ---------------------------------------------------------------------
CREATE INDEX idx_att_date       ON attendance (att_date);
CREATE INDEX idx_lv_emp_dates   ON leave_requests (emp_id, from_date, to_date);
CREATE INDEX idx_pay_month      ON payroll (pay_month);
CREATE INDEX idx_emp_dept       ON employees (dept_id);
