#!/usr/bin/env bash
# Builds payroll_db from scratch: schema -> functions -> views -> procedures
# -> triggers -> sample data -> security. Safe to re-run (drops and recreates).
#
# Usage:  ./setup.sh            (asks for your MySQL root password; Enter if none)
set -e
cd "$(dirname "$0")"

read -r -s -p "MySQL root password (press Enter if none): " PW
echo
export MYSQL_PWD="$PW"

for f in 01_schema 02_functions 03_views 04_procedures 05_triggers 06_seed_data 07_security; do
  echo "-> sql/$f.sql"
  mysql -u root -h 127.0.0.1 < "sql/$f.sql" > /dev/null
done

echo
echo "Done. payroll_db is ready."
echo "Start the app:   python3 app/payroll_app.py"
echo "Demo logins:     HR -> neha / hr@1234     Employee -> rahul / emp@1234"
