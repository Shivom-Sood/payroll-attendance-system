"""
Generates sql/06_seed_data.sql: master data, employees, leave history and
realistic attendance (late arrivals, overtime, weekend work, half days,
a missed punch) from 1 Aug 2026 to 19 Nov 2026 (three full payroll months).

Run:  python3 tools/generate_seed.py
The output is deterministic (fixed random seed), so the file is reproducible.
"""
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

random.seed(2026)

START = date(2026, 8, 1)
END = date(2026, 11, 19)
HOLIDAYS = {
    date(2026, 1, 26): "Republic Day",
    date(2026, 8, 15): "Independence Day",
    date(2026, 10, 2): "Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 9): "Diwali (Govardhan Puja)",
    date(2026, 12, 25): "Christmas",
}

# (first, last, email-user, phone, gender, hire, dept, designation, manager,
#  basic, hra, special, username, role)
EMPLOYEES = [
    ("Neha", "Kapoor", "neha.kapoor", "9810000001", "F", "2023-04-03", 4, "HR Manager", None, 60000, 24000, 16000, "neha", "HR_ADMIN"),
    ("Arjun", "Mehta", "arjun.mehta", "9810000002", "M", "2022-07-11", 1, "Engineering Manager", None, 90000, 36000, 34000, "arjun", "EMPLOYEE"),
    ("Priya", "Sharma", "priya.sharma", "9810000003", "F", "2023-01-16", 1, "Senior Software Engineer", 1002, 65000, 26000, 19000, "priya", "EMPLOYEE"),
    ("Rahul", "Verma", "rahul.verma", "9810000004", "M", "2024-06-03", 1, "Software Engineer", 1002, 45000, 18000, 12000, "rahul", "EMPLOYEE"),
    ("Ananya", "Iyer", "ananya.iyer", "9810000005", "F", "2025-07-14", 1, "Software Engineer", 1003, 42000, 16800, 11200, "ananya", "EMPLOYEE"),
    ("Karan", "Malhotra", "karan.malhotra", "9810000006", "M", "2023-09-04", 2, "QA Lead", 1002, 55000, 22000, 13000, "karan", "EMPLOYEE"),
    ("Sneha", "Reddy", "sneha.reddy", "9810000007", "F", "2024-11-18", 2, "QA Engineer", 1006, 38000, 15200, 9800, "sneha", "EMPLOYEE"),
    ("Vikram", "Singh", "vikram.singh", "9810000008", "M", "2023-03-20", 3, "DevOps Engineer", 1002, 60000, 24000, 16000, "vikram", "EMPLOYEE"),
    ("Rohan", "Gupta", "rohan.gupta", "9810000009", "M", "2025-02-10", 3, "Site Reliability Engineer", 1008, 50000, 20000, 10000, "rohan", "EMPLOYEE"),
    ("Kavya", "Nair", "kavya.nair", "9810000010", "F", "2024-01-08", 5, "Finance Executive", 1001, 40000, 16000, 9000, "kavya", "EMPLOYEE"),
    ("Aditya", "Joshi", "aditya.joshi", "9810000011", "M", "2025-03-03", 4, "HR Executive", 1001, 35000, 14000, 8000, "aditya", "HR_ADMIN"),
    ("Isha", "Bansal", "isha.bansal", "9810000012", "F", "2026-10-12", 1, "Junior Software Engineer", 1003, 32000, 12800, 7200, "isha", "EMPLOYEE"),
]

# Behaviour profile per employee id: probability of late arrival, of overtime,
# and weekend days worked (list of dates)
PROFILE = {
    1001: (0.05, 0.05), 1002: (0.05, 0.12), 1003: (0.06, 0.18), 1004: (0.22, 0.06),
    1005: (0.08, 0.08), 1006: (0.05, 0.10), 1007: (0.10, 0.05), 1008: (0.07, 0.32),
    1009: (0.10, 0.22), 1010: (0.04, 0.03), 1011: (0.06, 0.04), 1012: (0.12, 0.05),
}
WEEKEND_WORK = {   # emp_id: [(date, minutes)]  (includes work on a holiday)
    1008: [(date(2026, 8, 8), 300), (date(2026, 8, 22), 360), (date(2026, 9, 12), 330), (date(2026, 9, 26), 300), (date(2026, 10, 2), 360),
           (date(2026, 10, 17), 300), (date(2026, 10, 31), 420), (date(2026, 11, 14), 300)],
    1009: [(date(2026, 8, 29), 330), (date(2026, 9, 19), 300), (date(2026, 10, 24), 360), (date(2026, 11, 7), 240)],
    1003: [(date(2026, 10, 10), 270)],
}

