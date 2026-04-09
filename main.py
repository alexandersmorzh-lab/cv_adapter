"""
main.py — точка входа приложения CV Adapter
"""
import logging
import sys
import time
import traceback
from pathlib import Path

import gspread

import config
import sheets
import llm
import analyzer
import resume_adapter


def _setup_io_and_logging() -> None:
    """Построчный вывод и при DEBUG — сообщения с временем (чтобы в терминале было видно прогресс)."""
    if config.DEBUG:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s  %(message)s",
            datefmt="%H:%M:%S",
            force=True,
        )
    else:
        logging.basicConfig(level=logging.WARNING, force=True)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(line_buffering=True)
            except (OSError, AttributeError, ValueError):
                pass

    # Запросы Google Sheets / httpx иначе засыпают консоль при DEBUG=1
    if config.DEBUG and not config.DEBUG_HTTP:
        for name in (
            "urllib3",
            "urllib3.connectionpool",
            "httpx",
            "httpcore",
            "google.auth.transport.requests",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)

    log = logging.getLogger(__name__)
    log.debug(
        "Старт: cwd=%s script=%s frozen=%s DEBUG=%s DEBUG_HTTP=%s PAUSE_ON_EXIT=%s",
        Path.cwd(),
        Path(__file__).resolve(),
        getattr(sys, "frozen", False),
        config.DEBUG,
        config.DEBUG_HTTP,
        config.PAUSE_ON_EXIT,
    )


def main():
    _setup_io_and_logging()
    print("=" * 60, flush=True)
    print("  CV Adapter — адаптация резюме под вакансии", flush=True)
    print("=" * 60, flush=True)

    # Определяем режим работы из аргументов командной строки
    mode = _get_mode()

    # 1. Проверяем обязательные настройки
    _check_config()

    # 2. Авторизация в Google
    print("\n[*] Подключение к Google Sheets...", flush=True)
    try:
        client = sheets.authenticate()
        print("    ✓ Авторизация успешна", flush=True)
    except FileNotFoundError as e:
        _fatal(str(e))
    except Exception as e:
        _fatal(f"Ошибка авторизации Google: {e}")

    # 3. Читаем базовое резюме
    print("[*] Загрузка базового резюме (лист 'Master CV')...", flush=True)
    try:
        base_cv = sheets.get_base_cv(client)
        if not base_cv.strip():
            _fatal("Лист 'Master CV' пуст. Добавьте базовое резюме.")
        print(f"    ✓ Резюме загружено ({len(base_cv)} символов)", flush=True)
    except Exception as e:
        _fatal(f"Ошибка чтения листа Master CV: {e}")

    # 4. Выполняем операцию в зависимости от режима
    if mode == "analyze":
        _run_analyzer(client, base_cv)
    elif mode == "adapt":
        _run_adapter(client, base_cv)
    elif mode == "all":
        _run_analyzer(client, base_cv)
        _run_adapter(client, base_cv)


def _get_mode() -> str:
    """Определяет режим работы из аргументов командной строки или по умолчанию."""
    # Если есть аргументы, используем первый как режим
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("analyze", "adapt", "all"):
            return arg
        print(f"⚠ Неизвестный режим: {arg}", flush=True)
        print("Допустимые значения: analyze | adapt | all", flush=True)
    
    # По умолчанию: analyze
    return "analyze"


def _run_analyzer(client: gspread.Client, base_cv: str):
    """Запускает анализатор вакансий из Search DataBase."""
    print("\n[1/2] Analyzer: обработка листа 'Search DataBase' и синхронизация с Tracker...", flush=True)
    try:
        analyzed_ok, analyzed_total, added_to_tracker = analyzer.run_analyzer_search_database(
            client=client, base_cv=base_cv
        )
    except ValueError as e:
        _fatal(str(e))
    except gspread.WorksheetNotFound as e:
        title = str(e)
        _fatal(
            f"Лист «{title}» не найден в Google Таблице. "
            "Проверьте имена листов в документе и переменные в .env "
            "(SHEET_SEARCH_DATABASE, SHEET_WRONG_PHRASES, SHEET_ADDITIONAL_FILTER, SHEET_TRACKER)."
        )
    except Exception as e:
        _fatal(f"Ошибка Analyzer: {e}")

    if analyzed_total == 0:
        print(
            "      ℹ Analyzer: нет строк в Search DataBase (Description заполнен, SummaryScoring пуст).",
            flush=True,
        )
    else:
        if analyzed_ok == analyzed_total:
            print(f"    ✓ Analyzer: обработано строк: {analyzed_ok}/{analyzed_total}", flush=True)
        else:
            print(
                f"    ⚠ Analyzer: полностью обработано {analyzed_ok} из {analyzed_total}; "
                "по остальным смотрите сообщения ✗ выше.",
                flush=True,
            )
        print(f"    ℹ Добавлено в Tracker: {added_to_tracker} строк", flush=True)


def _run_adapter(client: gspread.Client, base_cv: str):
    """Запускает адаптацию резюме для строк из Tracker."""
    print("\n[2/2] Resume Adapter: создание адаптированных резюме...", flush=True)
    try:
        processed_ok, processed_total = resume_adapter.run_resume_adapter(
            client=client,
            base_cv=base_cv,
            delay_sec=2.0
        )
    except ValueError as e:
        _fatal(str(e))
    except Exception as e:
        _fatal(f"Ошибка Resume Adapter: {e}")

    if processed_total == 0:
        print("    ℹ Resume Adapter: нет строк для обработки (все резюме уже созданы).", flush=True)
    else:
        if processed_ok == processed_total:
            print(f"    ✓ Resume Adapter: обработано резюме: {processed_ok}/{processed_total}", flush=True)
        else:
            print(
                f"    ⚠ Resume Adapter: успешно создано {processed_ok} из {processed_total}; "
                "по остальным смотрите сообщения ✗ выше.",
                flush=True,
            )

    print(f"\n{'=' * 60}", flush=True)
    print(f"  ✓ Готово!", flush=True)
    print(f"{'=' * 60}", flush=True)
    _pause_and_exit(0)


def _check_config():
    """Проверяет наличие обязательных настроек."""
    errors = []

    if not config.SPREADSHEET_ID:
        errors.append("SPREADSHEET_ID не задан в .env")

    provider = config.LLM_PROVIDER.lower()
    if provider == "gemini" and not config.GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY не задан в .env")
    elif provider == "openai" and not config.OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY не задан в .env")
    elif provider == "groq" and not config.GROQ_API_KEY:
        errors.append("GROQ_API_KEY не задан в .env")

    if errors:
        print("\n⚠ Ошибки конфигурации (.env):", flush=True)
        for e in errors:
            print(f"  • {e}", flush=True)
        _pause_and_exit(1)


def _fatal(message: str):
    print(f"\n✗ КРИТИЧЕСКАЯ ОШИБКА:\n  {message}", flush=True)
    _pause_and_exit(1)


def _pause_and_exit(code: int = 0):
    """При запуске как EXE ждёт нажатия Enter перед закрытием."""
    if not config.PAUSE_ON_EXIT:
        sys.exit(code)
    print("\nНажмите Enter для выхода...", flush=True)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем.", flush=True)
        sys.exit(0)
    except Exception:
        print("\n✗ Неожиданная ошибка:", flush=True)
        traceback.print_exc()
        _pause_and_exit(1)