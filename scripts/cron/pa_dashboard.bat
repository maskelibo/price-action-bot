@echo off
cd /d "C:\Users\koray\projeler\Price Action"
python scripts\dashboard_text.py >> logs\cron_dashboard.log 2>&1
