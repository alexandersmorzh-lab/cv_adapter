# CV Adapter

Адаптирует резюме под вакансии из Google Sheets с помощью AI.

---

## Быстрый старт

### Что нужно рядом с приложением или в рабочей папке:
```
CVAdapter.exe (или CVAdapter.app)
.env                  ← ваши настройки
client_secret.json    ← OAuth-ключ от Google
system_prompt.txt     ← системный промпт для AI
```

### Запуск:
- **Windows**: `CVAdapter.exe` двойным кликом
- **macOS**: `CVAdapter.app` двойным кликом
- **Linux**: `./CVAdapter` в терминале

GUI откроется с кнопками для запуска задач и окном логов.

Для macOS есть важное исключение: из-за App Translocation файлы рядом с `CVAdapter.app` могут не находиться. Надёжное место для `.env`, `client_secret.json`, `token.json` и при необходимости `system_prompt.txt`:

```text
~/Library/Application Support/CVAdapter/
```

Если пользователю неудобно искать `Library`, можно положить `.env` и `client_secret.json` в более простой путь:

```text
~/Documents/CVAdapter/
```

Приложение тоже проверяет эту папку.

Новая macOS-сборка при запуске сама создаёт эту папку и, если может, копирует туда `.env`, `.env.example`, `system_prompt.txt` и `client_secret.json`. Если `client_secret.json` недоступен для автокопирования, приложение подскажет, куда его положить.
Если файл всё равно не найден, GUI предложит выбрать `client_secret.json` вручную через стандартный диалог macOS и сам скопирует его в нужное место.

---

## Сборка исполняемого файла

### Требования:
- Python 3.8+
- pip install -r requirements.txt
- pip install pyinstaller

### Сборка:
```bash
# Для текущей ОС (автоопределение)
python build.py

# Для Windows
python build.py --windows

# Для macOS
python build.py --macos

# Для Linux
python build.py --linux
```

Результат: `dist/CVAdapter.exe` (или `.app`, или без расширения)

### Сборка macOS через GitHub Actions

Если вы работаете на Windows, но нужен `CVAdapter.app`, используйте workflow:

1. Откройте репозиторий на GitHub
2. Перейдите во вкладку **Actions**
3. Запустите workflow **Build macOS app** вручную
4. При желании укажите `release_tag` вида `v1.0.0`, чтобы ZIP автоматически прикрепился к GitHub Release

Результат сборки:
- artifact `CVAdapter-macOS.zip` во вкладке Actions
- или asset в GitHub Release, если указан `release_tag`

В архив попадают:
- `CVAdapter.app`
- `.env.example`
- `system_prompt.txt`
- инструкция `MACOS_SETUP.md`

> Первая версия CI-сборки не подписана Apple certificate, поэтому на macOS может понадобиться запуск через **Right click → Open**.
> Если macOS продолжает запускать приложение через App Translocation, снимите quarantine: `xattr -dr com.apple.quarantine CVAdapter.app`

---

## Использование GUI

1. Запустите `CVAdapter.exe` двойным кликом
2. Откроется окно с кнопками:
   - **Анализ вакансий** — оценка вакансий и отбор подходящих
   - **Адаптация резюме** — генерация персонализированных резюме
   - **Анализ + Адаптация** — полный цикл
   - **Очистить лог** — очистка окна логов

3. Логи выполнения отображаются в текстовом поле
4. Во время выполнения кнопки заблокированы

---

## Консольный режим (для разработчиков)

```bash
# Анализ вакансий
python main.py analyze

# Адаптация резюме
python main.py adapt

# Полный цикл
python main.py all
```

---

## Шаг 1 — Настройка Google OAuth

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект (или выберите существующий)
3. Меню → **APIs & Services → Enable APIs**
   - Включите **Google Sheets API**
   - Включите **Google Drive API**
4. Меню → **APIs & Services → Credentials**
   - Нажмите **Create Credentials → OAuth client ID**
   - Тип приложения: **Desktop app**
   - Скачайте JSON — переименуйте в `client_secret.json`
5. Меню → **OAuth consent screen**
   - User type: **External**
   - Добавьте свой email в **Test users**

---

## Шаг 2 — Настройка AI API

### Gemini (рекомендуется, бесплатно):
1. Откройте [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Нажмите **Create API key**
3. Скопируйте ключ в `.env` → `GEMINI_API_KEY=...`

Бесплатная квота: **1 500 запросов/день**, 15 RPM.

### Другие провайдеры:
- **OpenAI**: `OPENAI_API_KEY=...`
- **Groq**: `GROQ_API_KEY=...`
- **Cerebras**: `CEREBRAS_API_KEY=...`

---

## Шаг 3 — Настройка .env

Скопируйте `.env.example` → `.env`, заполните:

```ini
SPREADSHEET_ID=  # ID из URL таблицы: /spreadsheets/d/ВОТ_ЭТО/edit
GEMINI_API_KEY=  # ключ из AI Studio
```

ID таблицы — длинная строка между `/d/` и `/edit` в URL.

---

## Шаг 4 — Структура Google Sheets

### Лист "Master CV"
Базовое резюме — просто текст в ячейках, никакого особого формата.

### Лист "Tracker"
Таблица с заголовками в первой строке. Обязательные колонки:

| ... | Description | Adapted CV | ... |
|-----|-------------|------------|-----|
| ... | Текст вакансии | (заполнится автоматически) | ... |

Порядок и название остальных колонок — любые.

---

## Запуск

Двойной клик на `CVAdapter.exe`.

При первом запуске откроется браузер для авторизации Google.
На macOS токен надёжнее всего хранится в `~/Library/Application Support/CVAdapter/token.json`.

---

## Переключение LLM

В `.env` измените `LLM_PROVIDER`:

| Значение | Провайдер | Бесплатно |
|----------|-----------|-----------|
| `gemini` | Google Gemini 1.5 Flash | ✓ 1500/день |
| `groq`   | Groq (Llama 3) | ✓ лимиты есть |
| `openai` | OpenAI GPT-4o-mini | платно |

---

## Сборка EXE из исходников

```bash
pip install -r requirements.txt
pip install pyinstaller
python build.py
```

Результат: `dist/CVAdapter.exe`
