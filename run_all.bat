@echo off
REM CV Adapter - быстрый запуск: Отобрать вакансии И подготовить резюме
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py all
pause