# (emp, code, from, to, reason, status, reviewer, applied_on)
LEAVES = [
    (1010, "SL", "2026-08-11", "2026-08-12", "Migraine", "APPROVED", 1001, "2026-08-11 08:20:00"),
    (1002, "CL", "2026-08-21", "2026-08-21", "School admission of son", "APPROVED", 1001, "2026-08-17 10:00:00"),
    (1008, "EL", "2026-08-24", "2026-08-26", "Trip to Manali", "APPROVED", 1001, "2026-08-03 15:30:00"),
    (1007, "CL", "2026-08-27", "2026-08-27", "Personal work", "REJECTED", 1001, "2026-08-26 19:10:00"),
    (1003, "CL", "2026-09-14", "2026-09-15", "Family function in Jaipur", "APPROVED", 1001, "2026-09-07 10:12:00"),
    (1010, "CL", "2026-09-25", "2026-09-25", "Personal work", "APPROVED", 1001, "2026-09-22 11:40:00"),
    (1005, "CL", "2026-09-28", "2026-09-28", "Short trip", "REJECTED", 1001, "2026-09-26 18:05:00"),
    (1004, "SL", "2026-10-07", "2026-10-07", "Fever", "APPROVED", 1011, "2026-10-07 08:30:00"),
    (1001, "CL", "2026-10-16", "2026-10-16", "Bank work", "APPROVED", 1011, "2026-10-12 09:55:00"),
    (1006, "EL", "2026-10-21", "2026-10-23", "Dussehra vacation", "APPROVED", 1001, "2026-10-05 14:20:00"),
    (1004, "LWP", "2026-10-26", "2026-10-27", "Personal emergency", "APPROVED", 1001, "2026-10-25 21:10:00"),
    (1005, "SL", "2026-11-04", "2026-11-05", "Viral infection", "APPROVED", 1011, "2026-11-04 08:05:00"),
    (1007, "CL", "2026-11-20", "2026-11-20", "Sister's wedding prep", "PENDING", None, "2026-11-16 12:30:00"),
    (1009, "EL", "2026-11-23", "2026-11-27", "Year-end vacation", "PENDING", None, "2026-11-17 16:45:00"),
]

ABSENT_NO_LEAVE = {(1009, date(2026, 8, 18)), (1004, date(2026, 8, 31)), (1009, date(2026, 9, 8)), (1005, date(2026, 10, 13)), (1012, date(2026, 11, 3))}
HALF_DAYS = {(1003, date(2026, 8, 14)): 270, (1010, date(2026, 10, 9)): 300, (1007, date(2026, 9, 30)): 290}
MISSED_PUNCH = {(1007, date(2026, 10, 15)), (1005, date(2026, 8, 20))}  # checked in, never checked out


