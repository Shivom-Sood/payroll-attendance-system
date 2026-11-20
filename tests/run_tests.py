"""
Phase 4 test suite: valid, invalid and boundary test cases.

What it does
  1. Rebuilds payroll_db from the SQL files (clean, known state)
  2. Runs every test case below against the real database
  3. Writes the documented results to tests/test_results.md
  4. Rebuilds payroll_db again so the demo data is left untouched

Run:   python3 tests/run_tests.py
       (asks for the MySQL root password; or set MYSQL_PWD)
Needs: the mysql command-line client on PATH, mysql-connector-python
"""
import getpass
import hashlib
import os
import subprocess
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import mysql.connector
from mysql.connector import Error as DBError

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = ["01_schema", "02_functions", "03_views", "04_procedures",
             "05_triggers", "06_seed_data", "07_security"]
HOST = os.getenv("PAYROLL_DB_HOST", "127.0.0.1")

results = []          # (id, category, description, expected, actual, passed)


# ----------------------------------------------------------------------
def rebuild(root_pw):
    env = dict(os.environ, MYSQL_PWD=root_pw)
    for f in SQL_FILES:
        with open(ROOT / "sql" / f"{f}.sql") as fh:
            r = subprocess.run(["mysql", "-u", "root", "-h", HOST], stdin=fh, env=env,
                               capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"Rebuild failed in {f}.sql:\n{r.stderr}")


def connect(user, password):
    return mysql.connector.connect(host=HOST, user=user, password=password,
                                   database="payroll_db", autocommit=True)


def run(conn, sql, params=()):
    """Execute SQL (or CALL); return all rows of the first result set."""
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall() if cur.with_rows else []
    while cur.nextset():
        if cur.with_rows:
            cur.fetchall()
    cur.close()
    return rows


def scalar(conn, sql, params=()):
    rows = run(conn, sql, params)
    return rows[0][0] if rows else None


def record(tid, cat, desc, expected, actual, passed):
    results.append((tid, cat, desc, expected, str(actual), passed))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {tid:<4} {desc}")


def expect_error(tid, cat, desc, conn, sql, params, must_contain):
    """Test passes if the statement is REJECTED with a message containing must_contain."""
    try:
        run(conn, sql, params)
        record(tid, cat, desc, f"Rejected: {must_contain}", "Statement succeeded (not rejected)", False)
    except DBError as e:
        msg = e.msg
        record(tid, cat, desc, f"Rejected: {must_contain}", f"Rejected: {msg}", must_contain.lower() in msg.lower())


def expect_value(tid, cat, desc, conn, sql, params, expected):
    try:
        actual = scalar(conn, sql, params)
        if isinstance(actual, Decimal):
            actual = float(actual)
        record(tid, cat, desc, str(expected), actual, actual == expected)
    except DBError as e:
        record(tid, cat, desc, str(expected), f"Error: {e.msg}", False)


def expect_ok(tid, cat, desc, conn, sql, params=(), check_sql=None, check_expected=None):
    try:
        run(conn, sql, params)
        if check_sql:
            actual = scalar(conn, check_sql)
            if isinstance(actual, Decimal):
                actual = float(actual)
            record(tid, cat, desc, f"Succeeds; {check_expected}", f"Succeeded; {actual}", actual == check_expected)
        else:
            record(tid, cat, desc, "Succeeds", "Succeeded", True)
    except DBError as e:
        record(tid, cat, desc, "Succeeds", f"Error: {e.msg}", False)


