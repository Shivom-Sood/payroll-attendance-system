"""
Overtime-Based Payroll and Attendance Management System
Command-line front end (role-based: HR Admin / Employee)

The app is deliberately thin: every rule (overtime, leave balance, payroll
maths, locking) lives in MySQL stored procedures, functions and triggers.
The app logs the user in, shows the menu for their role, and calls the
database. It connects with the limited 'payroll_app' account, which can
read data and EXECUTE procedures but cannot write to tables directly.

Run:  python3 app/payroll_app.py
Config (optional environment variables):
  PAYROLL_DB_HOST (127.0.0.1)  PAYROLL_DB_PORT (3306)
  PAYROLL_DB_USER (payroll_app) PAYROLL_DB_PASSWORD (App@2026)
  PAYROLL_DB_NAME (payroll_db)
"""
import getpass
import hashlib
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

try:
    import mysql.connector
    from mysql.connector import Error as DBError
except ImportError:
    sys.exit("Missing driver. Install it with:  pip3 install mysql-connector-python")

COMPANY = "TechSphere Solutions Pvt. Ltd., Gurugram"
SLIP_DIR = Path(__file__).resolve().parent.parent / "salary_slips"


# ======================================================================
# Database helpers
# ======================================================================
class DB:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=os.getenv("PAYROLL_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("PAYROLL_DB_PORT", "3306")),
            user=os.getenv("PAYROLL_DB_USER", "payroll_app"),
            password=os.getenv("PAYROLL_DB_PASSWORD", "App@2026"),
            database=os.getenv("PAYROLL_DB_NAME", "payroll_db"),
            autocommit=True,  # procedures manage their own transactions
        )

    def query(self, sql, params=()):
        """Run a SELECT; return (column_names, rows)."""
        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = cur.column_names
        cur.close()
        return cols, rows

    def query_one(self, sql, params=()):
        cols, rows = self.query(sql, params)
        return dict(zip(cols, rows[0])) if rows else None

    def call(self, proc, args=(), has_out=False):
        """Call a stored procedure.
        Returns (out_value, [(cols, rows), ...]) - one entry per result set.
        has_out=True means the procedure's last parameter is an OUT parameter."""
        cur = self.conn.cursor()
        results, out_value = [], None
        if hasattr(cur, "nextset"):                    # mysql-connector 9.2+
            params = ", ".join(["%s"] * len(args) + (["@out_param"] if has_out else []))
            cur.execute(f"CALL {proc}({params})", args)
            while True:
                if cur.with_rows:
                    results.append((cur.column_names, cur.fetchall()))
                if not cur.nextset():
                    break
            if has_out:
                cur.execute("SELECT @out_param")
                out_value = cur.fetchone()[0]
        else:                                          # older connector versions
            out_args = cur.callproc(proc, tuple(args) + ((0,) if has_out else ()))
            results = [(r.column_names, r.fetchall()) for r in cur.stored_results()]
            out_value = out_args[-1] if has_out else None
        cur.close()
        return out_value, results


# ======================================================================
# Display helpers
# ======================================================================
def money(v):
    """Indian-style grouping: 123456.5 -> 1,23,456.50"""
    v = Decimal(v or 0).quantize(Decimal("0.01"))
    sign = "-" if v < 0 else ""
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"


def cell(v):
    if v is None:
        return "-"
    if isinstance(v, Decimal):
        return money(v) if abs(v) >= 1000 else str(v)
    if isinstance(v, datetime):
        return v.strftime("%d-%b %H:%M")
    if isinstance(v, date):
        return v.strftime("%d-%b-%Y")
    return str(v)


