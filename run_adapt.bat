@echo off
REM CV Adapter - быстрый запуск: Подготовить резюме
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py adapt
pause
