@echo off
REM CV Adapter - batch скрипт для запуска Python
REM 
REM Использование:
REM   run_analyze.bat    - Отобрать вакансии
REM   run_adapt.bat      - Подготовить резюме
REM   run_all.bat        - Обе операции

cd /d "%~dp0"

REM Определяем режим из аргумента или названия файла
if "%1"=="" (
    REM По умолчанию - analyze
    set MODE=analyze
) else (
    set MODE=%1
)

REM Активируем виртуальное окружение и запускаем
call .venv\Scripts\activate.bat
python main.py %MODE%
pause
