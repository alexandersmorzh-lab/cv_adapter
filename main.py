"""
main.py — точка входа приложения CV Adapter
"""
import sys
import time
import traceback

import config
import sheets
import llm


def main():
    print("=" * 60)
    print("  CV Adapter — адаптация резюме под вакансии")
    print("=" * 60)

    # 1. Проверяем обязательные настройки
    _check_config()

    # 2. Авторизация в Google
    print("\n[1/4] Подключение к Google Sheets...")
    try:
        client = sheets.authenticate()
        print("      ✓ Авторизация успешна")
    except FileNotFoundError as e:
        _fatal(str(e))
    except Exception as e:
        _fatal(f"Ошибка авторизации Google: {e}")

    # 3. Читаем базовое резюме
    print("[2/4] Загрузка базового резюме (лист 'Master CV')...")
    try:
        base_cv = sheets.get_base_cv(client)
        if not base_cv.strip():
            _fatal("Лист 'Master CV' пуст. Добавьте базовое резюме.")
        print(f"      ✓ Резюме загружено ({len(base_cv)} символов)")
    except Exception as e:
        _fatal(f"Ошибка чтения листа Master CV: {e}")

    # 4. Читаем вакансии для обработки
    print("[3/4] Поиск вакансий для обработки (лист 'Tracker')...")
    try:
        worksheet, rows, col_indices, headers = sheets.get_tracker_rows(client)
    except ValueError as e:
        _fatal(str(e))
    except Exception as e:
        _fatal(f"Ошибка чтения листа Tracker: {e}")

    if not rows:
        print("      ℹ Нет строк для обработки.")
        print("        (Нужны строки: Description заполнен, Adapted CV — пуст)")
        _pause_and_exit(0)

    print(f"      ✓ Найдено вакансий для обработки: {len(rows)}")

    # 5. Генерация и запись
    print(f"[4/4] Генерация адаптированных резюме (LLM: {config.LLM_PROVIDER})...\n")
    ok = 0
    errors = 0

    for idx, row in enumerate(rows, start=1):
        row_num = row["row_num"]
        description = row["description"]
        preview = description[:60].replace("\n", " ")
        print(f"  [{idx}/{len(rows)}] Строка {row_num}: {preview}...")

        try:
            adapted_cv = llm.generate_adapted_cv(base_cv, description)
            sheets.write_adapted_cv(worksheet, row_num, col_indices["adapted_cv"], adapted_cv)
            print(f"         ✓ Записано ({len(adapted_cv)} символов)")
            ok += 1
        except Exception as e:
            print(f"         ✗ Ошибка: {e}")
            errors += 1

        # Пауза между запросами (Groq free tier: 12000 TPM)
        if idx < len(rows):
            print("         ⏳ Пауза 15 сек (rate limit)...")
            time.sleep(15)

    # Итог
    print(f"\n{'=' * 60}")
    print(f"  Готово! Обработано: {ok} ✓   Ошибок: {errors} ✗")
    print(f"{'=' * 60}")
    _pause_and_exit(0 if errors == 0 else 1)


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
        print("\n⚠ Ошибки конфигурации (.env):")
        for e in errors:
            print(f"  • {e}")
        _pause_and_exit(1)


def _fatal(message: str):
    print(f"\n✗ КРИТИЧЕСКАЯ ОШИБКА:\n  {message}")
    _pause_and_exit(1)


def _pause_and_exit(code: int = 0):
    """При запуске как EXE ждёт нажатия Enter перед закрытием."""
    print("\nНажмите Enter для выхода...")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем.")
        sys.exit(0)
    except Exception:
        print("\n✗ Неожиданная ошибка:")
        traceback.print_exc()
        _pause_and_exit(1)