# Памятка: как собрать `CVAdapter` под macOS через GitHub Actions

Короткая инструкция только для сценария **через GitHub Actions**.

---

## Когда использовать

Этот вариант нужен, если ты работаешь на **Windows**, но хочешь получить готовый `CVAdapter.app` для macOS.

> Локальная кросс-сборка `.app` из Windows через `PyInstaller` не поддерживается, поэтому используем только GitHub Actions.

---

## Пошаговая инструкция

1. Убедись, что все нужные изменения закоммичены и запушены в GitHub.
2. Открой репозиторий `cv_adapter` на GitHub.
3. Перейди во вкладку **Actions**.
4. В списке workflow выбери **Build macOS app**.
5. Нажми кнопку **Run workflow**.
6. При необходимости заполни поля:
   - `release_tag` — например `v1.0.0`
   - `release_name` — понятное имя релиза
7. Запусти workflow.
8. Дождись завершения job `build-macos`.
9. Открой результат запуска и скачай артефакт **CVAdapter-macOS**.
10. Распакуй ZIP-архив.

---

## Что будет внутри архива

В архиве будут:

- `CVAdapter.app`
- `.env.example`
- `system_prompt.txt`
- `README.md`
- `MACOS_SETUP.md`

---

## Что сделать после скачивания на Mac

1. Запустить `CVAdapter.app` один раз
2. Приложение само создаст `~/Library/Application Support/CVAdapter/`
3. Если сможет, оно само скопирует туда `.env` или `.env.example`, а также `system_prompt.txt`
4. Если `client_secret.json` не скопировался автоматически, положить его в `~/Library/Application Support/CVAdapter/`
5. Если папку `Library` пользователю сложно найти, можно вместо этого положить `.env` и `client_secret.json` в `~/Documents/CVAdapter/`
6. Запустить `CVAdapter.app` повторно

При первом входе Google OAuth создаст `token.json` в `~/Library/Application Support/CVAdapter/` автоматически.

Почему не стоит рассчитывать на файлы рядом с `.app`:

- неподписанное приложение может запускаться через App Translocation
- тогда путь рядом с `.app` становится временным и не совпадает с реальной папкой пользователя
- папка `~/Library/Application Support/CVAdapter/` стабильна и для чтения, и для записи

---

## Если macOS блокирует запуск

Так как приложение пока не подписано и не notarized, macOS может показать предупреждение.

Что делать:

1. Открой Finder
2. Найди `CVAdapter.app`
3. Нажми **правой кнопкой → Open**
4. Подтверди запуск

Если потребуется:

- открой **System Settings → Privacy & Security**
- вручную разреши запуск приложения
- если приложение всё равно стартует из временного каталога, сними quarantine:

```bash
xattr -dr com.apple.quarantine CVAdapter.app
```

---

## Коротко

**Весь процесс такой:**

`push в GitHub` → `Actions` → `Build macOS app` → `Run workflow` → `скачать CVAdapter-macOS.zip` → `запустить CVAdapter.app на Mac`