def print_table(cols, rows, title=None):
    if title:
        print(f"\n  {title}")
    if not rows:
        print("  (no records)")
        return
    data = [[cell(v) for v in r] for r in rows]
    widths = [max(len(str(c)), *(len(r[i]) for r in data)) for i, c in enumerate(cols)]
    line = "  +" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(line)
    print("  | " + " | ".join(str(c).ljust(w) for c, w in zip(cols, widths)) + " |")
    print(line)
    for r in data:
        print("  | " + " | ".join(v.rjust(w) if _numeric(v) else v.ljust(w)
                                  for v, w in zip(r, widths)) + " |")
    print(line)
    print(f"  {len(rows)} row(s)")


def _numeric(s):
    return s.replace(",", "").replace(".", "", 1).replace("-", "", 1).isdigit()


def ask(prompt, default=None, required=True):
    suffix = f" [{default}]" if default is not None else ""
    while True:
        val = input(f"  {prompt}{suffix}: ").strip()
        if not val and default is not None:
            return str(default)
        if val or not required:
            return val
        print("  This field is required.")


def ask_int(prompt, default=None):
    while True:
        val = ask(prompt, default)
        if val.isdigit():
            return int(val)
        print("  Please enter a number.")


def ask_date(prompt, default=None):
    while True:
        val = ask(prompt + " (YYYY-MM-DD)", default)
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            print("  Invalid date.")


def ask_month(prompt="Month", default=None):
    if default is None:
        today = date.today()
        prev = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
        default = prev.strftime("%Y-%m")
    while True:
        val = ask(prompt + " (YYYY-MM)", default)
        try:
            d = datetime.strptime(val, "%Y-%m").date()
            return d.year, d.month
        except ValueError:
            print("  Invalid month.")


def pause():
    input("\n  Press Enter to continue...")


def header(text):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def run_safely(fn, *args):
    """Run a menu action and show database errors (SIGNAL messages) nicely."""
    try:
        fn(*args)
    except DBError as e:
        print(f"\n  [!] {e.msg}")
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
    pause()


# ======================================================================
# Login
# ======================================================================
def hash_password(salt, password):
    return hashlib.sha256((salt + password).encode()).hexdigest()


def login(db):
    header("Payroll & Attendance System - Login")
    for attempt in range(3):
        username = ask("Username")
        password = getpass.getpass("  Password: ")
        user = db.query_one(
            "SELECT u.user_id, u.emp_id, u.username, u.password_hash, u.salt, u.role, "
            "       CONCAT(e.first_name, ' ', e.last_name) AS name "
            "FROM app_users u JOIN employees e ON e.emp_id = u.emp_id "
            "WHERE u.username = %s AND u.is_active AND e.status = 'ACTIVE'",
            (username,))
        if user and hash_password(user["salt"], password) == user["password_hash"]:
            # triggers write this name into audit_log.changed_by
            db.query("SELECT @app_user := %s", (f"app:{user['username']}",))
            print(f"\n  Welcome, {user['name']} ({user['role'].replace('_', ' ')})")
            return user
        print(f"  Invalid username or password ({2 - attempt} attempt(s) left)")
    return None


