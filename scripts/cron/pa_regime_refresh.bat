@echo off
cd /d "C:\Users\koray\projeler\Price Action"
python scripts\regime_features_refresh.py >> logs\cron_regime_refresh.log 2>&1
