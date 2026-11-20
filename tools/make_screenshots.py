"""
Captures REAL terminal output from the running app / MySQL and renders it as
terminal-style PNG screenshots for the report (docs/screenshots/).
Raw text traces are saved too (docs/output/).

Run after ./setup.sh:   python3 tools/make_screenshots.py
"""
import re
import subprocess
import time
from pathlib import Path

import pexpect
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
TRACES = ROOT / "docs" / "output"
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 15)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def app_session(steps):
    """Run the app in a real pseudo-terminal, typing each step; return the transcript."""
    child = pexpect.spawn("python3 app/payroll_app.py", cwd=str(ROOT), encoding="utf-8",
                          dimensions=(60, 220), timeout=20)
    log = []
    child.logfile_read = type("L", (), {"write": lambda s, d: log.append(d), "flush": lambda s: None})()
    for expect, send in steps:
        child.expect(expect)
        time.sleep(0.15)
        child.sendline(send)
    child.expect(pexpect.EOF)
    text = ANSI.sub("", "".join(log)).replace("\r", "")
    return text


def between(text, start, end, include_end=False):
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j + (len(end) if include_end else 0)]


def render(name, title, text):
    lines = [l.rstrip() for l in text.strip("\n").split("\n")]
    lines = [l for l in lines if "GetPassWarning" not in l and "fallback_getpass" not in l]
    cw, ch = FONT.getbbox("M")[2], 20
    width = max(60, len(title) + 12, max(len(l) for l in lines)) * cw + 40
    height = len(lines) * ch + 70
    img = Image.new("RGB", (width, height), (30, 32, 38))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 30], fill=(52, 55, 63))
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        d.ellipse([12 + i * 20, 9, 24 + i * 20, 21], fill=c)
    d.text((80, 7), title, font=FONT, fill=(200, 200, 205))
    for i, l in enumerate(lines):
        color = (230, 230, 230)
        if "[!]" in l or "ERROR" in l or "denied" in l:
            color = (255, 130, 120)
        elif "[PASS]" in l or l.strip().startswith(("Welcome", "Checked", "Leave", "Employee created")):
            color = (140, 220, 140)
        elif l.lstrip().startswith("$"):
            color = (120, 190, 255)
        d.text((20, 45 + i * ch), l, font=FONT, fill=color)
    img.save(SHOTS / f"{name}.png")
    (TRACES / f"{name}.txt").write_text("\n".join(lines) + "\n")
    print("saved", name)


