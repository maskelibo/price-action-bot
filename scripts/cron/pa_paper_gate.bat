@echo off
cd /d "C:\Users\koray\projeler\Price Action"
python scripts\paper_gate_evaluator.py >> logs\cron_paper_gate.log 2>&1
