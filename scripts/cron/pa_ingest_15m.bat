@echo off
cd /d "C:\Users\koray\projeler\Price Action"
python scripts\ingest_15m_live.py >> logs\cron_ingest_15m.log 2>&1
