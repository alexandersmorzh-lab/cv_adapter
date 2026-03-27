"""
build.py — сборка EXE через PyInstaller
Запуск: python build.py
"""
import subprocess
import sys

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--clean",                # очистка перед сборкой
    "--onefile",               # один EXE файл
    "--name", "CVAdapter",     # имя выходного файла
    "--console",               # консольное окно (видны логи)
    "--add-data", ".env.example;.",   # шаблон конфига
    "main.py",
]

print("Сборка EXE...")
result = subprocess.run(cmd)

if result.returncode == 0:
    print("\n✓ Готово! Файл: dist/CVAdapter.exe")
    print("  Положите рядом с ним: .env, system_prompt.txt и client_secret.json")
else:
    print("\n✗ Ошибка сборки")
    sys.exit(1)
