"""
build.py — сборка исполняемого файла через PyInstaller
Запуск: python build.py [--windows|--macos|--linux]
"""
import subprocess
import sys
import os
import time

def build_exe(platform="auto"):
    """Сборка исполняемого файла для указанной платформы"""

    host_platform = (
        "windows" if os.name == 'nt'
        else "macos" if sys.platform == 'darwin'
        else "linux" if sys.platform.startswith('linux')
        else "unknown"
    )

    if platform != "auto" and platform != host_platform:
        print(
            f"✗ Кросс-сборка через PyInstaller не поддерживается: "
            f"запрошено {platform}, текущая ОС {host_platform}."
        )
        print("  Для macOS собирайте проект на Mac или в macOS CI/CD.")
        return 1
    
    # Проверяем, не запущен ли уже exe
    exe_name = "CVAdapter.exe"
    if os.name == 'nt':
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
            capture_output=True, text=True
        )
        if exe_name in result.stdout:
            print(f"⚠ ОШИБКА: {exe_name} уже запущен!")
            print("  Пожалуйста, закройте приложение и повторите попытку.")
            return 1

    # Базовые аргументы
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",                # очистка перед сборкой
        "--onefile",               # один файл
        "--name", "CVAdapter",     # имя выходного файла
        "--noconsole",             # без консоли (GUI)
        "--windowed",              # оконное приложение
    ]

    # Добавляем необходимые файлы
    data_files = [
        (".env.example", "."),     # шаблон конфига
        ("system_prompt.txt", "."), # системный промпт
        ("client_secret.json", "."), # OAuth credentials (шаблон)
    ]

    data_separator = ";" if os.name == 'nt' else ":"

    for src, dst in data_files:
        if os.path.exists(src):
            cmd.extend(["--add-data", f"{src}{data_separator}{dst}"])

    # Hidden imports
    hidden_imports = [
        "main",
        "analyzer",
        "resume_adapter",
        "cv_docs",
        "prompts",
        "llm",
        "sheets",
        "config",
    ]
    for mod in hidden_imports:
        cmd.extend(["--hidden-import", mod])

    # Платформо-специфичные настройки
    if platform == "windows" or (platform == "auto" and os.name == 'nt'):
        # cmd.extend([
        #     "--icon", "icon.ico",  # иконка (если есть)
        # ])
        ext = ".exe"
    elif platform == "macos" or (platform == "auto" and sys.platform == 'darwin'):
        cmd.extend([
            "--osx-bundle-identifier", "com.cvadapter.app",
            # "--icon", "icon.icns",  # иконка (если есть)
        ])
        ext = ".app"
    elif platform == "linux" or (platform == "auto" and sys.platform.startswith('linux')):
        ext = ""
    else:
        print(f"Неизвестная платформа: {platform}")
        return 1

    # Entry point
    cmd.append("gui.py")

    print(f"Сборка для {platform}...")
    print("Команда:", " ".join(cmd))
    
    # Запоминаем время перед сборкой
    build_start_time = time.time()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        output_name = f"dist/CVAdapter{ext}"
        
        # Проверяем, что файл существует и был обновлен
        if os.path.exists(output_name):
            file_mtime = os.path.getmtime(output_name)
            if file_mtime >= build_start_time - 1:  # -1 сек для погрешности
                print(f"\n✓ Готово! Файл успешно обновлён: {output_name}")
                file_size = os.path.getsize(output_name) / 1024 / 1024
                print(f"  Размер: {file_size:.1f} МБ")
                if ext == ".app":
                    print("  При первом запуске macOS-версия сама создаст ~/Library/Application Support/CVAdapter/")
                    print("  Если получится, она сама скопирует туда .env/.env.example и system_prompt.txt")
                    print("  Если client_secret.json не скопируется автоматически, положите его в эту папку вручную")
                else:
                    print("  Положите рядом с ним: .env, system_prompt.txt и client_secret.json")
                print("  Запустите двойным кликом!")
            else:
                print(f"\n⚠ ОШИБКА: Файл {output_name} не был обновлён!")
                print("  Вероятно, exe был открыт во время сборки.")
                print("  Закройте приложение и пересобките заново.")
                return 1
        else:
            print(f"\n✗ ОШИБКА: Файл не создан: {output_name}")
            return 1
    else:
        print("\n✗ Ошибка сборки")

    return result.returncode


def main():
    if len(sys.argv) > 1:
        platform = sys.argv[1].lstrip('--')
        if platform not in ['windows', 'macos', 'linux']:
            print("Использование: python build.py [--windows|--macos|--linux]")
            print("Без аргументов — автоопределение платформы")
            sys.exit(1)
    else:
        platform = "auto"

    exit_code = build_exe(platform)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
