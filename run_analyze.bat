@echo off
REM CV Adapter - быстрый запуск: Отобрать вакансии
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py analyze
pause