# ======================================================================
# Salary slip
# ======================================================================
def render_slip(s):
    inner = 66                                   # characters between "| " and " |"
    rule = "+" + "-" * (inner + 2) + "+"

    def line(text=""):
        return "| " + text.ljust(inner) + " |"

    def pair(l1, v1, l2, v2):                    # two label/value columns, 32 + 2 + 32
        return line(f"{l1:<21}{v1:>11}  {l2:<21}{v2:>11}")

    def info(l1, v1, l2, v2):
        return line(f"{l1:<12}: {str(v1)[:19]:<19}  {l2:<11}: {str(v2)[:18]}")

    return "\n".join([
        rule,
        line(COMPANY.center(inner)),
        line(f"SALARY SLIP - {s['month_label'].upper()}".center(inner)),
        rule,
        info("Employee", s["employee_name"], "Emp ID", s["emp_id"]),
        info("Designation", s["designation"], "Department", s["dept_name"]),
        info("Joined", s["hire_date"].strftime("%d-%b-%Y"), "Status", s["status"]),
        rule,
        line("ATTENDANCE"),
        pair("Working days", s["working_days"], "Present days", s["present_days"]),
        pair("Paid leave", s["paid_leave_days"], "Unpaid leave", s["unpaid_leave_days"]),
        pair("Absent days", s["absent_days"], "Loss-of-pay days", s["lop_days"]),
        pair("Late marks", s["late_marks"], "Regular hours", s["regular_hours"]),
        pair("OT hrs weekday 1.5x", s["ot_hours_weekday"], "OT hrs holiday 2x", s["ot_hours_holiday"]),
        rule,
        line(f"{'EARNINGS':<32}  {'DEDUCTIONS':<32}"),
        pair("Basic", money(s["basic"]), "Loss of pay", money(s["lop_deduction"])),
        pair("HRA", money(s["hra"]), "Late marks", money(s["late_deduction"])),
        pair("Special allowance", money(s["special_allowance"]), "Provident fund", money(s["pf"])),
        pair("Overtime pay", money(s["ot_pay"]), "Income tax (TDS)", money(s["tds"])),
        rule,
        pair("GROSS EARNINGS", money(s["gross_earnings"]), "TOTAL DEDUCTIONS", money(s["total_deductions"])),
        rule,
        line(f"{'NET SALARY (Rs.)':<40}{money(s['net_salary']):>26}"),
        rule,
        f"  Generated on {s['processed_on'].strftime('%d-%b-%Y %H:%M')}. This is a system-generated slip.",
    ])


def show_slip(db, emp_id, year, month):
    _, results = db.call("sp_salary_slip", (emp_id, year, month))
    cols, rows = results[0]
    slip = dict(zip(cols, rows[0]))
    text = render_slip(slip)
    print("\n" + text)
    if ask("Save slip as a text file? (y/n)", "n").lower() == "y":
        SLIP_DIR.mkdir(exist_ok=True)
        path = SLIP_DIR / f"slip_{emp_id}_{year}-{month:02d}.txt"
        path.write_text(text + "\n")
        print(f"  Saved to {path}")


# ======================================================================
# Employee self-service actions
# ======================================================================
def emp_check_in(db, user):
    _, res = db.call("sp_check_in", (user["emp_id"],))
    print_table(*res[0])


def emp_check_out(db, user):
    _, res = db.call("sp_check_out", (user["emp_id"],))
    print_table(*res[0])


def emp_my_attendance(db, user):
    y, m = ask_month(default=date.today().strftime("%Y-%m"))
    cols, rows = db.query(
        "SELECT cal_date AS date, DATE_FORMAT(cal_date, '%a') AS day, day_status AS status, "
        "       TIME_FORMAT(check_in, '%H:%i') AS `in`, TIME_FORMAT(check_out, '%H:%i') AS `out`, "
        "       CONCAT(FLOOR(worked_minutes / 60), 'h ', LPAD(MOD(worked_minutes, 60), 2, '0'), 'm') AS worked, "
        "       IF(is_late, 'LATE', '') AS late, ot_weekday_minutes + ot_holiday_minutes AS ot_min "
        "FROM v_daily_attendance WHERE emp_id = %s AND YEAR(cal_date) = %s AND MONTH(cal_date) = %s "
        "ORDER BY cal_date", (user["emp_id"], y, m))
    print_table(cols, rows, f"Attendance {y}-{m:02d}")
    summary = db.query(
        "SELECT working_days_elapsed AS working_days, present_days, paid_leave_days, unpaid_leave_days, "
        "       absent_days, late_marks, total_hours, ot_hours_weekday, ot_hours_holiday "
        "FROM v_monthly_attendance WHERE emp_id = %s AND pay_month = %s",
        (user["emp_id"], date(y, m, 1)))
    print_table(*summary, "Summary")