def is_working(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def on_approved_leave(emp, d):
    for e, _code, f, t, _reason, status, _rev, _applied in LEAVES:
        if e == emp and status == "APPROVED" and date.fromisoformat(f) <= d <= date.fromisoformat(t):
            return True
    return False


def sql_str(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def attendance_rows():
    rows = []
    for idx, emp in enumerate(EMPLOYEES):
        emp_id = 1001 + idx
        hire = date.fromisoformat(emp[5])
        p_late, p_ot = PROFILE[emp_id]
        d = max(START, hire)
        while d <= END:
            if is_working(d) and not on_approved_leave(emp_id, d) and (emp_id, d) not in ABSENT_NO_LEAVE:
                if random.random() < p_late:
                    cin = datetime.combine(d, time(9, 46)) + timedelta(minutes=random.randint(0, 40))
                else:
                    cin = datetime.combine(d, time(9, 5)) + timedelta(minutes=random.randint(0, 38))
                cin = cin.replace(second=random.randint(0, 59))

                if (emp_id, d) in MISSED_PUNCH:
                    rows.append((emp_id, d, fmt(cin), None))
                else:
                    if (emp_id, d) in HALF_DAYS:
                        worked = HALF_DAYS[(emp_id, d)]
                    elif random.random() < p_ot:
                        worked = 540 + random.randint(45, 200)
                    else:
                        worked = 540 + random.randint(-20, 22)
                    cout = cin + timedelta(minutes=worked, seconds=random.randint(0, 59))
                    rows.append((emp_id, d, fmt(cin), fmt(cout)))
            d += timedelta(days=1)

        for wd, minutes in WEEKEND_WORK.get(emp_id, []):
            cin = datetime.combine(wd, time(10, 0)) + timedelta(minutes=random.randint(0, 30))
            rows.append((emp_id, wd, fmt(cin), fmt(cin + timedelta(minutes=minutes))))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def main():
    out = []
    w = out.append
    w("-- =====================================================================")
    w("--  File 06: Sample data (generated by tools/generate_seed.py)")
    w("--  Attendance: 1 Aug 2026 - 19 Nov 2026 | Payroll: Aug + Sep (PAID), Oct (PROCESSED)")
    w("--  Demo logins:  HR -> neha / hr@1234   |  Employee -> rahul / emp@1234")
    w("--  (every employee's password is emp@1234; HR admins use hr@1234)")
    w("-- =====================================================================")
    w("USE payroll_db;\n")

    w("INSERT INTO departments (dept_name, location) VALUES")
    w("  ('Engineering','Gurugram'), ('Quality Assurance','Gurugram'), ('DevOps','Gurugram'),")
    w("  ('Human Resources','Gurugram'), ('Finance','Gurugram');\n")

    w("-- Organisational policy (defaults defined in the table)")
    w("INSERT INTO payroll_policy (effective_from) VALUES ('2026-01-01');\n")

    w("-- Simplified new-regime income-tax slabs (annual taxable income)")
    w("INSERT INTO tax_slabs (lower_limit, upper_limit, rate) VALUES")
    w("  (0, 400000, 0.000), (400000, 800000, 0.050), (800000, 1200000, 0.100),")
    w("  (1200000, 1600000, 0.150), (1600000, 2000000, 0.200), (2000000, 2400000, 0.250),")
    w("  (2400000, NULL, 0.300);\n")

    w("INSERT INTO holidays (holiday_date, holiday_name) VALUES")
    w(",\n".join(f"  ('{d}', {sql_str(n)})" for d, n in sorted(HOLIDAYS.items())) + ";\n")

    w("INSERT INTO leave_types (code, leave_name, is_paid, annual_quota) VALUES")
    w("  ('CL','Casual Leave',TRUE,12), ('SL','Sick Leave',TRUE,10),")
    w("  ('EL','Earned Leave',TRUE,15), ('LWP','Leave Without Pay',FALSE,NULL);\n")

    w("CALL sp_fill_calendar('2026-01-01', '2027-12-31');\n")

    w("-- Employees: each CALL inserts employee + salary + login in one transaction")
    for e in EMPLOYEES:
        first, last, mail, phone, g, hire, dept, desig, mgr, basic, hra, sp, user, role = e
        pwd = "hr@1234" if role == "HR_ADMIN" else "emp@1234"
        w(f"CALL sp_add_employee({sql_str(first)}, {sql_str(last)}, '{mail}@techsphere.in', '{phone}', '{g}', "
          f"'{hire}', {dept}, {sql_str(desig)}, {sql_str(mgr)}, {basic}, {hra}, {sp}, '{user}', '{pwd}', '{role}', @id);")
    w("")

    w("-- Salary revision for Rahul from October (shows history + audit trigger)")
    w("CALL sp_update_salary(1004, 48000, 19200, 12800, '2026-10-01');\n")

    w("-- Leave history")
    w("INSERT INTO leave_requests (emp_id, leave_type_id, from_date, to_date, reason, status, applied_on, reviewed_by, reviewed_on) VALUES")
    lrows = []
    for emp, code, f, t, reason, status, rev, applied in LEAVES:
        reviewed_on = "NULL" if rev is None else f"'{applied[:10]} 18:00:00'"
        lrows.append(
            f"  ({emp}, (SELECT leave_type_id FROM leave_types WHERE code='{code}'), '{f}', '{t}', "
            f"{sql_str(reason)}, '{status}', '{applied}', {sql_str(rev)}, {reviewed_on})")
    w(",\n".join(lrows) + ";\n")

    rows = attendance_rows()
    w(f"-- Attendance ({len(rows)} records)")
    for i in range(0, len(rows), 200):
        chunk = rows[i:i + 200]
        w("INSERT INTO attendance (emp_id, att_date, check_in, check_out) VALUES")
        w(",\n".join(f"  ({r[0]}, '{r[1]}', '{r[2]}', {sql_str(r[3])})" for r in chunk) + ";")
    w("")

    w("-- Process payroll: August and September are paid and locked, October is processed")
    w("CALL sp_generate_payroll(2026, 8);")
    w("CALL sp_mark_payroll_paid(2026, 8);")
    w("CALL sp_generate_payroll(2026, 9);")
    w("CALL sp_mark_payroll_paid(2026, 9);")
    w("CALL sp_generate_payroll(2026, 10);")

    path = Path(__file__).resolve().parent.parent / "sql" / "06_seed_data.sql"
    path.write_text("\n".join(out) + "\n")
    print(f"Wrote {path} with {len(rows)} attendance rows")


if __name__ == "__main__":
    main()
