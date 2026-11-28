"""
Takes browser screenshots of the running Streamlit app for the README.
Start the app first:  streamlit run web/app.py
Then:                 python3 tools/web_screenshots.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots" / "web"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"


def wait(page):
    page.wait_for_timeout(600)
    page.wait_for_selector("[data-testid='stStatusWidget']", state="detached", timeout=30000)
    page.wait_for_timeout(1400)


def login(page, user, pw):
    page.goto(URL)
    page.get_by_label("Username").wait_for(timeout=30000)
    page.get_by_label("Username").fill(user)
    page.get_by_role("textbox", name="Password").fill(pw)
    page.get_by_role("button", name="Log in").click()
    page.get_by_text("Log out").wait_for(timeout=30000)
    wait(page)


def go(page, label):
    page.locator("[data-testid='stSidebar']").get_by_text(label, exact=True).click()
    wait(page)


def snap(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("saved", name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        page.goto(URL)
        page.get_by_label("Username").wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        snap(page, "01_login")

        login(page, "neha", "hr@1234")
        snap(page, "02_hr_dashboard")
        go(page, "Payroll")
        snap(page, "03_hr_payroll")
        go(page, "Leave requests")
        snap(page, "04_hr_leave_requests")
        go(page, "Salary slips")
        snap(page, "05_hr_salary_slip")
        go(page, "Attendance")
        snap(page, "06_hr_attendance")

        page.get_by_role("button", name="Log out").click()
        wait(page)
        login(page, "rahul", "emp@1234")
        snap(page, "07_employee_today")
        go(page, "My leave")
        snap(page, "08_employee_leave")
        go(page, "My salary slips")
        snap(page, "09_employee_slip")
        browser.close()


if __name__ == "__main__":
    main()