def emp_apply_leave(db, user):
    print_table(*db.query("SELECT code, leave_name, IF(is_paid,'Paid','Unpaid') AS type, annual_quota "
                          "FROM leave_types ORDER BY leave_type_id"), "Leave types")
    code = ask("Leave code").upper()
    frm = ask_date("From")
    to = ask_date("To", frm.isoformat())
    reason = ask("Reason")
    _, res = db.call("sp_apply_leave", (user["emp_id"], code, frm, to, reason))
    print_table(*res[0], "Leave request submitted")


def emp_my_leaves(db, user):
    print_table(*db.query(
        "SELECT leave_code, annual_quota, used_days, pending_days, remaining_days "
        "FROM v_leave_balance WHERE emp_id = %s", (user["emp_id"],)), f"Leave balance {date.today().year}")
    print_table(*db.query(
        "SELECT leave_id, leave_code, from_date, to_date, working_days AS days, status, reviewed_by_name "
        "FROM v_leave_requests WHERE emp_id = %s ORDER BY from_date DESC", (user["emp_id"],)),
        "My leave requests")


def emp_my_slip(db, user):
    print_table(*db.query(
        "SELECT month_label, net_salary, status FROM v_salary_slip WHERE emp_id = %s ORDER BY pay_month DESC",
        (user["emp_id"],)), "Available salary slips")
    y, m = ask_month()
    show_slip(db, user["emp_id"], y, m)


def employee_menu(db, user):
    actions = {
        "1": ("Check in", emp_check_in),
        "2": ("Check out", emp_check_out),
        "3": ("My attendance for a month", emp_my_attendance),
        "4": ("Apply for leave", emp_apply_leave),
        "5": ("My leave balance and requests", emp_my_leaves),
        "6": ("My salary slip", emp_my_slip),
    }
    menu_loop(db, user, "Employee Self-Service", actions)


# ======================================================================
# HR actions
# ======================================================================
def hr_directory(db, user):
    print_table(*db.query(
        "SELECT emp_id, employee_name, designation, dept_name, manager_name, hire_date, status, monthly_ctc_fixed "
        "FROM v_employee_directory ORDER BY emp_id"), "Employee directory")


def hr_add_employee(db, user):
    print_table(*db.query("SELECT dept_id, dept_name FROM departments"), "Departments")
    first = ask("First name")
    last = ask("Last name")
    email = ask("Email")
    phone = ask("Phone", required=False) or None
    gender = ask("Gender (M/F/O)").upper()[:1]
    hire = ask_date("Joining date", date.today().isoformat())
    dept = ask_int("Department id")
    desig = ask("Designation")
    mgr = ask("Manager emp_id (blank for none)", required=False)
    basic = Decimal(ask("Basic"))
    hra = Decimal(ask("HRA", round(basic * Decimal("0.4"))))
    special = Decimal(ask("Special allowance", 0))
    username = ask("Login username")
    password = getpass.getpass("  Initial password (min 6 chars): ")
    role = "HR_ADMIN" if ask("Role: 1) Employee  2) HR Admin", "1") == "2" else "EMPLOYEE"
    new_id, _ = db.call("sp_add_employee", (first, last, email, phone, gender, hire, dept, desig,
                                            int(mgr) if mgr else None, basic, hra, special,
                                            username, password, role), has_out=True)
    print(f"\n  Employee created with emp_id {new_id}")


def hr_revise_salary(db, user):
    emp = ask_int("emp_id")
    print_table(*db.query("SELECT effective_from, basic, hra, special_allowance FROM salary_structure "
                          "WHERE emp_id = %s ORDER BY effective_from", (emp,)), "Salary history")
    basic = Decimal(ask("New basic"))
    hra = Decimal(ask("New HRA", round(basic * Decimal("0.4"))))
    special = Decimal(ask("New special allowance"))
    eff = ask_date("Effective from", date.today().replace(day=1).isoformat())
    db.call("sp_update_salary", (emp, basic, hra, special, eff))
    print("  Salary revised (recorded in audit log).")


