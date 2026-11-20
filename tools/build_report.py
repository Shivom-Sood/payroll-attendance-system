"""
Builds the capstone report PDF: docs/Capstone_Report_Shivom_Sood.pdf
All figures (counts, payroll totals, worked example, test results) are read
live from payroll_db and tests/test_results.md, so the report always matches
the system.   Run after ./setup.sh:   python3 tools/build_report.py
"""
import os
import re
from datetime import date
from pathlib import Path

import mysql.connector
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "Capstone_Report_Shivom_Sood.pdf"
GITHUB = "https://github.com/Shivom-Sood/payroll-attendance-system"
W = A4[0] - 4 * cm

db = mysql.connector.connect(host=os.getenv("PAYROLL_DB_HOST", "127.0.0.1"), user="root",
                             password=os.getenv("MYSQL_PWD", ""), database="payroll_db")


def q(sql):
    cur = db.cursor(dictionary=True)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    return rows


def money(v):
    v = float(v)
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{'-' if v < 0 else ''}{whole}.{frac}"


# ---------------------------------------------------------------- styles
ss = getSampleStyleSheet()
NAVY = colors.HexColor("#1f3864")
ACC = colors.HexColor("#2e5c9a")
LIGHT = colors.HexColor("#eef3fb")
body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10, leading=14.2,
                      spaceAfter=6, alignment=4)
small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, spaceAfter=0, alignment=0)
cellst = ParagraphStyle("cell", parent=body, fontSize=8.6, leading=11, spaceAfter=0, alignment=0)
cellb = ParagraphStyle("cellb", parent=cellst, fontName="Helvetica-Bold", textColor=colors.white)
h1 = ParagraphStyle("h1", parent=ss["Heading1"], keepWithNext=1, fontName="Helvetica-Bold", fontSize=16, textColor=NAVY,
                    spaceBefore=4, spaceAfter=8)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], keepWithNext=1, fontName="Helvetica-Bold", fontSize=12.5, textColor=ACC,
                    spaceBefore=10, spaceAfter=5)
h3 = ParagraphStyle("h3", parent=ss["Heading3"], keepWithNext=1, fontName="Helvetica-Bold", fontSize=10.5, textColor=NAVY,
                    spaceBefore=6, spaceAfter=3)
caption = ParagraphStyle("cap", parent=body, fontSize=8.5, textColor=colors.HexColor("#555555"),
                         alignment=TA_CENTER, spaceBefore=3, spaceAfter=10)
code = ParagraphStyle("code", fontName="Courier", fontSize=8.2, leading=10.4, backColor=colors.HexColor("#f5f6f8"),
                      borderColor=colors.HexColor("#d9dce1"), borderWidth=0.5, borderPadding=6,
                      spaceBefore=4, spaceAfter=10, leftIndent=6, rightIndent=6)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=4, spaceAfter=3)

story = []
P = lambda t, s=body: story.append(Paragraph(t, s))
B = lambda t: story.append(Paragraph(t, bullet, bulletText="•"))