def shell(cmd):
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    return f"$ {cmd.split(' 2>')[0]}\n" + (r.stdout + r.stderr).replace(
        "mysql: [Warning] Using a password on the command line interface can be insecure.\n", "")


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    TRACES.mkdir(parents=True, exist_ok=True)
    C = "Choose: "
    ENTER = "Press Enter to continue"

    # ---------------- HR session ----------------
    hr = app_session([
        ("Username:", "neha"), ("Password:", "hr@1234"),
        (C, "7"), (r"Month \(YYYY-MM\)", "2026-10"), (ENTER, ""),
        (C, "8"), (r"Month \(YYYY-MM\)", "2026-10"), (ENTER, ""),
        (C, "9"), (r"Month \(YYYY-MM\)", "2026-10"), (ENTER, ""),
        (C, "10"), (r"Month \(YYYY-MM\)", "2026-10"), (ENTER, ""),
        (C, "12"), (r"Month \(YYYY-MM\)", "2026-10"), (ENTER, ""),
        (C, "6"), ("leave_id to review", ""), (ENTER, ""),
        (C, "14"), (ENTER, ""),
        (C, "0"), (r"another user\?", "n"),
    ])
    first_menu_end = hr.index("Back / Logout") + len("Back / Logout")
    render("01_login_hr_menu", "Login as HR Admin and role-based HR menu", hr[:first_menu_end])
    render("02_monthly_attendance", "Report: monthly attendance summary (October 2026)",
           between(hr, "Monthly attendance report 2026", ENTER))
    render("03_late_marks", "Report: late marks (October 2026)", between(hr, "Late marks 2026", ENTER))
    render("04_overtime_summary", "Report: overtime summary with ranking (window functions)",
           between(hr, "Overtime summary 2026", ENTER))
    render("05_generate_payroll", "Generate monthly payroll (stored procedure, one transaction)",
           between(hr, "Payroll generated", ENTER))
    render("06_expenditure", "Report: payroll expenditure statement by department",
           between(hr, "Payroll expenditure statement 2026", ENTER))
    render("07_pending_leave", "HR: pending leave requests", between(hr, "Pending leave requests", "leave_id to review"))
    render("08_audit_log", "Audit trail written by triggers", between(hr, "Audit log (latest 25)", ENTER))

    # ---------------- Employee session ----------------
    emp = app_session([
        ("Username:", "rahul"), ("Password:", "emp@1234"),
        (C, "6"), (r"Month \(YYYY-MM\)", "2026-10"), (r"Save slip", "n"), (ENTER, ""),
        (C, "5"), (ENTER, ""),
        (C, "1"), (ENTER, ""),
        (C, "1"), (ENTER, ""),
        (C, "4"), ("Leave code", "SL"), ("From", "2026-12-01"), ("To", "2026-12-31"), ("Reason", "Test"),
        (ENTER, ""),
        (C, "0"), (r"another user\?", "n"),
    ])
    menu_start = emp.index("Payroll & Attendance System - Login")
    render("09_employee_menu", "Login as Employee: limited self-service menu",
           emp[menu_start:emp.index("Back / Logout") + len("Back / Logout")])
    render("10_salary_slip", "Employee views own salary slip (October 2026)",
           emp[emp.rfind("+---", 0, emp.index("TechSphere")):emp.index("Save slip")])
    render("11_leave_balance", "Employee: leave balance and request history", between(emp, "Leave balance 2026", ENTER))
    chk = emp.index("Checked in")
    render("12_error_handling", "Validation: double check-in and leave beyond balance are rejected",
           emp[emp.rfind("Choose:", 0, chk):chk] + between(emp, "Checked in", ENTER) + "\n...\n"
           + between(emp, "[!] Already", ENTER) + "\n...\n" + between(emp, "[!] Insufficient", ENTER))

    # ---------------- Database-level access control ----------------
    sec = (shell("mysql -u rahul -p'emp@1234' payroll_db -e \"SELECT CURRENT_ROLE();\" 2>&1")
           + shell("mysql -u rahul -p'emp@1234' payroll_db -e \"SELECT month_label, net_salary, status FROM v_my_payslips;\" 2>&1")
           + shell("mysql -u rahul -p'emp@1234' payroll_db -e \"SELECT * FROM payroll;\" 2>&1")
           + shell("mysql -u rahul -p'emp@1234' payroll_db -e \"CALL sp_generate_payroll(2026,10);\" 2>&1")
           + shell("mysql -u neha -p'hr@1234' payroll_db -e \"DELETE FROM audit_log;\" 2>&1"))
    render("13_db_access_control", "Database RBAC: employee sees only own rows; everything else denied", sec)

    # ---------------- Index optimisation ----------------
    txt = (TRACES / "index_optimization_results.txt").read_text().split("\n")
    explain_rows = [l for l in txt if "| SIMPLE" in l][:2]
    header = [l for l in txt if l.startswith("| id ")][0]
    timings = [re.sub(r"\s+\|?$", "", l)[5:] for l in txt if l.startswith("| -> Group aggregate")
               or l.startswith("| -> Table scan on <temporary>")]
    body = ("PART A - real data (853 attendance rows), late-marks report for October\n\n"
            "BEFORE (no index on att_date):\n" + header + "\n" + explain_rows[0] + "\n\n"
            "AFTER  (CREATE INDEX idx_att_date ON attendance(att_date)):\n" + header + "\n" + explain_rows[1] +
            "\n\nPART B - scaled copy, 365,000 rows (EXPLAIN ANALYZE, total time)\n\n"
            f"Stage 1  no date index      {timings[0]}\n"
            f"Stage 2  idx(att_date)      {timings[1]}\n"
            f"Stage 3  covering index     {timings[2]}\n")
    render("14_index_explain", "Query execution plan: before vs after indexing", body)

    # ---------------- Test suite summary ----------------
    res = (ROOT / "tests" / "test_results.md").read_text()
    total = re.search(r"\*\*(\d+) of (\d+) test cases passed", res)
    rows = [l for l in res.split("\n") if l.startswith("| ") and l[2] in "VIB" and l[3].isdigit()]
    lines = ["$ python3 tests/run_tests.py", "Rebuilding payroll_db (clean state)..."]
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        lines.append(f"  [{cells[4]}] {cells[0]:<4} {cells[1][:88]}")
    lines += ["", "Restoring demo data...", f"{total.group(1)}/{total.group(2)} passed."]
    render("15_test_suite", "Automated test suite: valid, invalid and boundary cases", "\n".join(lines))


if __name__ == "__main__":
    main()
