"""
Overtime-Based Payroll and Attendance Management System
Web interface (Streamlit) - role-based: HR Admin / Employee

Same backend as the command-line app: it logs users in against app_users,
connects as the limited 'payroll_app' account, and only CALLs the stored
procedures and SELECTs the views from Phases 1-4. No payroll rule is
re-implemented here.

Run from the project folder:   streamlit run web/app.py
"""
import hashlib
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import mysql.connector
import pandas as pd
import streamlit as st
from mysql.connector import Error as DBError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from payroll_app import money, render_slip  # same slip layout as the CLI  # noqa: E402

st.set_page_config(page_title="Payroll & Attendance System", page_icon="🧾", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 2rem;}
  div[data-testid="stMetric"] {background:#fdf1e7; border:1px solid #f3d3b8; border-radius:10px; padding:12px 16px;}
  .slip {border:1px solid #efc9ab; border-radius:10px; overflow:hidden; max-width:760px;}
  .slip-head {background:#e07b39; color:white; padding:14px 18px;}
  .slip-head h3 {margin:0; color:white;} .slip-head p {margin:2px 0 0 0; opacity:.9;}
  .slip table {width:100%; border-collapse:collapse; font-size:14px;}
  .slip td {padding:6px 18px; border-bottom:1px solid #f6e3d3;}
  .slip td.r {text-align:right; font-variant-numeric: tabular-nums;}
  .slip .sec td {background:#fdf1e7; font-weight:600; color:#b4541a;}
  .slip .net td {background:#b4541a; color:white; font-weight:700; font-size:16px;}
</style>
""", unsafe_allow_html=True)


# ======================================================================
# Database helpers
# ======================================================================
@st.cache_resource
def _connection():
    return mysql.connector.connect(
        host=os.getenv("PAYROLL_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("PAYROLL_DB_PORT", "3306")),
        user=os.getenv("PAYROLL_DB_USER", "payroll_app"),
        password=os.getenv("PAYROLL_DB_PASSWORD", "App@2026"),
        database=os.getenv("PAYROLL_DB_NAME", "payroll_db"),
        autocommit=True,
    )


def conn():
    c = _connection()
    try:
        c.ping(reconnect=True, attempts=2, delay=1)
    except DBError:
        _connection.clear()
        c = _connection()
    return c


def lakh(v):
    """Short money for metric cards: 928174 -> 'Rs 9.28 L'."""
    v = float(v or 0)
    return f"Rs {v / 1e5:.2f} L" if abs(v) >= 1e5 else f"Rs {money(v)}"


def _clean(v):
    return float(v) if isinstance(v, Decimal) else v


def query(sql, params=()):
    cur = conn().cursor()
    cur.execute(sql, params)
    rows = [[_clean(v) for v in r] for r in cur.fetchall()]
    cols = list(cur.column_names)
    cur.close()
    return pd.DataFrame(rows, columns=cols)


def query_one(sql, params=()):
    d = query(sql, params)
    return d.iloc[0].to_dict() if len(d) else None


def call(proc, args=(), has_out=False):
    """CALL a stored procedure; returns (out_value, [DataFrame per result set])."""
    cur = conn().cursor()
    if "user" in st.session_state:                      # audit trail: who made the change
        cur.execute("SET @app_user = %s", (f"web:{st.session_state.user['username']}",))
    params = ", ".join(["%s"] * len(args) + (["@out_param"] if has_out else []))
    cur.execute(f"CALL {proc}({params})", tuple(args))
    results = []
    while True:
        if cur.with_rows:
            results.append(pd.DataFrame([[_clean(v) for v in r] for r in cur.fetchall()],
                                        columns=list(cur.column_names)))
        if not cur.nextset():
            break
    out = None
    if has_out:
        cur.execute("SELECT @out_param")
        out = cur.fetchone()[0]
    cur.close()
    return out, results


def attempt(fn, success=None):
    """Run a database action; show the SIGNAL message from MySQL if it is rejected."""
    try:
        result = fn()
        if success:
            st.success(success)
        return result if result is not None else True
    except DBError as e:
        st.error(e.msg)
        return None


def flash_and_rerun(message):
    st.session_state.flash = message
    st.rerun()


def months(source="attendance"):
    sql = ("SELECT DISTINCT DATE_FORMAT(att_date, '%Y-%m-01') m FROM attendance ORDER BY m DESC"
           if source == "attendance" else
           "SELECT DISTINCT DATE_FORMAT(pay_month, '%Y-%m-01') m FROM payroll ORDER BY m DESC")
    return [date.fromisoformat(m) for m in query(sql)["m"]]


def month_picker(label, options, key, index=0):
    return st.selectbox(label, options, index=min(index, len(options) - 1) if options else 0,
                        format_func=lambda d: d.strftime("%B %Y"), key=key)


def show(d, height=None):
    d = d.copy()
    for c in d.columns:                                   # show blanks instead of "None" in text columns
        if not pd.api.types.is_numeric_dtype(d[c]) and d[c].isna().any():
            d[c] = d[c].astype(object).where(d[c].notna(), "")
    extra = {"height": height} if height else {}
    st.dataframe(d, hide_index=True, use_container_width=True, **extra)


# ======================================================================
# Login
# ======================================================================
def login_page():
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.markdown("## 🧾 Payroll & Attendance System")
        st.caption("TechSphere Solutions, Gurugram (demo company)")
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            ok = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if ok:
            u = query_one(
                "SELECT u.emp_id, u.username, u.password_hash, u.salt, u.role, "
                "CONCAT(e.first_name, ' ', e.last_name) AS name, e.designation "
                "FROM app_users u JOIN employees e ON e.emp_id = u.emp_id "
                "WHERE u.username = %s AND u.is_active AND e.status = 'ACTIVE'", (username.strip(),))
            if u and hashlib.sha256((u["salt"] + password).encode()).hexdigest() == u["password_hash"]:
                st.session_state.user = u
                st.rerun()
            st.error("Invalid username or password")
        st.info("Demo logins: **HR** neha / hr@1234 · **Employee** rahul / emp@1234")


# ======================================================================
# Salary slip (shared by HR and employee pages)
# ======================================================================
def slip_view(emp_id, month):
    _, res = call("sp_salary_slip", (emp_id, month.year, month.month))
    s = res[0].iloc[0].to_dict()
    rows = lambda pairs: "".join(f"<tr><td>{a}</td><td class='r'>{b}</td><td>{c}</td><td class='r'>{d}</td></tr>"
                                 for a, b, c, d in pairs)
    st.markdown(f"""
<div class="slip">
  <div class="slip-head"><h3>Salary slip - {s['month_label']}</h3>
    <p>{s['employee_name']} · Emp {s['emp_id']} · {s['designation']} · {s['dept_name']} · {s['status']}</p></div>
  <table>
    <tr class="sec"><td colspan="4">Attendance</td></tr>
    {rows([("Working days", s['working_days'], "Present days", s['present_days']),
           ("Paid leave", s['paid_leave_days'], "Unpaid leave", s['unpaid_leave_days']),
           ("Absent days", s['absent_days'], "Loss-of-pay days", s['lop_days']),
           ("Late marks", s['late_marks'], "Regular hours", s['regular_hours']),
           ("OT hours weekday (1.5x)", s['ot_hours_weekday'], "OT hours holiday (2x)", s['ot_hours_holiday'])])}
    <tr class="sec"><td colspan="2">Earnings (Rs)</td><td colspan="2">Deductions (Rs)</td></tr>
    {rows([("Basic", money(s['basic']), "Loss of pay", money(s['lop_deduction'])),
           ("HRA", money(s['hra']), "Late marks", money(s['late_deduction'])),
           ("Special allowance", money(s['special_allowance']), "Provident fund", money(s['pf'])),
           ("Overtime pay", money(s['ot_pay']), "Income tax (TDS)", money(s['tds'])),
           ("<b>Gross earnings</b>", f"<b>{money(s['gross_earnings'])}</b>",
            "<b>Total deductions</b>", f"<b>{money(s['total_deductions'])}</b>")])}
    <tr class="net"><td colspan="3">Net salary (Rs)</td><td class="r">{money(s['net_salary'])}</td></tr>
  </table>
</div>""", unsafe_allow_html=True)
    s["hire_date"] = pd.Timestamp(s["hire_date"]).date()
    s["processed_on"] = pd.Timestamp(s["processed_on"]).to_pydatetime()
    st.download_button("⬇ Download slip (.txt)", render_slip(s) + "\n",
                       file_name=f"slip_{emp_id}_{month:%Y-%m}.txt", key=f"dl_{emp_id}_{month}")


# ======================================================================
# Employee self-service pages
# ======================================================================
def page_my_today(u):
    st.subheader(f"Good to see you, {u['name'].split()[0]} 👋")
    today = query_one("SELECT day_status, check_in, check_out, worked_minutes, is_late "
                      "FROM v_daily_attendance WHERE emp_id = %s AND cal_date = CURDATE()", (u["emp_id"],))
    c1, c2, c3 = st.columns(3)
    c1.metric("Today", (today or {}).get("day_status", "-").replace("_", " ").title())
    c2.metric("Checked in", pd.Timestamp(today["check_in"]).strftime("%H:%M") if today and today["check_in"] else "-")
    c3.metric("Checked out", pd.Timestamp(today["check_out"]).strftime("%H:%M") if today and today["check_out"] else "-")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("✅ Check in", type="primary", use_container_width=True):
        if attempt(lambda: call("sp_check_in", (u["emp_id"],))):
            flash_and_rerun("Checked in. Have a good day!")
    if b2.button("🏁 Check out", use_container_width=True):
        if attempt(lambda: call("sp_check_out", (u["emp_id"],))):
            flash_and_rerun("Checked out. See you tomorrow!")
    st.markdown("#### This month so far")
    m = query_one("SELECT * FROM v_monthly_attendance WHERE emp_id = %s AND pay_month = %s",
                  (u["emp_id"], date.today().replace(day=1)))
    if m:
        k = st.columns(5)
        k[0].metric("Present days", m["present_days"])
        k[1].metric("Late marks", int(m["late_marks"]))
        k[2].metric("Leave days", m["paid_leave_days"] + m["unpaid_leave_days"])
        k[3].metric("Hours worked", m["total_hours"])
        k[4].metric("Overtime hours", round(m["ot_hours_weekday"] + m["ot_hours_holiday"], 2))


def page_my_attendance(u):
    st.subheader("My attendance")
    month = month_picker("Month", months(), "my_att_month")
    d = query("SELECT cal_date AS date, DATE_FORMAT(cal_date, '%a') AS day, day_status AS status, "
              "TIME_FORMAT(check_in, '%H:%i') AS check_in, TIME_FORMAT(check_out, '%H:%i') AS check_out, "
              "ROUND(worked_minutes / 60, 2) AS hours, IF(is_late, 'LATE', '') AS late, "
              "ot_weekday_minutes + ot_holiday_minutes AS ot_minutes "
              "FROM v_daily_attendance WHERE emp_id = %s AND cal_date BETWEEN %s AND LAST_DAY(%s) "
              "ORDER BY cal_date", (u["emp_id"], month, month))
    show(d, height=420)


def page_my_leave(u):
    st.subheader("My leave")
    bal = query("SELECT leave_code, leave_name, annual_quota, used_days, pending_days, remaining_days "
                "FROM v_leave_balance WHERE emp_id = %s", (u["emp_id"],))
    cols = st.columns(len(bal) or 1)
    for col, (_, r) in zip(cols, bal.iterrows()):
        col.metric(f"{r['leave_name']} left", f"{r['remaining_days']:g} / {r['annual_quota']:g}")
    with st.form("apply_leave", clear_on_submit=True):
        st.markdown("**Apply for leave**")
        types = query("SELECT code, leave_name FROM leave_types ORDER BY leave_type_id")
        c1, c2, c3 = st.columns(3)
        code = c1.selectbox("Type", types["code"], format_func=lambda c: types.set_index("code").loc[c, "leave_name"])
        frm = c2.date_input("From", date.today())
        to = c3.date_input("To", date.today())
        reason = st.text_input("Reason")
        if st.form_submit_button("Submit request", type="primary"):
            attempt(lambda: call("sp_apply_leave", (u["emp_id"], code, frm, to, reason or "-")),
                    "Leave request submitted - waiting for HR approval")
    st.markdown("#### My requests")
    show(query("SELECT leave_id, leave_code, from_date, to_date, working_days AS days, status, "
               "reviewed_by_name AS reviewed_by FROM v_leave_requests WHERE emp_id = %s ORDER BY from_date DESC",
               (u["emp_id"],)))


def page_my_slips(u):
    st.subheader("My salary slips")
    avail = [pd.Timestamp(m).date() for m in
             query("SELECT pay_month FROM payroll WHERE emp_id = %s ORDER BY pay_month DESC", (u["emp_id"],))["pay_month"]]
    if not avail:
        st.info("No salary slips yet.")
        return
    month = month_picker("Month", avail, "my_slip_month")
    slip_view(u["emp_id"], month)


# ======================================================================
# HR pages
# ======================================================================
def page_hr_dashboard(u):
    st.subheader("HR dashboard")
    k = query_one("SELECT (SELECT COUNT(*) FROM employees WHERE status='ACTIVE') emps, "
                  "(SELECT COUNT(*) FROM attendance WHERE att_date = CURDATE()) in_today, "
                  "(SELECT COUNT(*) FROM leave_requests WHERE status='PENDING') pending, "
                  "(SELECT MAX(pay_month) FROM payroll) last_month")
    last = pd.Timestamp(k["last_month"]).date() if k["last_month"] else None
    net = query_one("SELECT SUM(net_salary) n, SUM(ot_pay) ot FROM payroll WHERE pay_month = %s", (last,)) if last else None
    c = st.columns(4)
    c[0].metric("Active employees", int(k["emps"]))
    c[1].metric("Checked in today", int(k["in_today"]))
    c[2].metric("Pending leave requests", int(k["pending"]))
    c[3].metric(f"Net payroll {last:%b %Y}" if last else "Net payroll", lakh(net['n']) if net else "-")
    if last:
        l, r = st.columns(2)
        with l:
            st.markdown(f"**Gross payroll by department, {last:%B %Y}**")
            d = query("SELECT dept_name, total_gross FROM v_payroll_expenditure WHERE pay_month = %s", (last,))
            st.bar_chart(d.set_index("dept_name"), color="#e07b39")
        with r:
            st.markdown(f"**Overtime hours by employee, {last:%B %Y}**")
            d = query("SELECT employee_name, total_ot_hours FROM v_overtime_summary WHERE pay_month = %s "
                      "AND total_ot_hours > 0 ORDER BY total_ot_hours DESC", (last,))
            st.bar_chart(d.set_index("employee_name"), color="#b4541a")
    st.markdown("#### Today's attendance board")
    show(query("SELECT d.emp_id, CONCAT(e.first_name,' ',e.last_name) AS employee, d.day_status AS status, "
               "TIME_FORMAT(d.check_in,'%H:%i') AS check_in, TIME_FORMAT(d.check_out,'%H:%i') AS check_out, "
               "IF(d.is_late,'LATE','') AS late FROM v_daily_attendance d JOIN employees e ON e.emp_id = d.emp_id "
               "WHERE d.cal_date = CURDATE() ORDER BY d.emp_id"))


def page_hr_employees(u):
    st.subheader("Employees")
    show(query("SELECT emp_id, employee_name, designation, dept_name, manager_name, hire_date, status, "
               "monthly_ctc_fixed AS monthly_fixed_pay FROM v_employee_directory ORDER BY emp_id"))
    depts = query("SELECT dept_id, dept_name FROM departments")
    with st.expander("➕ Add new employee"):
        with st.form("add_emp", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            first, last, email = c1.text_input("First name"), c2.text_input("Last name"), c3.text_input("Email")
            phone, gender, hire = c1.text_input("Phone"), c2.selectbox("Gender", ["M", "F", "O"]), c3.date_input("Joining date")
            dept = c1.selectbox("Department", depts["dept_id"], format_func=lambda i: depts.set_index("dept_id").loc[i, "dept_name"])
            desig, mgr = c2.text_input("Designation"), c3.number_input("Manager emp_id (0 = none)", min_value=0, step=1)
            basic = c1.number_input("Basic", min_value=0.0, step=1000.0)
            hra = c2.number_input("HRA", min_value=0.0, step=500.0)
            special = c3.number_input("Special allowance", min_value=0.0, step=500.0)
            username, password = c1.text_input("Login username"), c2.text_input("Initial password", type="password")
            role = c3.selectbox("Role", ["EMPLOYEE", "HR_ADMIN"])
            if st.form_submit_button("Create employee", type="primary"):
                new_id = attempt(lambda: call("sp_add_employee", (first, last, email, phone or None, gender, hire, int(dept),
                                                                   desig, int(mgr) or None, basic, hra, special,
                                                                   username, password, role), has_out=True)[0])
                if new_id:
                    st.success(f"Employee created with emp_id {new_id}")
    with st.expander("✏️ Revise salary"):
        emp = st.number_input("emp_id", min_value=1001, step=1, key="rev_emp")
        show(query("SELECT effective_from, basic, hra, special_allowance FROM salary_structure "
                   "WHERE emp_id = %s ORDER BY effective_from", (int(emp),)))
        with st.form("revise"):
            c1, c2, c3, c4 = st.columns(4)
            b = c1.number_input("New basic", min_value=0.0, step=1000.0)
            h = c2.number_input("New HRA", min_value=0.0, step=500.0)
            s = c3.number_input("New special", min_value=0.0, step=500.0)
            eff = c4.date_input("Effective from", date.today().replace(day=1))
            if st.form_submit_button("Save revision", type="primary"):
                attempt(lambda: call("sp_update_salary", (int(emp), b, h, s, eff)), "Salary revised (recorded in audit log)")


def page_hr_attendance(u):
    st.subheader("Attendance")
    t1, t2, t3, t4 = st.tabs(["Monthly summary", "Late marks", "Employee day-by-day", "Correct a record"])
    with t1:
        m = month_picker("Month", months(), "att_sum_month", index=1)
        show(query("SELECT emp_id, employee_name, dept_name, working_days_elapsed AS working_days, present_days, "
                   "paid_leave_days, unpaid_leave_days, absent_days, half_days, missed_punches, late_marks, "
                   "total_hours, ot_hours_weekday, ot_hours_holiday FROM v_monthly_attendance "
                   "WHERE pay_month = %s ORDER BY emp_id", (m,)))
    with t2:
        m = month_picker("Month", months(), "late_month", index=1)
        show(query("SELECT emp_id, employee_name, late_marks, late_on FROM v_late_marks "
                   "WHERE pay_month = %s ORDER BY late_marks DESC", (m,)))
    with t3:
        emps = query("SELECT emp_id, employee_name FROM v_employee_directory ORDER BY emp_id")
        c1, c2 = st.columns(2)
        e = c1.selectbox("Employee", emps["emp_id"], format_func=lambda i: f"{i} - {emps.set_index('emp_id').loc[i, 'employee_name']}")
        m = month_picker("Month", months(), "day_month", index=1)
        show(query("SELECT cal_date AS date, day_status AS status, TIME_FORMAT(check_in,'%H:%i') AS check_in, "
                   "TIME_FORMAT(check_out,'%H:%i') AS check_out, ROUND(worked_minutes/60,2) AS hours, "
                   "IF(is_late,'LATE','') AS late, ot_weekday_minutes + ot_holiday_minutes AS ot_minutes "
                   "FROM v_daily_attendance WHERE emp_id = %s AND cal_date BETWEEN %s AND LAST_DAY(%s) ORDER BY cal_date",
                   (int(e), m, m)), height=420)
    with t4:
        st.caption("Fix a missed punch or wrong time. Months that are already PAID are locked by a trigger.")
        with st.form("correct"):
            c1, c2, c3, c4 = st.columns(4)
            e = c1.number_input("emp_id", min_value=1001, step=1)
            d = c2.date_input("Date")
            cin = c3.time_input("Check-in")
            cout = c4.time_input("Check-out")
            if st.form_submit_button("Save", type="primary"):
                attempt(lambda: call("sp_upsert_attendance", (int(e), d, f"{d} {cin}", f"{d} {cout}")), "Attendance saved")


def page_hr_leave(u):
    st.subheader("Leave requests")
    pend = query("SELECT leave_id, employee_name, leave_code, from_date, to_date, working_days, reason "
                 "FROM v_leave_requests WHERE status = 'PENDING' ORDER BY applied_on")
    if pend.empty:
        st.success("No pending requests 🎉")
    for _, r in pend.iterrows():
        with st.container(border=True):
            a, b, c = st.columns([4, 1, 1])
            a.markdown(f"**{r['employee_name']}** · {r['leave_code']} · {r['from_date']} → {r['to_date']} "
                       f"({r['working_days']} working days)  \n_{r['reason']}_")
            if b.button("Approve", key=f"ap{r['leave_id']}", type="primary", use_container_width=True):
                if attempt(lambda: call("sp_review_leave", (int(r["leave_id"]), u["emp_id"], "APPROVED"))):
                    flash_and_rerun(f"Approved leave for {r['employee_name']}")
            if c.button("Reject", key=f"rj{r['leave_id']}", use_container_width=True):
                if attempt(lambda: call("sp_review_leave", (int(r["leave_id"]), u["emp_id"], "REJECTED"))):
                    flash_and_rerun(f"Rejected leave for {r['employee_name']}")
    st.markdown("#### All requests")
    show(query("SELECT leave_id, employee_name, leave_code, from_date, to_date, working_days AS days, status, "
               "reviewed_by_name AS reviewed_by FROM v_leave_requests ORDER BY applied_on DESC"))


def page_hr_payroll(u):
    st.subheader("Payroll")
    first_this_month = date.today().replace(day=1)
    runnable = [m for m in months() if m < first_this_month]
    m = month_picker("Payroll month", runnable, "pay_month")
    c2, c3, _ = st.columns([1, 1, 3])
    if c2.button("⚙️ Generate payroll", type="primary", use_container_width=True):
        attempt(lambda: call("sp_generate_payroll", (m.year, m.month)), f"Payroll generated for {m:%B %Y}")
    lock = c3.button("🔒 Mark as PAID", use_container_width=True)
    if lock:
        st.session_state.confirm_lock = m
    if st.session_state.get("confirm_lock") == m:
        st.warning(f"Locking {m:%B %Y} as PAID cannot be undone. Attendance and payroll for that month become read-only.")
        y, n, _ = st.columns([1, 1, 4])
        if y.button("Yes, lock it", type="primary"):
            attempt(lambda: call("sp_mark_payroll_paid", (m.year, m.month)), f"{m:%B %Y} marked as PAID")
            st.session_state.confirm_lock = None
        if n.button("Cancel"):
            st.session_state.confirm_lock = None
            st.rerun()
    t1, t2, t3 = st.tabs(["Payroll register", "Overtime summary", "Expenditure statement"])
    with t1:
        d = query("SELECT emp_id, employee_name, dept_name, lop_days, late_marks, ot_pay, gross_earnings, "
                  "lop_deduction, late_deduction, pf, tds, total_deductions, net_salary, status "
                  "FROM v_salary_slip WHERE pay_month = %s ORDER BY emp_id", (m,))
        if d.empty:
            st.info("No payroll generated for this month yet.")
        else:
            k = st.columns(4)
            k[0].metric("Employees", len(d))
            k[1].metric("Gross", lakh(d['gross_earnings'].sum()))
            k[2].metric("Deductions", lakh(d['total_deductions'].sum()))
            k[3].metric("Net paid", lakh(d['net_salary'].sum()))
            show(d)
    with t2:
        show(query("SELECT ot_rank_in_company AS `rank`, employee_name, dept_name, ot_hours_weekday, ot_hours_holiday, "
                   "total_ot_hours, ot_pay, pct_of_month_ot_pay AS pct_of_ot_pay FROM v_overtime_summary "
                   "WHERE pay_month = %s ORDER BY `rank`", (m,)))
    with t3:
        d = query("SELECT dept_name, headcount, total_gross, total_ot_pay, total_attendance_deductions, total_pf, "
                  "total_tds, total_net_paid, pct_of_company_gross FROM v_payroll_expenditure "
                  "WHERE pay_month = %s ORDER BY total_gross DESC", (m,))
        show(d)
        if not d.empty:
            st.bar_chart(d.set_index("dept_name")[["total_net_paid", "total_pf", "total_tds"]],
                         color=["#e07b39", "#f2b48a", "#b4541a"])


def page_hr_slips(u):
    st.subheader("Salary slips")
    emps = query("SELECT emp_id, employee_name FROM v_employee_directory ORDER BY emp_id")
    c1, c2 = st.columns(2)
    e = c1.selectbox("Employee", emps["emp_id"], index=3,
                     format_func=lambda i: f"{i} - {emps.set_index('emp_id').loc[i, 'employee_name']}")
    with c2:
        m = month_picker("Month", months("payroll"), "hr_slip_month")
    attempt(lambda: slip_view(int(e), m))


def page_hr_audit(u):
    st.subheader("Audit log")
    st.caption("Written automatically by triggers. HR can read it but cannot delete it.")
    show(query("SELECT log_id, table_name, action, details, changed_by, changed_at FROM audit_log "
               "ORDER BY log_id DESC LIMIT 100"))


# ======================================================================
# Navigation
# ======================================================================
HR_PAGES = {"Dashboard": page_hr_dashboard, "Employees": page_hr_employees, "Attendance": page_hr_attendance,
            "Leave requests": page_hr_leave, "Payroll": page_hr_payroll, "Salary slips": page_hr_slips,
            "Audit log": page_hr_audit}
EMP_PAGES = {"Today": page_my_today, "My attendance": page_my_attendance, "My leave": page_my_leave,
             "My salary slips": page_my_slips}


def main():
    try:
        conn()
    except DBError as e:
        st.error(f"Could not connect to MySQL: {e.msg}. Is MySQL running, and has ./setup.sh been run?")
        st.stop()
    if "user" not in st.session_state:
        login_page()
        return
    u = st.session_state.user
    with st.sidebar:
        st.markdown(f"### {u['name']}")
        st.caption(f"{u['designation']} · {'HR Admin' if u['role'] == 'HR_ADMIN' else 'Employee'}")
        if u["role"] == "HR_ADMIN":
            pages = {**HR_PAGES, **{f"Me: {k}": v for k, v in EMP_PAGES.items()}}
        else:
            pages = EMP_PAGES
        choice = st.radio("Go to", list(pages), label_visibility="collapsed")
        st.divider()
        if st.button("Log out", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    pages[choice](u)


main()