def hr_today_board(db, user):
    print_table(*db.query(
        "SELECT d.emp_id, CONCAT(e.first_name,' ',e.last_name) AS employee, d.day_status AS status, "
        "       TIME_FORMAT(d.check_in, '%H:%i') AS `in`, TIME_FORMAT(d.check_out, '%H:%i') AS `out`, "
        "       IF(d.is_late,'LATE','') AS late "
        "FROM v_daily_attendance d JOIN employees e ON e.emp_id = d.emp_id "
        "WHERE d.cal_date = CURDATE() ORDER BY d.emp_id"), f"Attendance board - {date.today():%d %b %Y}")


def hr_correct_attendance(db, user):
    emp = ask_int("emp_id")
    d = ask_date("Date")
    cin = ask("Check-in time (HH:MM)", "09:30")
    cout = ask("Check-out time (HH:MM, blank if none)", required=False)
    db.call("sp_upsert_attendance", (emp, d, f"{d} {cin}:00", f"{d} {cout}:00" if cout else None))
    print("  Attendance saved.")


def hr_leave_requests(db, user):
    cols, rows = db.query(
        "SELECT leave_id, employee_name, leave_code, from_date, to_date, working_days AS days, reason, applied_on "
        "FROM v_leave_requests WHERE status = 'PENDING' ORDER BY applied_on")
    print_table(cols, rows, "Pending leave requests")
    if not rows:
        return
    leave_id = ask("leave_id to review (blank to go back)", required=False)
    if not leave_id:
        return
    decision = "APPROVED" if ask("1) Approve  2) Reject", "1") == "1" else "REJECTED"
    db.call("sp_review_leave", (int(leave_id), user["emp_id"], decision))
    print(f"  Leave {leave_id} {decision.lower()}.")


def hr_monthly_attendance(db, user):
    y, m = ask_month(default=date.today().strftime("%Y-%m"))
    print_table(*db.query(
        "SELECT emp_id, employee_name, dept_name, working_days_elapsed AS wd, present_days AS present, "
        "       paid_leave_days AS pl, unpaid_leave_days AS ul, absent_days AS absent, half_days AS half, "
        "       missed_punches AS missed, late_marks AS late, total_hours, ot_hours_weekday AS ot_wk, "
        "       ot_hours_holiday AS ot_hol "
        "FROM v_monthly_attendance WHERE pay_month = %s ORDER BY emp_id", (date(y, m, 1),)),
        f"Monthly attendance report {y}-{m:02d}")


def hr_late_marks(db, user):
    y, m = ask_month(default=date.today().strftime("%Y-%m"))
    print_table(*db.query(
        "SELECT emp_id, employee_name, late_marks, late_on FROM v_late_marks "
        "WHERE pay_month = %s ORDER BY late_marks DESC", (date(y, m, 1),)), f"Late marks {y}-{m:02d}")


def hr_overtime(db, user):
    y, m = ask_month()
    print_table(*db.query(
        "SELECT ot_rank_in_company AS `rank`, employee_name, dept_name, ot_hours_weekday AS weekday_hrs, "
        "       ot_hours_holiday AS holiday_hrs, total_ot_hours, ot_pay, pct_of_month_ot_pay AS pct "
        "FROM v_overtime_summary WHERE pay_month = %s ORDER BY `rank`", (date(y, m, 1),)),
        f"Overtime summary {y}-{m:02d}")


def hr_generate_payroll(db, user):
    y, m = ask_month()
    _, res = db.call("sp_generate_payroll", (y, m))
    print_table(*res[-1], "Payroll generated")
    print_table(*db.query(
        "SELECT emp_id, employee_name, lop_days, late_marks, ot_pay, gross_earnings, total_deductions, net_salary "
        "FROM v_salary_slip WHERE pay_month = %s ORDER BY emp_id", (date(y, m, 1),)), "Payroll register")


