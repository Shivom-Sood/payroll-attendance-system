# Test Results: Overtime-Based Payroll and Attendance Management System

Run on 20 Nov 2026 22:16 against a freshly rebuilt `payroll_db`. **57 of 57 test cases passed.**

Each case states the expected behaviour and the actual response from MySQL. Invalid cases pass when the database *rejects* the operation with the expected message.

## Valid cases (10/10 passed)

| ID | Test case | Expected | Actual result | Status |
|---|---|---|---|---|
| V01 | HR adds a new employee (employee + salary + login in one transaction) | Succeeds; 1 | Succeeded; 1 | PASS |
| V02 | Login with the correct password (salted SHA-256 matches) | Hash matches | Hash matches | PASS |
| V03 | Employee checks in today | Succeeds; 1 | Succeeded; 1 | PASS |
| V04 | Employee checks out after checking in | Succeeds; 1 | Succeeded; 1 | PASS |
| V05 | HR revises salary (new history row, audit row written) | Succeeds; 2 | Succeeded; 2 | PASS |
| V06 | Employee applies for 2 days of casual leave | Succeeds; PENDING | Succeeded; PENDING | PASS |
| V07 | HR approves the leave (audit row written) | Succeeds; 1 | Succeeded; 1 | PASS |
| V08 | Re-run October payroll (transaction replaces PROCESSED rows) | Succeeds; 12 | Succeeded; 12 | PASS |
| V09 | Mark October payroll as PAID (all rows in one transaction) | Succeeds; 12 | Succeeded; 12 | PASS |
| V10 | Reports return data: monthly attendance rows for Oct 2026 | 12 | 12 | PASS |

## Invalid cases (27/27 passed)

| ID | Test case | Expected | Actual result | Status |
|---|---|---|---|---|
| I01 | Negative basic salary via procedure | Rejected: Basic must be positive | Rejected: Basic must be positive and allowances cannot be negative | PASS |
| I02 | Negative salary inserted directly into the table (CHECK constraint) | Rejected: chk_sal_positive | Rejected: Check constraint 'chk_sal_positive' is violated. | PASS |
| I03 | Duplicate attendance entry (same employee, same date) | Rejected: Duplicate entry | Rejected: Duplicate entry '1003-2026-11-02' for key 'attendance.uq_att_emp_date' | PASS |
| I04 | Checking in twice on the same day | Rejected: Already checked in today | Rejected: Already checked in today | PASS |
| I05 | Check-out time earlier than check-in | Rejected: chk_att_order | Rejected: Check constraint 'chk_att_order' is violated. | PASS |
| I06 | Attendance for a future date | Rejected: future date | Rejected: Attendance cannot be recorded for a future date | PASS |
| I07 | Attendance before the joining date | Rejected: before the joining date | Rejected: Attendance date is before the joining date | PASS |
| I08 | Leave overlapping an approved leave (trigger) | Rejected: overlaps | Rejected: Leave overlaps an existing pending or approved request | PASS |
| I09 | Leave longer than the remaining balance | Rejected: Insufficient leave balance | Rejected: Insufficient leave balance for this leave type | PASS |
| I10 | Leave on dates with no working days (weekend) | Rejected: no working days | Rejected: Selected dates contain no working days | PASS |
| I11 | Non-HR employee tries to approve a leave | Rejected: Only HR admins | Rejected: Only HR admins can review leave | PASS |
| I12 | HR admin tries to approve their own leave | Rejected: cannot review your own | Rejected: You cannot review your own leave | PASS |
| I13 | Add employee with a duplicate email | Rejected: Duplicate entry | Rejected: Duplicate entry 'neha.kapoor@techsphere.in' for key 'employees.email' | PASS |
| I14 | ...and the failed add leaves no partial rows (ROLLBACK) | Salary rows unchanged | before=15, after=15 | PASS |
| I15 | Modify a PAID payroll record | Rejected: locked | Rejected: Paid payroll records are locked | PASS |
| I16 | Delete a PAID payroll month | Rejected: locked | Rejected: Paid payroll records are locked | PASS |
| I17 | Change attendance inside a PAID month | Rejected: attendance is locked | Rejected: That month is already paid; attendance is locked | PASS |
| I18 | Generate payroll for a month that has not ended | Rejected: after the month has ended | Rejected: Payroll can only be generated after the month has ended | PASS |
| I19 | Regenerate an already PAID month | Rejected: already PAID | Rejected: Payroll for this month is already PAID and locked | PASS |
| I20 | Back-date a salary revision into a paid month | Rejected: already paid month | Rejected: Cannot back-date a revision into an already paid month | PASS |
| I21 | Unauthorized: employee 'rahul' reads the payroll table | Rejected: SELECT command denied | Rejected: SELECT command denied to user 'rahul'@'localhost' for table 'payroll' | PASS |
| I22 | Unauthorized: employee 'rahul' runs the payroll procedure | Rejected: execute command denied | Rejected: execute command denied to user 'rahul'@'localhost' for routine 'payroll_db.sp_generate_payroll' | PASS |
| I23 | Unauthorized: app account edits a table directly (bypassing procedures) | Rejected: UPDATE command denied | Rejected: UPDATE command denied to user 'payroll_app'@'localhost' for table 'employees' | PASS |
| I24 | Unauthorized: HR tries to erase the audit log | Rejected: DELETE command denied | Rejected: DELETE command denied to user 'neha'@'localhost' for table 'audit_log' | PASS |
| I25 | Employee self-service view shows only their own slips | 1 | 1 | PASS |
| I26 | Login with a wrong password is refused | Hash mismatch | Hash mismatch | PASS |
| I27 | SQL-injection username (' OR '1'='1) finds no user (parameterised query) | 0 | 0 | PASS |