def table(rows, widths, header=True, font=8.6, zebra=True, keep=False):
    data = [[Paragraph(str(c), cellb if (header and i == 0) else
                       ParagraphStyle("c", parent=cellst, fontSize=font, leading=font + 2.4))
             for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c5ccd6")),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), ACC))
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(st))
    story.append(KeepTogether([t]) if keep else t)
    story.append(Spacer(1, 8))


def img(path, cap, max_w=W, max_h=21 * cm):
    with PILImage.open(path) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    story.append(KeepTogether([Image(str(path), width=w * scale, height=h * scale),
                               Paragraph(cap, caption)]))


def shot(name, cap, max_w=W, max_h=21 * cm):
    img(ROOT / "docs" / "screenshots" / f"{name}.png", cap, max_w, max_h)


def codeblock(text):
    story.append(KeepTogether([Preformatted(text.strip("\n"), code)]))


# ---------------------------------------------------------------- live figures
counts = q("""SELECT
   (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='payroll_db' AND TABLE_TYPE='BASE TABLE') t,
   (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA='payroll_db') v,
   (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='payroll_db' AND ROUTINE_TYPE='FUNCTION') f,
   (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='payroll_db' AND ROUTINE_TYPE='PROCEDURE') p,
   (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='payroll_db') tr,
   (SELECT COUNT(*) FROM employees) emps, (SELECT COUNT(*) FROM attendance) att,
   (SELECT COUNT(*) FROM leave_requests) lv, (SELECT COUNT(*) FROM payroll) pay,
   (SELECT MIN(att_date) FROM attendance) a_from, (SELECT MAX(att_date) FROM attendance) a_to""")[0]
months = q("""SELECT month_label, working_days wd, COUNT(*) n, SUM(gross_earnings) g, SUM(ot_pay) ot,
                     SUM(total_deductions) d, SUM(net_salary) net, MAX(status) st
              FROM v_salary_slip GROUP BY pay_month, month_label, working_days ORDER BY pay_month""")
rahul = q("SELECT * FROM v_salary_slip WHERE emp_id=1004 AND pay_month='2026-10-01'")[0]
res_md = (ROOT / "tests" / "test_results.md").read_text()
tot = re.search(r"\*\*(\d+) of (\d+) test cases passed", res_md)
test_rows = []
for line in res_md.split("\n"):
    m = re.match(r"\| ([VIB]\d\d) \| (.*?) \| (.*?) \| (.*?) \| (PASS|FAIL) \|", line)
    if m:
        test_rows.append(m.groups())
idx = (ROOT / "docs" / "output" / "index_optimization_results.txt").read_text()
times = [float(x) for x in re.findall(r"^\| -> (?:Group aggregate|Table scan on <temporary>).*?actual time=[0-9.]+\.\.([0-9.]+)",
                                      idx, flags=re.M)]

# ================================================================ COVER
story += [Spacer(1, 2.2 * cm),
          Paragraph("KR MANGALAM UNIVERSITY, GURUGRAM", ParagraphStyle("u", parent=body, alignment=TA_CENTER,
                    fontName="Helvetica-Bold", fontSize=13, textColor=NAVY)),
          Paragraph("School of Engineering &amp; Technology", ParagraphStyle("u2", parent=body, alignment=TA_CENTER)),
          Spacer(1, 1.6 * cm),
          Paragraph("DBMS CAPSTONE PROJECT REPORT", ParagraphStyle("t0", parent=body, alignment=TA_CENTER,
                    fontName="Helvetica-Bold", fontSize=12, textColor=ACC)),
          Spacer(1, 0.4 * cm),
          Paragraph("Overtime-Based Payroll and<br/>Attendance Management System",
                    ParagraphStyle("t", parent=body, alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=24,
                                   leading=30, textColor=NAVY)),
          Spacer(1, 0.5 * cm),
          Paragraph("A full-lifecycle MySQL application for a mid-sized IT firm: data modelling, procedural SQL, "
                    "reporting and optimisation, transactional security, and a role-based interface",
                    ParagraphStyle("st", parent=body, alignment=TA_CENTER, fontSize=11, leading=15,
                                   textColor=colors.HexColor("#444444"))),
          Spacer(1, 2.2 * cm)]
cover = Table([[Paragraph("<b>Submitted by</b>", cellst), Paragraph("Shivom Sood", cellst)],
               [Paragraph("<b>Roll number</b>", cellst), Paragraph("2501730435", cellst)],
               [Paragraph("<b>Programme</b>", cellst), Paragraph("B.Tech CSE (AI &amp; ML), Semester 3", cellst)],
               [Paragraph("<b>Course</b>", cellst), Paragraph("Database Management Systems", cellst)],
               [Paragraph("<b>Project type</b>", cellst), Paragraph("Individual (solo) capstone, topic #11", cellst)],
               [Paragraph("<b>Source code</b>", cellst), Paragraph(f'<link href="{GITHUB}" color="blue">{GITHUB}</link>', cellst)],
               [Paragraph("<b>Date</b>", cellst), Paragraph(date.today().strftime("%B %Y"), cellst)]],
              colWidths=[4 * cm, 10 * cm])
cover.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c5ccd6")),
                           ("BACKGROUND", (0, 0), (0, -1), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
story += [cover, PageBreak()]

# ================================================================ CONTENTS
P("Contents", h1)
toc = [("1", "Introduction and objectives"), ("2", "Phase 1: Data modelling and schema design"),
       ("3", "Phase 2: Procedural implementation"), ("4", "Phase 3: Query and report development"),
       ("5", "Phase 4: Security, access control and testing"), ("6", "Phase 5: Integration and user interface"),
       ("7", "Real-world use cases and scaling to a larger firm"), ("8", "Limitations and future scope"),
       ("9", "Conclusion"), ("A", "Appendix: project files and how to run")]
table([["No.", "Section"]] + [list(t) for t in toc], [1.4 * cm, W - 1.4 * cm], zebra=False)
P("<b>How the five phases connect.</b> Phase 1's schema is implemented unchanged in Phase 2; Phase 2's data feeds "
  "every Phase 3 report; Phase 4 secures and tests the same objects; and Phase 5's interface calls only those "
  "Phase 1-4 database objects. Everything runs as one database (<font face='Courier'>payroll_db</font>) built by "
  "one script (<font face='Courier'>setup.sh</font>), not as separate scripts per phase.")
table([["Phase", "Requirement (from the brief)", "Where it is delivered"],
       ["1", "ER diagram with cardinalities, 3NF, PK/FK schema", "Section 2; sql/01_schema.sql; docs/er_diagram_chen.png"],
       ["2", "DDL, salary &amp; tax procedures/functions, validation triggers, 10+ employees over 3 months",
        "Section 3; sql/02, 04, 05, 06"],
       ["3", "Monthly attendance, salary slip, late-marks reports; indexes with before/after plans",
        "Section 4; sql/03_views.sql, sql/09_index_optimization.sql"],
       ["4", "RBAC (HR vs employee), COMMIT/ROLLBACK, valid/invalid/boundary tests documented",
        "Section 5; sql/07_security.sql, tests/run_tests.py, tests/test_results.md"],
       ["5", "Role-based CLI on the same backend, README, screenshots, use-case report",
        "Sections 6-7; app/payroll_app.py, README.md, docs/screenshots/"]],
      [1.3 * cm, 7.6 * cm, W - 8.9 * cm])
story.append(PageBreak())

# ================================================================ 1 INTRODUCTION
P("1. Introduction and objectives", h1)
P("Payroll in an IT company depends on attendance. Salaries change every month because of overtime, late arrivals, "
  "leave without pay, mid-month joiners and tax. Doing this in spreadsheets is slow and error-prone, and it gives "
  "employees no reliable view of their own records. This project builds a database-centred system for a fictional "
  "mid-sized IT firm, <i>TechSphere Solutions, Gurugram</i>, that records daily check-in and check-out, calculates "
  "regular and overtime hours, manages leave approvals, and generates the monthly payroll with salary slips and "
  "management reports.")
P("Objectives", h2)
for t in ["Design a normalised (3NF) relational schema for employees, attendance, leave, salary and payroll.",
          "Put the business rules (overtime, late marks, loss of pay, PF, income tax) inside the database as stored "
          "functions, procedures and triggers, so every client gets identical results.",
          "Produce the required reports (monthly attendance, salary slip, late marks) plus overtime and expenditure "
          "statements, and show measurable speed-up from indexing.",
          "Enforce role-based access (HR full access, employees only their own records) and transactional safety.",
          "Provide a role-based command-line interface and prove correctness with an automated test suite."]:
    B(t)
P("Technology", h2)
table([["Layer", "Choice", "Reason"],
       ["Database", "MySQL 8.0+ (developed for 9.x)", "Course standard; supports CTEs, window functions, roles, CHECK"],
       ["Business logic", "Stored functions, procedures, triggers", "Rules enforced centrally and cannot be bypassed"],
       ["Interface", "Python 3 CLI + mysql-connector-python", "Simple, portable, parameterised queries"],
       ["Tools", "MySQL Workbench, Graphviz (diagrams), Git/GitHub", "Design, documentation and version control"]],
      [3 * cm, 5.6 * cm, W - 8.6 * cm])
P("Scope and assumptions", h2)
P("Five-day week (Monday-Friday) with a company holiday list; a 9-hour shift starting 09:30 including a one-hour break; "
  "monthly payroll processed after the month ends. Organisational rules are stored in a <font face='Courier'>payroll_policy</font> "
  "table, so they can be changed without touching code. Tax and PF are simplified versions of Indian rules for academic purposes.")
story.append(PageBreak())

# ================================================================ 2 PHASE 1
P("2. Phase 1: Data modelling and schema design", h1)
P("2.1 Entities", h2)
P("The brief's core entities are <b>Employee, Attendance, Leave, Salary and Payroll</b>. While modelling, Leave split into "
  "<b>LEAVE_TYPE</b> (the rules for casual, sick, earned and unpaid leave) and <b>LEAVE_REQUEST</b> (each application). "
  "<b>DEPARTMENT</b> and <b>APP_USER</b> (login) were added. Rules that are not facts about a person were also moved "
  "into their own tables: payroll_policy, tax_slabs, holidays and calendar. The theme allows extending entities.")
img(ROOT / "docs" / "er_diagram_chen.png", "Figure 1: ER diagram (Chen notation). Rectangles are entities, diamonds are "
    "relationships, ellipses are attributes; keys are underlined and derived attributes are dashed.", max_h=19.5 * cm)
P("2.2 Relationships and cardinalities", h2)
table([["Relationship", "Entities", "Cardinality", "Implemented by"],
       ["Works in", "EMPLOYEE - DEPARTMENT", "N : 1", "employees.dept_id FK"],
       ["Manages (recursive)", "EMPLOYEE - EMPLOYEE", "1 : N", "employees.manager_id FK (self-reference)"],
       ["Has", "EMPLOYEE - SALARY_STRUCTURE", "1 : N (history)", "salary_structure.emp_id FK, UNIQUE(emp_id, effective_from)"],
       ["Records", "EMPLOYEE - ATTENDANCE", "1 : N", "attendance.emp_id FK, UNIQUE(emp_id, att_date)"],
       ["Applies", "EMPLOYEE - LEAVE_REQUEST", "1 : N", "leave_requests.emp_id FK"],
       ["Of type", "LEAVE_REQUEST - LEAVE_TYPE", "N : 1", "leave_requests.leave_type_id FK"],
       ["Reviews", "EMPLOYEE (HR) - LEAVE_REQUEST", "1 : N", "leave_requests.reviewed_by FK"],
       ["Paid via", "EMPLOYEE - PAYROLL", "1 : N", "payroll.emp_id FK, UNIQUE(emp_id, pay_month)"],
       ["Logs in as", "EMPLOYEE - APP_USER", "1 : 1", "app_users.emp_id FK + UNIQUE"]],
      [3.3 * cm, 4.6 * cm, 2.4 * cm, W - 10.3 * cm])

P("2.3 Normalisation to 3NF", h2)
P("The starting point is the way payroll is often kept in practice: one wide <b>unnormalised register</b> with a row per "
  "employee per month, holding employee details, department, manager, salary figures and a repeating list of daily punches "
  "and leaves.")
codeblock("UNF: PayrollRegister(emp_id, emp_name, email, dept_name, dept_location, manager_name, designation,\n"
          "     basic, hra, special, month,\n"
          "     {att_date, check_in, check_out}*, {leave_from, leave_to, leave_type, leave_name, is_paid, quota}*,\n"
          "     gross, deductions, net)")
P("<b>First normal form (1NF): atomic values, no repeating groups.</b> The repeating daily punches and leave entries move "
  "to their own rows, and the name is split into first and last name. This gives Attendance(<u>emp_id, att_date</u>, "
  "check_in, check_out), LeaveEntry(<u>emp_id, from_date</u>, to_date, leave_code, leave_name, is_paid, annual_quota) and "
  "EmployeeMonth(<u>emp_id, month</u>, first_name, last_name, email, dept_name, dept_location, manager_name, basic, hra, special, ...).")
P("<b>Second normal form (2NF): no partial dependency on part of a composite key.</b> In EmployeeMonth, "
  "<font face='Courier'>emp_id -&gt; first_name, email, dept_name, designation</font> depends on only part of the key "
  "(emp_id, month), so employee facts move to EMPLOYEES. Salary figures do not depend on the month either; they depend on "
  "the employee and the date a revision took effect, so they become SALARY_STRUCTURE(<u>salary_id</u>, emp_id, basic, hra, "
  "special_allowance, effective_from). In LeaveEntry, <font face='Courier'>leave_code -&gt; leave_name, is_paid, annual_quota</font> "
  "is likewise moved to LEAVE_TYPES.")
P("<b>Third normal form (3NF): no transitive dependency on the key.</b> In EMPLOYEES, <font face='Courier'>emp_id -&gt; "
  "dept_name -&gt; dept_location</font> is transitive, so DEPARTMENTS(<u>dept_id</u>, dept_name, location) is created and "
  "employees keep only dept_id. The manager's name is not stored at all; manager_id references EMPLOYEES. Tax slab rates and "
  "policy values (shift time, OT rates, grace minutes) depend on their own keys, not on any employee or payroll row, so they "
  "live in TAX_SLABS and PAYROLL_POLICY instead of being repeated.")
P("<b>Result.</b> In every final table each non-key attribute depends on the key, the whole key and nothing but the key. "
  "Main functional dependencies:")
table([["Table", "Key", "Functional dependencies (determinant -&gt; attributes)"],
       ["departments", "dept_id", "dept_id -&gt; dept_name, location;  dept_name is also a candidate key"],
       ["employees", "emp_id", "emp_id -&gt; first_name, last_name, email, phone, gender, hire_date, dept_id, designation, manager_id, status; email is a candidate key"],
       ["salary_structure", "salary_id", "salary_id -&gt; emp_id, basic, hra, special_allowance, effective_from;  (emp_id, effective_from) is a candidate key"],
       ["attendance", "attendance_id", "attendance_id -&gt; emp_id, att_date, check_in, check_out;  (emp_id, att_date) is a candidate key"],
       ["leave_types", "leave_type_id", "leave_type_id -&gt; code, leave_name, is_paid, annual_quota;  code is a candidate key"],
       ["leave_requests", "leave_id", "leave_id -&gt; emp_id, leave_type_id, from_date, to_date, reason, status, reviewed_by, reviewed_on"],
       ["payroll", "payroll_id", "payroll_id -&gt; emp_id, pay_month, all monthly figures;  (emp_id, pay_month) is a candidate key"],
       ["app_users", "user_id", "user_id -&gt; emp_id, username, password_hash, salt, role;  emp_id and username are candidate keys"]],
      [3 * cm, 2.4 * cm, W - 5.4 * cm], font=8.2)
P("Since every determinant above is a candidate key, the core tables also satisfy BCNF. Two deliberate, documented "
  "exceptions are kept for correctness: (1) <font face='Courier'>attendance.worked_minutes</font> is a STORED generated "
  "column computed from check-in and check-out, so it can never disagree with them; (2) the PAYROLL table stores the computed "
  "monthly figures as a <b>historical snapshot</b>. A salary slip is a legal record and must not change when a salary or policy "
  "is revised later, so PAID rows are locked by triggers.")

P("2.4 Final relational schema", h2)
table([["Table", "Primary key", "Foreign keys", "Other constraints"],
       ["departments", "dept_id", "-", "UNIQUE dept_name"],
       ["employees", "emp_id (from 1001)", "dept_id -&gt; departments; manager_id -&gt; employees", "UNIQUE email; ENUM gender/status"],
       ["salary_structure", "salary_id", "emp_id -&gt; employees (CASCADE)", "UNIQUE(emp_id, effective_from); CHECK basic &gt; 0, allowances &gt;= 0"],
       ["payroll_policy", "policy_id", "-", "UNIQUE effective_from"],
       ["tax_slabs", "slab_id", "-", "CHECK upper &gt; lower"],
       ["holidays", "holiday_date", "-", "-"],
       ["calendar", "cal_date", "-", "filled by a recursive CTE"],
       ["attendance", "attendance_id", "emp_id -&gt; employees", "UNIQUE(emp_id, att_date); CHECK check_in on att_date; CHECK check_out &gt; check_in; generated worked_minutes"],
       ["leave_types", "leave_type_id", "-", "UNIQUE code"],
       ["leave_requests", "leave_id", "emp_id, reviewed_by -&gt; employees; leave_type_id -&gt; leave_types", "CHECK to_date &gt;= from_date; ENUM status"],
       ["payroll", "payroll_id", "emp_id -&gt; employees", "UNIQUE(emp_id, pay_month); CHECK pay_month is 1st; CHECK net &gt;= 0"],
       ["app_users", "user_id", "emp_id -&gt; employees", "UNIQUE emp_id, UNIQUE username; ENUM role"],
       ["audit_log", "log_id", "-", "written only by triggers"]],
      [2.9 * cm, 2.6 * cm, 5.4 * cm, W - 10.9 * cm], font=8)
story.append(KeepTogether([Paragraph("Excerpt of the DDL (attendance), showing PK, FK, UNIQUE, CHECK and a generated column:", body),
    Preformatted("""CREATE TABLE attendance (
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
);""", code)]))
story.append(Spacer(1, 10))

# ================================================================ 3 PHASE 2
P("3. Phase 2: Procedural implementation", h1)
P(f"The Phase 1 schema is created unchanged by <font face='Courier'>sql/01_schema.sql</font>. The database contains "
  f"<b>{counts['t']} tables, {counts['v']} views, {counts['f']} stored functions, {counts['p']} stored procedures and "
  f"{counts['tr']} triggers</b>. All rules live in the database; the interface only calls these objects.")
P("3.1 Organisational policy (payroll_policy table)", h2)
table([["Rule", "Value"],
       ["Shift", "09:30 start, 9 hours including a 1-hour break (540 minutes)"],
       ["Late mark", "check-in after 09:45 (15-minute grace); every 3 late marks = half-day deduction"],
       ["Full day / half day", "worked &gt;= 8 h / &gt;= 4 h; a missing check-out counts as a half day"],
       ["Weekday overtime", "time beyond 9 h, counted only if &gt;= 30 minutes, capped at 4 h/day, paid at 1.5x"],
       ["Weekend / holiday work", "every hour counts as overtime (up to one shift), paid at 2x"],
       ["Rates", "per day = fixed monthly pay / working days;  per hour = basic / (working days x 8)"],
       ["Provident fund", "12% of earned basic"],
       ["Income tax (TDS)", "simplified new-regime slabs; Rs 75,000 standard deduction; no tax up to Rs 12 lakh taxable "
                            "(with marginal relief); 4% cess; projected over 12 months"]],
      [4 * cm, W - 4 * cm])
P("3.2 Stored functions", h2)
table([["Function", "Purpose"],
       ["fn_working_days(year, month)", "working days in a month (calendar minus weekends and holidays)"],
       ["fn_is_working_day(date)", "TRUE for Monday-Friday dates that are not holidays"],
       ["fn_ot_minutes(date, worked)", "overtime minutes for one day: threshold, cap, weekend/holiday rule"],
       ["fn_annual_tax(taxable, date)", "slab-wise income tax with rebate, marginal relief and cess"],
       ["fn_monthly_tds(income, date)", "projects monthly taxable pay over a year and returns 1/12 of the tax"],
       ["fn_salary_id / fn_policy_id", "the salary revision / policy version in force on a given date"],
       ["fn_current_emp_id()", "employee linked to the connected MySQL account (row-level security)"]],
      [5.3 * cm, W - 5.3 * cm])
P("3.3 Stored procedures", h2)
table([["Procedure", "Purpose", "Transaction"],
       ["sp_add_employee", "creates employee + salary + login in one step", "COMMIT / ROLLBACK"],
       ["sp_update_salary", "salary revision (keeps history); validates values and paid months", "COMMIT / ROLLBACK"],
       ["sp_generate_payroll", "monthly payroll run for all active employees", "COMMIT / ROLLBACK"],
       ["sp_mark_payroll_paid", "locks a month as PAID (all rows or none)", "COMMIT / ROLLBACK"],
       ["sp_check_in / sp_check_out", "daily punches using server time, with validation", "single statement"],
       ["sp_apply_leave", "leave request with working-day count and balance check", "single statement"],
       ["sp_review_leave", "HR approval/rejection; blocks non-HR and self-approval", "single statement"],
       ["sp_upsert_attendance", "HR correction of a punch (e.g. missed check-out)", "single statement"],
       ["sp_salary_slip", "returns the slip for one employee and month", "read only"],
       ["sp_fill_calendar", "fills the calendar with a recursive CTE", "-"],
       ["sp_my_check_in / out / apply_leave", "self-service wrappers that act only on the caller's own record", "-"]],
      [4.6 * cm, 8.2 * cm, W - 12.8 * cm])
P("The payroll procedure computes every employee in a single INSERT ... SELECT built from chained CTEs inside one transaction:", body)
codeblock("""fixed pay      = basic + HRA + special allowance        (salary revision in force that month)
LOP days       = working days - present days - paid leave days
                 (covers absences, unpaid leave, half days and days before joining)
overtime pay   = hourly rate x (weekday OT hours x 1.5 + holiday OT hours x 2)
gross          = fixed pay + overtime pay
deductions     = LOP + late-mark deduction + PF (12% of earned basic) + TDS
net salary     = gross - deductions""")
P("3.4 Triggers", h2)
table([["Trigger", "Event", "Rule enforced"],
       ["trg_attendance_before_insert", "BEFORE INSERT attendance", "only active employees; not before joining; not a future date; not inside a PAID month"],
       ["trg_attendance_before_update", "BEFORE UPDATE attendance", "attendance in a PAID month cannot change"],
       ["trg_leave_before_insert", "BEFORE INSERT leave_requests", "rejects leave overlapping a pending or approved request"],
       ["trg_leave_after_update", "AFTER UPDATE leave_requests", "audit row for every approval or rejection"],
       ["trg_salary_after_insert / update", "AFTER INSERT/UPDATE salary_structure", "audit row for every revision"],
       ["trg_payroll_before_update / delete", "BEFORE UPDATE/DELETE payroll", "PAID payroll rows are locked"],
       ["trg_payroll_after_update", "AFTER UPDATE payroll", "audit row when a month is marked PAID"]],
      [4.9 * cm, 4.3 * cm, W - 9.2 * cm], font=8.2)
P("3.5 Sample data", h2)
P(f"<font face='Courier'>sql/06_seed_data.sql</font> (generated reproducibly by <font face='Courier'>tools/generate_seed.py</font>) "
  f"loads <b>{counts['emps']} employees in 5 departments</b> and <b>{counts['att']} attendance records</b> from "
  f"{counts['a_from']:%d %b %Y} to {counts['a_to']:%d %b %Y}, covering <b>three complete payroll months (August, September "
  f"and October 2026)</b>. It also has {counts['lv']} leave requests (approved, rejected, pending, paid and unpaid). The data "
  f"deliberately includes late arrivals, overtime, weekend and holiday work, half days, a missed punch, absences without leave, "
  f"a salary revision and a mid-month joiner, so every rule is exercised.")
table([["Month", "Working days", "Employees", "Gross (Rs)", "Overtime pay (Rs)", "Deductions (Rs)", "Net paid (Rs)", "Status"]] +
      [[m["month_label"], m["wd"], m["n"], money(m["g"]), money(m["ot"]), money(m["d"]), money(m["net"]), m["st"]] for m in months],
      [2.6 * cm, 1.7 * cm, 1.7 * cm, 2.3 * cm, 2.3 * cm, 2.2 * cm, 2.3 * cm, W - 15.1 * cm], font=8)
P("3.6 Worked example (verified by hand)", h2)
pd = float(rahul["basic"] + rahul["hra"] + rahul["special_allowance"]) / rahul["working_days"]
ph = float(rahul["basic"]) / (rahul["working_days"] * 8)
P(f"Rahul Verma, October 2026: salary revised from 1 Oct to basic {money(rahul['basic'])}, HRA {money(rahul['hra'])}, "
  f"special {money(rahul['special_allowance'])} (fixed pay {money(pd * rahul['working_days'])}). There were "
  f"{rahul['working_days']} working days.")
table([["Item", "Calculation", "Amount (Rs)"],
       ["Per-day rate", f"{money(pd * rahul['working_days'])} / {rahul['working_days']}", money(pd)],
       ["Overtime pay", f"{rahul['ot_hours_weekday']} weekday OT h x 1.5 x {money(ph)}/h", money(rahul["ot_pay"])],
       ["Loss of pay", f"{rahul['lop_days']} days (2 days unpaid leave) x {money(pd)}", money(rahul["lop_deduction"])],
       ["Late marks", f"{rahul['late_marks']} late marks -&gt; floor(4/3) = 1 x 0.5 day", money(rahul["late_deduction"])],
       ["PF", f"12% x {money(rahul['basic'])} x {rahul['working_days'] - float(rahul['lop_days']):g}/{rahul['working_days']} days", money(rahul["pf"])],
       ["TDS", "projected taxable income below Rs 12 lakh -&gt; rebate", money(rahul["tds"])],
       ["<b>Net salary</b>", f"{money(rahul['gross_earnings'])} gross - {money(rahul['total_deductions'])} deductions",
        f"<b>{money(rahul['net_salary'])}</b>"]],
      [3.2 * cm, 9.6 * cm, W - 12.8 * cm])
story.append(PageBreak())

# ================================================================ 4 PHASE 3
P("4. Phase 3: Query and report development", h1)
P("All reports are views built on one core view, <font face='Courier'>v_daily_attendance</font>. It produces one row per "
  "employee per calendar day (from joining date to today), joins attendance, approved leave, holidays and the policy in force, "
  "and classifies each day: PRESENT, HALF_DAY, MISSED_PUNCH, PAID_LEAVE, UNPAID_LEAVE, ABSENT, OFF or EXTRA_DAY. "
  "It also works out late marks, regular minutes and overtime. Building every report on this one view means the attendance "
  "report and the payroll can never disagree.")
P("4.1 Monthly attendance summary", h2)
codeblock("""SELECT da.emp_id, CONCAT(e.first_name,' ',e.last_name) AS employee_name, d.dept_name,
       CAST(DATE_FORMAT(da.cal_date,'%Y-%m-01') AS DATE) AS pay_month,
       SUM(da.day_type = 'WORKING') AS working_days_elapsed,  SUM(da.present_value) AS present_days,
       SUM(da.paid_leave_value) AS paid_leave_days,  SUM(da.absent_value) AS absent_days,
       SUM(da.is_late) AS late_marks,  ROUND(SUM(da.ot_weekday_minutes)/60, 2) AS ot_hours_weekday, ...
FROM v_daily_attendance da JOIN employees e ON e.emp_id = da.emp_id
JOIN departments d ON d.dept_id = e.dept_id
GROUP BY da.emp_id, employee_name, d.dept_name, pay_month;      -- view: v_monthly_attendance""")
shot("02_monthly_attendance", "Figure 2: Monthly attendance summary, October 2026 (HR menu option 7).")
P("4.2 Salary slip per employee", h2)
P("<font face='Courier'>v_salary_slip</font> joins payroll with employee and department; "
  "<font face='Courier'>sp_salary_slip(emp, year, month)</font> returns one slip, which the app formats and can save as a text file.")
shot("10_salary_slip", "Figure 3: Salary slip generated for Rahul Verma, October 2026 (employee menu option 6).", max_w=13 * cm)
P("4.3 Late-marks report", h2)
P("<font face='Courier'>v_late_marks</font> counts check-ins after shift start plus grace, and lists the dates and times with "
  "GROUP_CONCAT.")
shot("03_late_marks", "Figure 4: Late-marks report, October 2026.")
P("4.4 Additional reports", h2)
P("The overtime summary ranks employees with <font face='Courier'>RANK() OVER (PARTITION BY pay_month ...)</font> and shows "
  "each person's share of overtime pay with <font face='Courier'>SUM() OVER</font>. The payroll expenditure statement gives "
  "department-wise gross, overtime, PF, TDS and net pay, with each department's share of the company total. "
  "<font face='Courier'>sql/08_demo_queries.sql</font> holds 13 further queries: joins, GROUP BY/HAVING, correlated and "
  "non-correlated subqueries, EXISTS, UNION, LAG(), and a recursive CTE for the reporting chain.")
shot("04_overtime_summary", "Figure 5: Overtime summary with company ranking (window functions).")
shot("06_expenditure", "Figure 6: Payroll expenditure statement by department, October 2026.")
P("4.5 Indexing and execution-plan improvement", h2)
table([["Index", "Columns", "Used by"],
       ["idx_att_date", "attendance(att_date)", "late-marks and monthly attendance reports (date-range filters)"],
       ["uq_att_emp_date", "attendance(emp_id, att_date)", "daily view join; also prevents duplicate punches"],
       ["idx_pay_month", "payroll(pay_month)", "salary slip, overtime and expenditure reports"],
       ["idx_lv_emp_dates", "leave_requests(emp_id, from_date, to_date)", "leave overlap trigger and daily view join"],
       ["idx_emp_dept", "employees(dept_id)", "department-wise reports"]],
      [3.2 * cm, 5.6 * cm, W - 8.8 * cm])
P("<b>Experiment</b> (<font face='Courier'>sql/09_index_optimization.sql</font>), using the late-marks query, which filters "
  "attendance by a date range. The existing UNIQUE(emp_id, att_date) index starts with emp_id, so by the leftmost-prefix rule "
  "it cannot serve a filter on att_date alone. Before the index, MySQL had to read the whole index (type = index, 853 rows). "
  "After <font face='Courier'>CREATE INDEX idx_att_date</font> it performs a range scan of about 231 rows (type = range). "
  "To measure real time saved, the same query was run with EXPLAIN ANALYZE on a scaled copy of 365,000 rows "
  "(1,000 employees x 1 year):")
if len(times) == 3:
    story.append(Spacer(1, 0))
    table([["Stage", "Access path", "Total time", "Speed-up"],
           ["1. No date index", "full index scan of 365,000 rows", f"{times[0]:.0f} ms", "1x"],
           ["2. idx(att_date)", "index range scan (~31,000 rows)", f"{times[1]:.0f} ms", f"{times[0] / times[1]:.0f}x"],
           ["3. Covering index (att_date, emp_id, check_in)", "covering range scan: no table row reads",
            f"{times[2]:.0f} ms", f"{times[0] / times[2]:.0f}x"]],
          [5.4 * cm, 5.6 * cm, 2.6 * cm, W - 13.6 * cm], keep=True)
shot("14_index_explain", "Figure 7: EXPLAIN before/after on project data, and EXPLAIN ANALYZE timings on the scaled copy.")
story.append(PageBreak())

# ================================================================ 5 PHASE 4
P("5. Phase 4: Security, access control and testing", h1)
P("5.1 Role-based access control", h2)
P("Access is controlled at two independent layers, so a mistake in one does not expose data.")
table([["Layer", "HR / Admin", "Employee"],
       ["Application (Python CLI)", "HR menu: employees, salary, attendance corrections, leave approvals, payroll, all reports, audit log",
        "Self-service menu: check in/out, own attendance, apply leave, own leave balance, own salary slips"],
       ["Database (MySQL roles)", "role <b>payroll_hr</b>: SELECT/EXECUTE on everything; write access only to operational tables; audit log is read-only",
        "role <b>payroll_employee</b>: only the v_my_* views and sp_my_* procedures; no access to any base table"],
       ["App service account", "<b>payroll_app</b>: SELECT + EXECUTE only, so every change must go through a validated procedure", ""]],
      [3.6 * cm, 6.5 * cm, W - 10.1 * cm])
P("Employees are read-only on their own records. The <font face='Courier'>v_my_*</font> views are SQL SECURITY DEFINER "
  "and filter on <font face='Courier'>USER()</font>, the account actually connected, which gives row-level security in "
  "plain MySQL. Self check-in and leave application go through procedures that can only act on the caller's own employee ID. "
  "Passwords for the application are stored as salted SHA-256 hashes and every query is parameterised.")
codeblock("""CREATE OR REPLACE SQL SECURITY DEFINER VIEW v_my_payslips AS
SELECT * FROM v_salary_slip WHERE emp_id = fn_current_emp_id();     -- only the caller's rows

GRANT SELECT  ON payroll_db.v_my_payslips      TO 'payroll_employee';
GRANT EXECUTE ON PROCEDURE payroll_db.sp_my_check_in TO 'payroll_employee';
GRANT SELECT, EXECUTE ON payroll_db.* TO 'payroll_hr';""")
shot("13_db_access_control", "Figure 8: Employee account 'rahul' sees only his own slips; reading the payroll table, "
     "running payroll, or HR deleting the audit log are all denied.")
P("5.2 Transactions (COMMIT / ROLLBACK)", h2)
P("Every salary or payroll change is wrapped in a transaction with an EXIT HANDLER that rolls back and re-raises the error:")
codeblock("""DECLARE EXIT HANDLER FOR SQLEXCEPTION
BEGIN
    ROLLBACK;            -- undo everything done in this call
    RESIGNAL;            -- report the original error to the caller
END;
START TRANSACTION;
    DELETE FROM payroll WHERE pay_month = v_start AND status = 'PROCESSED';
    INSERT INTO payroll (...) WITH att AS (...), base AS (...), rates AS (...) SELECT ...;
COMMIT;""")
P("This applies to <font face='Courier'>sp_add_employee</font> (employee, salary and login rows), "
  "<font face='Courier'>sp_update_salary</font> (salary row and its audit row), <font face='Courier'>sp_generate_payroll</font> "
  "(every employee's row for the month) and <font face='Courier'>sp_mark_payroll_paid</font>. Test I13/I14 proves it: adding "
  "an employee with a duplicate email fails, and no partial salary or login row is left behind.")
P("5.3 Test cases and results", h2)
cats = {c: [r for r in test_rows if r[0][0] == c[0]] for c in ("Valid", "Invalid", "Boundary")}
P(f"<font face='Courier'>tests/run_tests.py</font> rebuilds the database, runs every case against the real system, writes "
  f"<font face='Courier'>tests/test_results.md</font>, then restores the demo data. Invalid cases pass only when the database "
  f"<i>rejects</i> the operation with the expected message. <b>Result: {tot.group(1)} of {tot.group(2)} test cases passed.</b>")
table([["Category", "What is covered", "Cases", "Passed"],
       ["Valid", "add employee, login, check-in/out, salary revision, leave apply/approve, payroll run, mark paid, reports",
        len(cats["Valid"]), sum(r[4] == "PASS" for r in cats["Valid"])],
       ["Invalid", "negative salary, duplicate attendance, double check-in, future/pre-joining dates, overlapping leave, "
                   "balance, unauthorised access, locked payroll, SQL injection, rollback",
        len(cats["Invalid"]), sum(r[4] == "PASS" for r in cats["Invalid"])],
       ["Boundary", "exactly 8 h / 4 h, 09:45:00 vs 09:45:01, 29 vs 30 min OT, OT caps, tax at Rs 12 lakh and marginal relief, "
                    "exact leave balance, mid-month joiner, year-end leave",
        len(cats["Boundary"]), sum(r[4] == "PASS" for r in cats["Boundary"])]],
      [2.2 * cm, 11.2 * cm, 1.6 * cm, W - 15 * cm])
rows = [["ID", "Test case", "Expected", "Actual result (from MySQL)", "Status"]]
for tid, desc, exp, act, st in test_rows:
    rows.append([tid, desc, exp.replace("->", "&#8594;"), act.replace("<", "&lt;").replace(">", "&gt;"), st])
table(rows, [1 * cm, 5.4 * cm, 3.6 * cm, 5.6 * cm, W - 15.6 * cm], font=7.2)
story.append(PageBreak())

# ================================================================ 6 PHASE 5
P("6. Phase 5: Integration and user interface", h1)
P("The interface is a Python command-line application that uses exactly the Phase 1-4 backend. It never computes salary or "
  "attendance itself. It logs the user in, shows the menu for their role, calls stored procedures and reads views. Database "
  "errors raised by SIGNAL appear as readable messages.")
img(ROOT / "docs" / "architecture.png", "Figure 9: System architecture: one connected application on one database.")
shot("01_login_hr_menu", "Figure 10: Login as HR Admin and the HR menu.", max_w=10.5 * cm)
shot("09_employee_menu", "Figure 11: The same app for an employee shows only self-service options.", max_w=10.5 * cm)
shot("05_generate_payroll", "Figure 12: HR generates the monthly payroll (stored procedure, one transaction).")
shot("11_leave_balance", "Figure 13: Employee view of own leave balance and request history.")
shot("12_error_handling", "Figure 14: Business rules enforced by the database appear as clear messages in the app.",
     max_w=11 * cm)
shot("08_audit_log", "Figure 15: Audit trail written by triggers, including the application user who made the change.")
story.append(PageBreak())

# ================================================================ 7 USE CASES / SCALING
P("7. Real-world use cases and scaling to a larger firm", h1)
P("7.1 Use cases", h2)
for t in ["<b>IT services and software companies</b> with shift-based work, project overtime and weekend deployments "
          "(the DevOps team in the sample data).",
          "<b>BPOs and support centres</b>, where late marks, half days and overtime directly change pay every month.",
          "<b>Hospitals, factories and retail chains</b>: the same model with different policy rows (shift times, OT rates).",
          "<b>Employee self-service</b>: staff check attendance, leave balance and slips themselves, which reduces HR queries.",
          "<b>Management reporting</b>: department-wise payroll cost and overtime trends support budgeting and staffing decisions."]:
    B(t)
P("7.2 Scaling from 12 to 10,000+ employees", h2)
P("A firm of 10,000 people generates about 2.5 million attendance rows a year. The design already prepares for this: rules are "
  "data rather than code, history is preserved, and reports read indexed date ranges. The following steps would take it further:")
table([["Area", "Approach"],
       ["Data volume", "Partition <font face='Courier'>attendance</font> by month (RANGE on att_date); archive closed years to history tables. "
                       "The Phase 3 experiment shows a covering index already cuts the late-marks query on 365,000 rows by about "
                       f"{(times[0] / times[2]) if len(times) == 3 else 48:.0f}x."],
       ["Attendance capture", "Feed punches from biometric or RFID devices and mobile apps into <font face='Courier'>sp_check_in</font>; "
                              "the validation triggers stay the same."],
       ["Payroll run", "Process by department or location in batches, each its own transaction; schedule with MySQL EVENTs; "
                       "store run logs."],
       ["Multiple locations / entities", "Add location and company tables; make <font face='Courier'>payroll_policy</font> and holidays "
                                         "location-specific (different states, shifts and holiday lists)."],
       ["Statutory rules", "Add tables for ESI, professional tax, gratuity and the old tax regime; extend the tax function with "
                           "declarations and investments."],
       ["Performance", "Read replicas for reports, connection pooling, caching monthly summaries in a summary table refreshed after "
                       "each payroll run."],
       ["Interface", "Replace the CLI with a web front end (for example Flask/Node REST API) calling the same procedures, so no "
                     "business logic is rewritten."],
       ["Security", "Single sign-on, password policy, encryption at rest for salary columns, and finer roles (manager approves own "
                    "team's leave, finance marks payroll paid)."]],
      [3.6 * cm, W - 3.6 * cm])

# ================================================================ 8 / 9
P("8. Limitations and future scope", h1)
for t in ["Tax and PF are simplified (no investment declarations, ESI or professional tax).",
          "Leave is in whole days; half-day leave and leave encashment are not modelled.",
          "One policy and holiday list for the whole company; multi-location rules are future work.",
          "The interface is a command-line app; a web or mobile front end and PDF salary slips are natural next steps.",
          "Night shifts crossing midnight are allowed by the schema (check_out is a DATETIME) but not specially handled in OT rules."]:
    B(t)
P("9. Conclusion", h1)
P("The project delivers a complete, connected payroll and attendance system. A 3NF schema designed in Phase 1 is implemented "
  "unchanged in Phase 2 with procedures, functions and triggers that encode the organisation's rules. Phase 3 reports and "
  "indexes are built on that data, with a measured speed-up. Phase 4 adds two-layer role-based security and transactional "
  f"safety, verified by {tot.group(2)} automated test cases that all pass. Phase 5 places a role-based interface on the same "
  "backend. Keeping the business logic inside the database makes results consistent for every user and client, and makes the "
  "system straightforward to extend to a larger organisation.")

# ================================================================ APPENDIX
P("Appendix: project files and how to run", h1)
table([["File", "Contents"],
       ["setup.sh", "builds payroll_db from files 01-07 in order"],
       ["sql/01_schema.sql", "tables, keys, constraints, indexes"],
       ["sql/02_functions.sql", "working days, overtime, income tax, TDS, lookups"],
       ["sql/03_views.sql", "core daily view and all report views"],
       ["sql/04_procedures.sql", "business procedures and payroll run"],
       ["sql/05_triggers.sql", "validation and audit triggers"],
       ["sql/06_seed_data.sql", "12 employees, Aug-Nov 2026 data, payroll"],
       ["sql/07_security.sql", "roles, users, self-service views"],
       ["sql/08_demo_queries.sql", "13 demonstration queries"],
       ["sql/09_index_optimization.sql", "execution plan before/after experiment"],
       ["app/payroll_app.py", "role-based command-line interface"],
       ["tests/run_tests.py, tests/test_results.md", "automated test suite and documented results"],
       ["docs/", "ER diagram, architecture, screenshots, output traces, this report"]],
      [5.6 * cm, W - 5.6 * cm])
codeblock("""brew services start mysql
pip3 install mysql-connector-python
./setup.sh                      # Enter the MySQL root password (or press Enter if none)
python3 app/payroll_app.py      # HR: neha / hr@1234     Employee: rahul / emp@1234
python3 tests/run_tests.py      # runs all test cases and rewrites tests/test_results.md""")
P(f'Source code: <link href="{GITHUB}" color="blue">{GITHUB}</link>')


# ---------------------------------------------------------------- page decorations
def decorate(canvas, doc):
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(2 * cm, 1.2 * cm, "Overtime-Based Payroll and Attendance Management System | Shivom Sood (2501730435)")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#c5ccd6"))
    canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
    canvas.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                        bottomMargin=2 * cm, title="Overtime-Based Payroll and Attendance Management System",
                        author="Shivom Sood (2501730435)", subject="DBMS Capstone Project Report")
doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
print("Wrote", OUT)