# ----------------------------------------------------------------------
def tests(root_pw):
    db = connect("root", root_pw)
    app = connect("payroll_app", "App@2026")
    rahul = connect("rahul", "emp@1234")
    today = date.today()

    # ================= VALID CASES =================
    print("\nVALID")
    cat = "Valid"
    expect_ok("V01", cat, "HR adds a new employee (employee + salary + login in one transaction)", app,
              "CALL sp_add_employee('Test','Employee','test.employee@techsphere.in','9999999999','M',"
              "'2026-11-02',1,'QA Intern',1006,30000,12000,6000,'tester','test@123','EMPLOYEE',@new)",
              check_sql="SELECT COUNT(*) FROM employees e JOIN salary_structure s USING (emp_id) "
                        "JOIN app_users u USING (emp_id) WHERE e.email='test.employee@techsphere.in'",
              check_expected=1)
    tid = scalar(db, "SELECT emp_id FROM employees WHERE email='test.employee@techsphere.in'")

    salt, phash = run(db, "SELECT salt, password_hash FROM app_users WHERE username='tester'")[0]
    ok = hashlib.sha256((salt + "test@123").encode()).hexdigest() == phash
    record("V02", cat, "Login with the correct password (salted SHA-256 matches)", "Hash matches",
           "Hash matches" if ok else "Mismatch", ok)

    expect_ok("V03", cat, "Employee checks in today", app, "CALL sp_check_in(%s)", (tid,),
              check_sql=f"SELECT COUNT(*) FROM attendance WHERE emp_id={tid} AND att_date=CURDATE()",
              check_expected=1)
    time.sleep(1.2)
    expect_ok("V04", cat, "Employee checks out after checking in", app, "CALL sp_check_out(%s)", (tid,),
              check_sql=f"SELECT check_out IS NOT NULL FROM attendance WHERE emp_id={tid} AND att_date=CURDATE()",
              check_expected=1)

    expect_ok("V05", cat, "HR revises salary (new history row, audit row written)", app,
              "CALL sp_update_salary(%s, 32000, 12800, 6400, '2026-12-01')", (tid,),
              check_sql=f"SELECT COUNT(*) FROM audit_log WHERE table_name='salary_structure' AND details LIKE 'emp {tid}:%'",
              check_expected=2)

    expect_ok("V06", cat, "Employee applies for 2 days of casual leave", app,
              "CALL sp_apply_leave(%s,'CL','2026-12-28','2026-12-29','Year-end')", (tid,),
              check_sql=f"SELECT status FROM leave_requests WHERE emp_id={tid} AND leave_type_id=1",
              check_expected="PENDING")
    lid = scalar(db, f"SELECT leave_id FROM leave_requests WHERE emp_id={tid} AND from_date='2026-12-28'")
    expect_ok("V07", cat, "HR approves the leave (audit row written)", app,
              "CALL sp_review_leave(%s, 1001, 'APPROVED')", (lid,),
              check_sql=f"SELECT COUNT(*) FROM audit_log WHERE table_name='leave_requests' AND record_id={lid}",
              check_expected=1)

    expect_ok("V08", cat, "Re-run October payroll (transaction replaces PROCESSED rows)", app,
              "CALL sp_generate_payroll(2026, 10)",
              check_sql="SELECT COUNT(*) FROM payroll WHERE pay_month='2026-10-01'", check_expected=12)
    expect_ok("V09", cat, "Mark October payroll as PAID (all rows in one transaction)", app,
              "CALL sp_mark_payroll_paid(2026, 10)",
              check_sql="SELECT COUNT(*) FROM payroll WHERE pay_month='2026-10-01' AND status='PAID'",
              check_expected=12)
    expect_value("V10", cat, "Reports return data: monthly attendance rows for Oct 2026", app,
                 "SELECT COUNT(*) FROM v_monthly_attendance WHERE pay_month='2026-10-01'", (), 12)

    # ================= INVALID CASES =================
    print("\nINVALID")
    cat = "Invalid"
    expect_error("I01", cat, "Negative basic salary via procedure", app,
                 "CALL sp_update_salary(1004, -5000, 1000, 1000, '2026-12-01')", (), "Basic must be positive")
    expect_error("I02", cat, "Negative salary inserted directly into the table (CHECK constraint)", db,
                 "INSERT INTO salary_structure (emp_id, basic, hra, special_allowance, effective_from) "
                 "VALUES (1004, -100, 0, 0, '2027-01-01')", (), "chk_sal_positive")
    expect_error("I03", cat, "Duplicate attendance entry (same employee, same date)", db,
                 "INSERT INTO attendance (emp_id, att_date, check_in) VALUES (1003, '2026-11-02', '2026-11-02 09:30:00')",
                 (), "Duplicate entry")
    expect_error("I04", cat, "Checking in twice on the same day", app, "CALL sp_check_in(%s)", (tid,),
                 "Already checked in today")
    expect_error("I05", cat, "Check-out time earlier than check-in", db,
                 "INSERT INTO attendance (emp_id, att_date, check_in, check_out) "
                 "VALUES (%s, '2026-11-05', '2026-11-05 18:00:00', '2026-11-05 09:00:00')", (tid,), "chk_att_order")
    expect_error("I06", cat, "Attendance for a future date", db,
                 "INSERT INTO attendance (emp_id, att_date, check_in) VALUES (1004, CURDATE() + INTERVAL 3 DAY, "
                 "TIMESTAMP(CURDATE() + INTERVAL 3 DAY, '09:30:00'))", (), "future date")
    expect_error("I07", cat, "Attendance before the joining date", db,
                 "INSERT INTO attendance (emp_id, att_date, check_in) VALUES (%s, '2026-10-30', '2026-10-30 09:30:00')",
                 (tid,), "before the joining date")
    expect_error("I08", cat, "Leave overlapping an approved leave (trigger)", app,
                 "CALL sp_apply_leave(%s,'SL','2026-12-29','2026-12-30','overlap')", (tid,), "overlaps")
    expect_error("I09", cat, "Leave longer than the remaining balance", app,
                 "CALL sp_apply_leave(1004,'SL','2026-12-01','2026-12-31','too long')", (), "Insufficient leave balance")
    expect_error("I10", cat, "Leave on dates with no working days (weekend)", app,
                 "CALL sp_apply_leave(1004,'CL','2026-12-05','2026-12-06','weekend')", (), "no working days")
    expect_error("I11", cat, "Non-HR employee tries to approve a leave", app,
                 "CALL sp_review_leave(10, 1004, 'APPROVED')", (), "Only HR admins")
    run(db, "INSERT INTO leave_requests (emp_id, leave_type_id, from_date, to_date, reason) "
            "VALUES (1001, 1, '2026-12-14', '2026-12-14', 'own leave test')")
    own = scalar(db, "SELECT MAX(leave_id) FROM leave_requests WHERE emp_id=1001")
    expect_error("I12", cat, "HR admin tries to approve their own leave", app,
                 "CALL sp_review_leave(%s, 1001, 'APPROVED')", (own,), "cannot review your own")
    before = scalar(db, "SELECT COUNT(*) FROM salary_structure")
    expect_error("I13", cat, "Add employee with a duplicate email", app,
                 "CALL sp_add_employee('Dup','User','neha.kapoor@techsphere.in','1','F','2026-11-02',1,'Dev',NULL,"
                 "30000,0,0,'dupuser','dup@123','EMPLOYEE',@x)", (), "Duplicate entry")
    after = scalar(db, "SELECT COUNT(*) FROM salary_structure")
    record("I14", cat, "...and the failed add leaves no partial rows (ROLLBACK)", "Salary rows unchanged",
           f"before={before}, after={after}", before == after)
    expect_error("I15", cat, "Modify a PAID payroll record", db,
                 "UPDATE payroll SET net_salary = 1 WHERE pay_month='2026-09-01' AND emp_id=1004", (), "locked")
    expect_error("I16", cat, "Delete a PAID payroll month", db,
                 "DELETE FROM payroll WHERE pay_month='2026-08-01'", (), "locked")
    expect_error("I17", cat, "Change attendance inside a PAID month", db,
                 "CALL sp_upsert_attendance(1004,'2026-09-10','2026-09-10 09:00:00','2026-09-10 18:00:00')", (),
                 "attendance is locked")
    expect_error("I18", cat, "Generate payroll for a month that has not ended", app,
                 "CALL sp_generate_payroll(%s, %s)", (today.year, today.month), "after the month has ended")
    expect_error("I19", cat, "Regenerate an already PAID month", app,
                 "CALL sp_generate_payroll(2026, 9)", (), "already PAID")
    expect_error("I20", cat, "Back-date a salary revision into a paid month", app,
                 "CALL sp_update_salary(1004, 50000, 20000, 10000, '2026-09-01')", (), "already paid month")
    expect_error("I21", cat, "Unauthorized: employee 'rahul' reads the payroll table", rahul,
                 "SELECT * FROM payroll", (), "SELECT command denied")
    expect_error("I22", cat, "Unauthorized: employee 'rahul' runs the payroll procedure", rahul,
                 "CALL sp_generate_payroll(2026, 10)", (), "execute command denied")
    expect_error("I23", cat, "Unauthorized: app account edits a table directly (bypassing procedures)", app,
                 "UPDATE employees SET status='INACTIVE' WHERE emp_id=1004", (), "UPDATE command denied")
    expect_error("I24", cat, "Unauthorized: HR tries to erase the audit log", connect("neha", "hr@1234"),
                 "DELETE FROM audit_log", (), "DELETE command denied")
    expect_value("I25", cat, "Employee self-service view shows only their own slips", rahul,
                 "SELECT COUNT(DISTINCT emp_id) FROM v_my_payslips", (), 1)
    salt, phash = run(db, "SELECT salt, password_hash FROM app_users WHERE username='rahul'")[0]
    bad = hashlib.sha256((salt + "wrongpass").encode()).hexdigest() != phash
    record("I26", cat, "Login with a wrong password is refused", "Hash mismatch",
           "Hash mismatch" if bad else "Matched", bad)
    expect_value("I27", cat, "SQL-injection username (' OR '1'='1) finds no user (parameterised query)", app,
                 "SELECT COUNT(*) FROM app_users WHERE username = %s", ("' OR '1'='1",), 0)

    # ================= BOUNDARY CASES =================
    print("\nBOUNDARY")
    cat = "Boundary"
    # attendance rows for the test employee on past working days, then read the classification
    for d, cin, mins in [("2026-11-03", "09:30:00", 480), ("2026-11-04", "09:30:00", 479),
                         ("2026-11-05", "09:30:00", 240), ("2026-11-06", "09:30:00", 239),
                         ("2026-11-10", "09:45:00", 540), ("2026-11-11", "09:45:01", 540)]:
        run(db, "CALL sp_upsert_attendance(%s, %s, %s, TIMESTAMP(%s, %s) + INTERVAL %s MINUTE)",
            (tid, d, f"{d} {cin}", d, cin, mins))
    status = "SELECT day_status FROM v_daily_attendance WHERE emp_id=%s AND cal_date=%s"
    late = "SELECT is_late FROM v_daily_attendance WHERE emp_id=%s AND cal_date=%s"
    expect_value("B01", cat, "Worked exactly 8h00m (480 min) -> full day", db, status, (tid, "2026-11-03"), "PRESENT")
    expect_value("B02", cat, "Worked 7h59m (479 min) -> half day", db, status, (tid, "2026-11-04"), "HALF_DAY")
    expect_value("B03", cat, "Worked exactly 4h00m (240 min) -> half day", db, status, (tid, "2026-11-05"), "HALF_DAY")
    expect_value("B04", cat, "Worked 3h59m (239 min) -> counted absent", db, status, (tid, "2026-11-06"), "ABSENT")
    expect_value("B05", cat, "Check-in at exactly 09:45:00 (end of grace) -> not late", db, late, (tid, "2026-11-10"), 0)
    expect_value("B06", cat, "Check-in at 09:45:01 -> late mark", db, late, (tid, "2026-11-11"), 1)
    ot = "SELECT fn_ot_minutes(%s, %s)"
    expect_value("B07", cat, "Weekday: 29 min beyond the 9h shift -> no overtime", db, ot, ("2026-11-03", 569), 0)
    expect_value("B08", cat, "Weekday: exactly 30 min beyond the shift -> 30 min OT", db, ot, ("2026-11-03", 570), 30)
    expect_value("B09", cat, "Weekday: 6h beyond the shift -> capped at 240 min", db, ot, ("2026-11-03", 900), 240)
    expect_value("B10", cat, "Weekend: 10h worked -> OT capped at one shift (540)", db, ot, ("2026-11-07", 600), 540)
    expect_value("B11", cat, "Holiday (Diwali 9 Nov): 5h worked -> all 300 min are OT", db, ot, ("2026-11-09", 300), 300)
    tax = "SELECT fn_annual_tax(%s, '2026-10-31')"
    expect_value("B12", cat, "Taxable income exactly Rs 12,00,000 -> zero tax (rebate)", db, tax, (1200000,), 0.0)
    expect_value("B13", cat, "Taxable Rs 12,10,000 -> marginal relief caps tax at Rs 10,000 + cess", db, tax,
                 (1210000,), 10400.0)
    expect_value("B14", cat, "Taxable Rs 16,00,000 -> slab tax Rs 1,20,000 + 4% cess", db, tax, (1600000,), 124800.0)
    expect_ok("B15", cat, "Leave request using exactly the remaining EL balance (15 days)", app,
              "CALL sp_apply_leave(%s,'EL','2026-12-01','2026-12-21','Long leave')", (tid,),
              check_sql=f"SELECT COUNT(*) FROM leave_requests WHERE emp_id={tid} AND leave_type_id=3",
              check_expected=1)
    expect_error("B16", cat, "One more EL day beyond the balance -> rejected", app,
                 "CALL sp_apply_leave(%s,'EL','2026-12-22','2026-12-22','one more')", (tid,), "Insufficient")
    expect_value("B17", cat, "Late-mark rule: every payroll row deducts 0.5 day per 3 late marks", db,
                 "SELECT COUNT(*) FROM payroll WHERE late_deduction <> "
                 "ROUND(FLOOR(late_marks / 3) * 0.5 * (basic + hra + special_allowance) / working_days, 2)", (), 0)
    expect_value("B18", cat, "Mid-month joiner (Isha, joined 12 Oct): 6 days loss of pay", db,
                 "SELECT lop_days FROM payroll WHERE emp_id=1012 AND pay_month='2026-10-01'", (), 6.0)
    expect_value("B19", cat, "Every payroll row: net = gross - total deductions, and net >= 0", db,
                 "SELECT COUNT(*) FROM payroll WHERE net_salary <> gross_earnings - total_deductions OR net_salary < 0",
                 (), 0)
    expect_error("B20", cat, "Leave from 31 Dec to 1 Jan (crosses a year end) -> must be split", app,
                 "CALL sp_apply_leave(1004,'CL','2026-12-31','2027-01-01','new year')", (), "crosses a year end")

    for c in (db, app, rahul):
        c.close()