## Boundary cases (20/20 passed)

| ID | Test case | Expected | Actual result | Status |
|---|---|---|---|---|
| B01 | Worked exactly 8h00m (480 min) -> full day | PRESENT | PRESENT | PASS |
| B02 | Worked 7h59m (479 min) -> half day | HALF_DAY | HALF_DAY | PASS |
| B03 | Worked exactly 4h00m (240 min) -> half day | HALF_DAY | HALF_DAY | PASS |
| B04 | Worked 3h59m (239 min) -> counted absent | ABSENT | ABSENT | PASS |
| B05 | Check-in at exactly 09:45:00 (end of grace) -> not late | 0 | 0 | PASS |
| B06 | Check-in at 09:45:01 -> late mark | 1 | 1 | PASS |
| B07 | Weekday: 29 min beyond the 9h shift -> no overtime | 0 | 0 | PASS |
| B08 | Weekday: exactly 30 min beyond the shift -> 30 min OT | 30 | 30 | PASS |
| B09 | Weekday: 6h beyond the shift -> capped at 240 min | 240 | 240 | PASS |
| B10 | Weekend: 10h worked -> OT capped at one shift (540) | 540 | 540 | PASS |
| B11 | Holiday (Diwali 9 Nov): 5h worked -> all 300 min are OT | 300 | 300 | PASS |
| B12 | Taxable income exactly Rs 12,00,000 -> zero tax (rebate) | 0.0 | 0.0 | PASS |
| B13 | Taxable Rs 12,10,000 -> marginal relief caps tax at Rs 10,000 + cess | 10400.0 | 10400.0 | PASS |
| B14 | Taxable Rs 16,00,000 -> slab tax Rs 1,20,000 + 4% cess | 124800.0 | 124800.0 | PASS |
| B15 | Leave request using exactly the remaining EL balance (15 days) | Succeeds; 1 | Succeeded; 1 | PASS |
| B16 | One more EL day beyond the balance -> rejected | Rejected: Insufficient | Rejected: Insufficient leave balance for this leave type | PASS |
| B17 | Late-mark rule: every payroll row deducts 0.5 day per 3 late marks | 0 | 0 | PASS |
| B18 | Mid-month joiner (Isha, joined 12 Oct): 6 days loss of pay | 6.0 | 6.0 | PASS |
| B19 | Every payroll row: net = gross - total deductions, and net >= 0 | 0 | 0 | PASS |
| B20 | Leave from 31 Dec to 1 Jan (crosses a year end) -> must be split | Rejected: crosses a year end | Rejected: Split leave that crosses a year end into two requests | PASS |
