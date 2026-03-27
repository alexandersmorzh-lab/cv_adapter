# CV Adapter

Адаптирует резюме под вакансии из Google Sheets с помощью AI.

---

## Быстрый старт

### Что нужно в папке рядом с CVAdapter.exe:
```
CVAdapter.exe
.env                  ← ваши настройки
client_secret.json    ← OAuth-ключ от Google
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

## Шаг 2 — Настройка Gemini API

1. Откройте [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Нажмите **Create API key**
3. Скопируйте ключ в `.env` → `GEMINI_API_KEY=...`

Бесплатная квота Gemini 1.5 Flash: **1 500 запросов/день**, 15 RPM.

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
Токен сохранится в `token.json` — повторная авторизация не нужна.

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
