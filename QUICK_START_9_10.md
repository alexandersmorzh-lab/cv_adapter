# БЫСТРЫЙ СТАРТ - Задачи 9 и 10

## ✅ ЧТО РЕАЛИЗОВАНО

### Задача 9: Запуск из Google Sheet
- Два пункта меню в Google Sheet через Google Apps Script
- "Отобрать вакансии"
- "Подготовить резюме"

### Задача 10: Адаптация резюме в Google Doc
- Копирование шаблона документа
- Адаптация текста через LLM
- Сохранение ссылки в Tracker

---

## 🚀 КАК НАЧАТЬ

### Шаг 1: Конфигурация Master CV

Откройте Google Sheet, лист "Master CV". Убедитесь, что есть строки:

```
Master CV         | [ваше базовое резюме текстом]
CV Doc Template   | https://docs.google.com/document/d/YOUR_TEMPLATE_ID/edit
System_prompt     | [системный промпт для LLM]
Adapted_CVs_F...  | https://drive.google.com/drive/folders/YOUR_FOLDER_ID
```

**Где получить ID:**
- Template Doc ID: откройте Google Doc → адрес строки `/d/YOUR_ID/edit`
- Folder ID: откройте папку на Drive → адрес строки `/folders/YOUR_ID`

### Шаг 2: Структура Tracker листа

Убедитесь, что Tracker содержит колонки:
- `Title` — название должности
- `Company` — компания
- `Description` — описание вакансии
- `New CV File` — **[будет заполняться автоматически]**

### Шаг 3: Запуск

#### Вариант А: Простой (batch-файлы)
Двойной клик по одному из файлов:
- `run_analyze.bat` — найти и отобрать вакансии
- `run_adapt.bat` — создать резюме для Tracker
- `run_all.bat` — обе операции подряд

#### Вариант Б: Из Google Sheet (Apps Script)
1. Откройте Google Sheet
2. Extensions → Apps Script
3. Скопируйте весь контент файла `CV_Adapter_Apps_Script.gs`
4. Ctrl+S (сохранить)
5. Обновите Sheet (F5)
6. Появится меню "CV Adapter" в Sheet

**Затем нужно будет запустить batch-файл вручную** (Apps Script не может запустить Python напрямую).

---

## 📋 КОМАНДЫ

### Через командную строку:
```bash
# Отобрать вакансии (анализ листа Search DataBase)
python main.py analyze

# Готовить резюме (адаптация для Tracker)
python main.py adapt

# Обе операции подряд
python main.py all
```

### Или двойной клик:
- `run_analyze.bat`
- `run_adapt.bat`
- `run_all.bat`

---

## ⚙️ ПАРАМЕТРЫ .env

Опционально добавьте:
```env
ADAPTED_CVS_FOLDER_NAME=Adapted_CVs
```

(Если папка не указана в Master CV, система создаст её автоматически, если возможно)

---

## 🔑 НОВАЯ АРХИТЕКТУРА

### Новые модули:
- **cv_docs.py** — работа с Google Docs (копирование, редактирование)
- **resume_adapter.py** — обработка Tracker, создание резюме

### Обновленные:
- **main.py** — поддержка режимов (analyze/adapt/all)
- **sheets.py** — Google Docs & Drive APIs
- **config.py** — новые параметры

---

## ✅ ПРОВЕРКА

```bash
# Проверить, что все модули рабочие:
python -c "import resume_adapter, cv_docs; print('OK')"
```

---

## 📖 ПОДРОБНАЯ ДОКУМЕНТАЦИЯ

Смотрите файл: `TASKS_9_10_IMPLEMENTATION.md`

---

## ❓ ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ

### Ошибка: "CV Doc Template не найден"
- Проверьте, что в Master CV строка "CV Doc Template" заполнена
- Используйте полный ID (без `https://...`)

### Ошибка: "Google Docs API не инициализирован"
- Убедитесь, что Google Docs API включен в Cloud Console
- Часто требуется повторная авторизация

### Ошибка про папку
- Создайте папку "Adapted_CVs" на Google Drive вручную
- Скопируйте её ID в Master CV, строка "Adapted_CVs_Folder"

### Долгое выполнение
- Нормально если обрабатывается 10+ резюме
- Есть задержка 2 сек между LLM запросами

---

## 🎯 ТИПИЧНЫЙ WORKFLOW

1. **Утро**: Запустить `run_analyze.bat`
   - Обработает все новые вакансии из "Search DataBase"
   - Добавит подходящие в "Tracker"

2. **После анализа**: Запустить `run_adapt.bat`
   - Создаст адаптированные резюме для всех строк в Tracker
   - Добавит ссылки в колонку "New CV File"

3. **Результат**: В папке "Adapted_CVs" на Drive появятся новые Google Docs с резюме

---

## 📝 ГОТОВО!

Функциональность **Задач 9 и 10** полностью реализована и готова к использованию.

Удачи! 🚀
