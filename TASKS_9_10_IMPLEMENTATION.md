# Реализация задач 9 и 10 - Меню в Google Sheet и Адаптация резюме

## Резюме

Реализованы две задачи:
- **Задача 9**: Интеграция с Google Sheet через два пункта меню
- **Задача 10**: Создание адаптированного резюме в Google Doc по шаблону

## Новые компоненты

### 1. **sheets.py** (расширен)
- Добавлена поддержка Google Docs API и Google Drive API
- Новые функции:
  - `get_master_cv_metadata()` — читает конфигурацию из Master CV
  - `copy_google_doc()` — копирует документ-шаблон
  - `get_doc_link()` — формирует ссылку на документ
  - `update_tracker_new_cv_file()` — обновляет колонку "New CV File"

### 2. **cv_docs.py** (новый модуль)
Функции:
- `create_adapted_cv_document()` — основная функция, которая:
  1. Генерирует адаптированное резюме через LLM
  2. Копирует шаблон документа
  3. Заменяет текст в копии
  4. Возвращает ссылку
- `_replace_text_in_doc()` — замена текста в Google Doc
- `extract_text_from_description()` — очистка текста описания

### 3. **resume_adapter.py** (новый модуль)
- `run_resume_adapter()` — основная функция, обрабатывает все строки в Tracker:
  - Находит строки с заполненным Description и пустым "New CV File"
  - Создает адаптированное резюме для каждой
  - Обновляет Tracker ссылками на документы

### 4. **main.py** (обновлен)
- Новая архитектура с поддержкой режимов работы
- Функции:
  - `_get_mode()` — определяет режим из аргументов командной строки
  - `_run_analyzer()` — запуск Analyzer
  - `_run_adapter()` — запуск Resume Adapter

Режимы:
```bash
python main.py analyze   # Отобрать вакансии
python main.py adapt     # Подготовить резюме
python main.py all       # Обе операции
```

### 5. **config.py** (расширен)
Новые параметры:
- `COL_NEW_CV_FILE` — название колонки для ссылок на резюме
- `CV_TEMPLATE_DOC_ID` — ID шаблона (заполняется из Master CV)
- `ADAPTED_CVS_FOLDER_ID` — ID папки для резюме
- `ADAPTED_CVS_FOLDER_NAME` — имя папки

## Интеграция с Google Sheet

### Вариант 1: Google Apps Script (встроенный редактор Sheet)

1. **Откройте Google Sheet**
2. Меню Extensions → Apps Script
3. Скопируйте весь контент из файла `CV_Adapter_Apps_Script.gs`
4. Сохраните (Ctrl+S)
5. Обновите страницу Sheet (F5)
6. Теперь в Sheet появится меню **"CV Adapter"** с двумя пунктами:
   - "Отобрать вакансии"
   - "Подготовить резюме"

**ВАЖНО**: Apps Script не может напрямую запустить Python на вашем компьютере. Требуется одно из:

#### Способ А: Запуск вручную (рекомендуется для простоты)
Просто дважды кликните на batch-файл в папке проекта:
- `run_analyze.bat` — Отобрать вакансии
- `run_adapt.bat` — Подготовить резюме
- `run_all.bat` — Обе операции

#### Способ Б: Через HTTP сервер (продвинуто)
Создайте простой Python Flask сервер (примечание в .gs файле) и раскомментируйте ВАРИАНТ 1 в `executeCommand()`.

## Структура данных Master CV

Лист "Master CV" должен содержать:

| Раздел | Значение |
|--------|----------|
| Master CV | [содержание базового резюме] |
| CV Doc Template | https://docs.google.com/document/d/YOUR_TEMPLATE_ID/edit или просто YOUR_TEMPLATE_ID |
| System_prompt | [текст системного промпта для LLM] |
| Adapted_CVs_Folder | https://drive.google.com/drive/folders/YOUR_FOLDER_ID или просто YOUR_FOLDER_ID |

## Структура листа Tracker

Требуемые колонки:
- `Title` — название должности
- `Company` — название компании
- `Description` — описание вакансии
- `New CV File` — ссылка на адаптированное резюме (заполняется автоматически)

## Используемые Google APIs

1. **Google Sheets API** — чтение/запись данных
2. **Google Docs API v1** — создание и редактирование документов
3. **Google Drive API v3** — копирование файлов, работа с папками

⚠️ Убедитесь, что эти APIs включены в Google Cloud Console!

## Требуемые разрешения OAuth

SCOPES в sheets.py:
```python
[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
```

При первом запуске будет запрошена авторизация.

## Пример использования

```bash
# 1. Отобрать вакансии и синхронизировать с Tracker
python main.py analyze

# 2. Подготовить резюме для строк в Tracker (может быть долгим)
python main.py adapt

# 3. Обе операции по очереди
python main.py all
```

## Параметры окружения (.env)

Обновите или добавьте:
```env
ADAPTED_CVS_FOLDER_NAME=Adapted_CVs
ADAPTED_CVS_FOLDER_ID=1A2B3C4D5E6F...  # Опционально, если не указано в Master CV
```

## Обработка ошибок

При ошибках:
1. Проверьте логи в консоли (если DEBUG=1)
2. Убедитесь, что Template Doc ID и папка Adapted_CVs доступны
3. Проверьте, что LLM и Drive API доступны
4. Убедитесь, что базовое резюме в Master CV заполнено

## Производительность

- Пауза между LLM запросами: 2 секунды (для rate limiting)
- Таймаут для долгих операций: 30 минут
- Рекомендуется обрабатывать до 10-20 резюме за раз

## Заметки о интеграции

### Sheet → Python интеграция

Apps Script работает **только в браузере** и не может:
- Запустить локальный Python процесс напрямую
- Получить доступ к локальной файловой системе
- Взаимодействовать с портами напрямую

**Решение**: Используйте batch-файлы для локального запуска или создайте HTTP сервер.

### Альтернатива: Apps Script с HTTP

Если хотите полной автоматизации:
1. Развертите Flask сервер на облачном сервере (например, Google Cloud Run)
2. Apps Script отправляет HTTP запросы на этот сервер
3. Сервер запускает Python и отправляет результат обратно

## Файлы

- `main.py` — обновленная точка входа
- `resume_adapter.py` — адаптация резюме
- `cv_docs.py` — работа с Google Docs
- `sheets.py` — расширена для Google Docs API
- `config.py` — новые параметры
- `CV_Adapter_Apps_Script.gs` — Google Apps Script
- `run_analyze.bat` — быстрый запуск анализа
- `run_adapt.bat` — быстрый запуск адаптации
- `run_all.bat` — быстрый запуск обеих операций

## Дальнейшие улучшения

1. [ ] Сохранение структуры/стилей при копировании документа
2. [ ] Замена текстовых плейсхолдеров в шаблоне (вместо замены всего контента)
3. [ ] Интеграция с Google Forms для запуска
4. [ ] Автоматический скачивание скопированного документа как PDF
5. [ ] Отправка уведомлений по email
