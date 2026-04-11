"""
GUI для CV Adapter - простой интерфейс для запуска задач.
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox, font, ttk
import sys
import threading
import os
import io
from pathlib import Path

import sheets

class CVAdapterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CV Adapter")
        self.root.geometry("840x620")
        self.root.configure(bg="#f4f6fb")
        
        # Процесс для отслеживания и остановки
        self.process = None

        # Стили для кнопок
        self.style = ttk.Style(self.root)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self.style.configure(
            "Primary.TButton",
            foreground="#ffffff",
            background="#3b82f6",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", "#2563eb"), ("disabled", "#93c5fd")],
        )
        self.style.configure(
            "Secondary.TButton",
            foreground="#1f2937",
            background="#e2e8f0",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(12, 8),
            font=("Segoe UI", 10),
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#cbd5e1"), ("disabled", "#f8fafc")],
        )
        self.style.configure(
            "Danger.TButton",
            foreground="#ffffff",
            background="#dc2626",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", "#b91c1c"), ("disabled", "#fca5a5")],
        )

        # Создаем фрейм для кнопок
        button_frame = ttk.Frame(root, padding=10)
        button_frame.pack(fill=tk.X, padx=10, pady=(10, 0))

        # Кнопки для задач
        self.btn_linkedin = ttk.Button(button_frame, text="Поиск в LinkedIn", command=self.run_linkedin, style="Primary.TButton")
        self.btn_analyze = ttk.Button(button_frame, text="Анализ вакансий", command=self.run_analyze, style="Primary.TButton")
        self.btn_adapt = ttk.Button(button_frame, text="Адаптация резюме", command=self.run_adapt, style="Primary.TButton")
        self.btn_all = ttk.Button(button_frame, text="Анализ + Адаптация", command=self.run_all, style="Secondary.TButton")
        self.btn_cancel = ttk.Button(button_frame, text="Отмена", command=self.cancel_task, style="Danger.TButton")
        self.btn_clear = ttk.Button(button_frame, text="Очистить лог", command=self.clear_log, style="Secondary.TButton")

        self.btn_linkedin.pack(side=tk.LEFT, padx=5)
        self.btn_analyze.pack(side=tk.LEFT, padx=5)
        self.btn_adapt.pack(side=tk.LEFT, padx=5)
        self.btn_all.pack(side=tk.LEFT, padx=5)
        self.btn_cancel.pack(side=tk.LEFT, padx=5)
        self.btn_clear.pack(side=tk.LEFT, padx=5)

        # Шрифт, поддерживающий кириллицу
        log_font = font.Font(family="Segoe UI", size=10)
        
        # Текстовое поле для логов
        self.log_text = scrolledtext.ScrolledText(
            root,
            wrap=tk.WORD,
            height=30,
            state='disabled',
            font=log_font,
            bg="#ffffff",
            fg="#111111",
            bd=0,
            relief=tk.FLAT,
            insertbackground="#111111",
        )
        self.log_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Статус
        self.status_label = tk.Label(
            root,
            text="Готов к работе",
            bd=0,
            anchor=tk.W,
            bg="#eef2ff",
            fg="#1f2937",
            padx=10,
            pady=8,
        )
        self.status_label.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Запрещаем закрытие во время выполнения
        self.is_running = False
        self.cancel_event = threading.Event()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._update_button_states(running=False)

    def log(self, message):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state='disabled')
        self.log_text.see(tk.END)
        self.root.update()
        self.root.update_idletasks()

    def set_status(self, message):
        self.status_label.config(text=message)
        self.root.update()

    def _update_button_states(self, running: bool):
        if running:
            for button in (self.btn_linkedin, self.btn_analyze, self.btn_adapt, self.btn_all):
                button.state(["disabled"])
            self.btn_cancel.state(["!disabled"])
            self.btn_clear.state(["disabled"])
        else:
            for button in (self.btn_linkedin, self.btn_analyze, self.btn_adapt, self.btn_all):
                button.state(["!disabled"])
            self.btn_cancel.state(["disabled"])
            self.btn_clear.state(["!disabled"])

    def run_task(self, mode):
        if self.is_running:
            messagebox.showwarning("Предупреждение", "Задача уже выполняется!")
            return

        self.is_running = True
        self.cancel_event.clear()
        self._update_button_states(running=True)
        self.set_status(f"Выполняется: {mode}")
        self.log(f"\n{'='*50}")
        self.log(f"Запуск задачи: {mode}")
        self.log(f"{'='*50}\n")

        # Запускаем в отдельном потоке
        thread = threading.Thread(target=self._run_subprocess, args=(mode,))
        thread.daemon = True
        thread.start()

    def _run_subprocess(self, mode):
        import main as main_module
        
        try:
            # Проверяем и проводим авторизацию Google, если нужно
            token_path = sheets.get_token_path()
            # self.log(f"[DEBUG] Token path: {token_path}")
            # self.log(f"[DEBUG] Token существует: {token_path.exists()}")

            if not token_path.exists():
                self.log("Проводим авторизацию Google...")
                try:
                    sheets.authenticate()
                    self.log("✓ Авторизация успешна!")
                    self.log(f"[DEBUG] Token сохранён: {token_path.exists()}")
                except Exception as e:
                    self.log(f"❌ Ошибка авторизации: {e}")
                    return
            else:
                self.log("✓ Найден сохранённый token.json")

            # Перенаправляем stdout/stderr в лог GUI
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            
            class GUIStream:
                def __init__(self, gui_instance):
                    self.gui = gui_instance
                    self.buffer = ""
                
                def write(self, text):
                    if text:
                        self.buffer += text
                        if '\n' in self.buffer:
                            lines = self.buffer.split('\n')
                            for line in lines[:-1]:
                                self.gui.log(line)
                            self.buffer = lines[-1]
                
                def flush(self):
                    if self.buffer:
                        self.gui.log(self.buffer)
                        self.buffer = ""
                
                def isatty(self):
                    return False
            
            gui_stream = GUIStream(self)
            sys.stdout = gui_stream
            sys.stderr = gui_stream
            
            try:
                # Запускаем main() напрямую
                sys.argv = ['main.py', mode]
                main_module.main()
                self.log("✓ Задача выполнена успешно!")
            except SystemExit as e:
                if e.code != 0:
                    self.log(f"✗ Задача завершилась с ошибкой (код {e.code})")
                else:
                    self.log("✓ Задача выполнена успешно!")
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        except Exception as e:
            self.log(f"❌ Ошибка выполнения: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            # Удаляем файл-флаг остановки
            stop_file = Path.cwd() / ".stop_requested"
            try:
                if stop_file.exists():
                    stop_file.unlink()
            except:
                pass
            
            self.process = None
            self.is_running = False
            self._update_button_states(running=False)
            self.set_status("Готов к работе")

    def run_linkedin(self):
        self.run_task('linkedin')

    def run_analyze(self):
        self.run_task('analyze')

    def run_adapt(self):
        self.run_task('adapt')

    def run_all(self):
        self.run_task('all')

    def cancel_task(self):
        if self.is_running:
            # Создаём файл-флаг для сигнала остановки
            stop_file = Path.cwd() / ".stop_requested"
            stop_file.touch()
            self.log("↻ Отправлен сигнал остановки рабочему процессу...")

    def clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

    def on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("Выход", "Задача выполняется. Остановить и выйти?"):
                self.cancel_event.set()
                # Ждем немного, чтобы процесс остановился
                import time
                for _ in range(50):  # Ждим до 5 сек
                    if not self.is_running:
                        break
                    time.sleep(0.1)
                
                # Если все еще работает, принудительно убиваем
                if self.process and self.process.poll() is None:
                    try:
                        self.process.kill()
                    except:
                        pass
        
        self.root.destroy()


def main():
    root = tk.Tk()
    app = CVAdapterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()