# ----------------------------------------------------------------------
def write_report(started):
    passed = sum(r[5] for r in results)
    lines = [
        "# Test Results: Overtime-Based Payroll and Attendance Management System",
        "",
        f"Run on {started:%d %b %Y %H:%M} against a freshly rebuilt `payroll_db`. "
        f"**{passed} of {len(results)} test cases passed.**",
        "",
        "Each case states the expected behaviour and the actual response from MySQL. "
        "Invalid cases pass when the database *rejects* the operation with the expected message.",
        "",
    ]
    for cat in ("Valid", "Invalid", "Boundary"):
        rows = [r for r in results if r[1] == cat]
        lines += [f"## {cat} cases ({sum(r[5] for r in rows)}/{len(rows)} passed)", "",
                  "| ID | Test case | Expected | Actual result | Status |",
                  "|---|---|---|---|---|"]
        for tid, _, desc, exp, act, ok in rows:
            act = act.replace("|", "/")
            lines.append(f"| {tid} | {desc} | {exp} | {act} | {'PASS' if ok else 'FAIL'} |")
        lines.append("")
    out = ROOT / "tests" / "test_results.md"
    out.write_text("\n".join(lines))
    return passed, out


def main():
    root_pw = os.getenv("MYSQL_PWD")
    if root_pw is None:
        root_pw = getpass.getpass("MySQL root password (Enter if none): ")
    started = datetime.now()
    print("Rebuilding payroll_db (clean state)...")
    rebuild(root_pw)
    try:
        tests(root_pw)
    finally:
        print("\nRestoring demo data...")
        rebuild(root_pw)
    passed, out = write_report(started)
    print(f"\n{passed}/{len(results)} passed. Results written to {out}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