def hr_mark_paid(db, user):
    y, m = ask_month()
    if ask(f"Lock {y}-{m:02d} as PAID? This cannot be undone (y/n)", "n").lower() != "y":
        return
    _, res = db.call("sp_mark_payroll_paid", (y, m))
    print_table(*res[0])


def hr_expenditure(db, user):
    y, m = ask_month()
    cols, rows = db.query(
        "SELECT dept_name, headcount, total_gross, total_ot_pay, total_attendance_deductions AS att_deductions, "
        "       total_pf, total_tds, total_net_paid, pct_of_company_gross AS pct_gross "
        "FROM v_payroll_expenditure WHERE pay_month = %s ORDER BY total_gross DESC", (date(y, m, 1),))
    print_table(cols, rows, f"Payroll expenditure statement {y}-{m:02d}")
    if rows:
        total = db.query_one("SELECT SUM(gross_earnings) g, SUM(net_salary) n, SUM(pf) pf, SUM(tds) tds "
                             "FROM payroll WHERE pay_month = %s", (date(y, m, 1),))
        print(f"  Company total -> gross {money(total['g'])} | PF {money(total['pf'])} | "
              f"TDS {money(total['tds'])} | net paid {money(total['n'])}")


def hr_any_slip(db, user):
    emp = ask_int("emp_id")
    y, m = ask_month()
    show_slip(db, emp, y, m)


def hr_audit(db, user):
    print_table(*db.query("SELECT log_id, table_name, action, details, changed_by, changed_at "
                          "FROM audit_log ORDER BY log_id DESC LIMIT 25"), "Audit log (latest 25)")


def hr_menu(db, user):
    actions = {
        "1": ("Employee directory", hr_directory),
        "2": ("Add new employee", hr_add_employee),
        "3": ("Revise salary", hr_revise_salary),
        "4": ("Today's attendance board", hr_today_board),
        "5": ("Correct an attendance record", hr_correct_attendance),
        "6": ("Review pending leave requests", hr_leave_requests),
        "7": ("Monthly attendance report", hr_monthly_attendance),
        "8": ("Late marks report", hr_late_marks),
        "9": ("Overtime summary", hr_overtime),
        "10": ("Generate monthly payroll", hr_generate_payroll),
        "11": ("Mark payroll as PAID (lock)", hr_mark_paid),
        "12": ("Payroll expenditure statement", hr_expenditure),
        "13": ("View any salary slip", hr_any_slip),
        "14": ("Audit log", hr_audit),
        "15": ("My own self-service", lambda d, u: employee_menu(d, u)),
    }
    menu_loop(db, user, "HR Admin", actions)


def menu_loop(db, user, title, actions):
    while True:
        header(f"{title} - {user['name']}")
        for key, (label, _) in actions.items():
            print(f"  {key:>2}. {label}")
        print("   0. Back / Logout")
        choice = input("\n  Choose: ").strip()
        if choice == "0":
            return
        if choice in actions:
            label, fn = actions[choice]
            if label == "My own self-service":
                fn(db, user)
            else:
                run_safely(fn, db, user)
        else:
            print("  Invalid choice.")


# ======================================================================
def main():
    try:
        db = DB()
    except DBError as e:
        sys.exit(f"Could not connect to MySQL: {e.msg}\n"
                 "Check that MySQL is running and sql/07_security.sql has been run "
                 "(or set PAYROLL_DB_USER / PAYROLL_DB_PASSWORD).")
    try:
        while True:
            user = login(db)
            if not user:
                print("  Too many failed attempts.")
                break
            (hr_menu if user["role"] == "HR_ADMIN" else employee_menu)(db, user)
            if ask("Log in as another user? (y/n)", "n").lower() != "y":
                break
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        db.conn.close()
        print("  Goodbye!")


if __name__ == "__main__":
    main()
