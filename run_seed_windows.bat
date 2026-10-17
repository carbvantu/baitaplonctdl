@echo off
chcp 65001 >nul
python --version
python vcu_collect_pubmed.py --seed-only
if errorlevel 1 pause
pause
