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
        self.root.geometry("900x660")
        self.root.minsize(820, 580)
        self.root.configure(bg="#f4f6f8")
        
        # Процесс для отслеживания и остановки
        self.process = None

        # Стили для кнопок
        self.style = ttk.Style(self.root)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        self.style.configure("Card.TFrame", background="#ffffff")
        self.style.configure("Inner.TFrame", background="#ffffff")

        self.style.configure(
            "Primary.TButton",
            foreground="#ffffff",
            background="#0f766e",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(14, 10),
            font=("Segoe UI", 10, "bold"),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", "#0d6b64"), ("disabled", "#99d6d1")],
        )
        self.style.configure(
            "ActivePrimary.TButton",
            foreground="#99f6e4",
            background="#115e59",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(14, 10),
            font=("Segoe UI", 10, "bold"),
        )
        self.style.map(
            "ActivePrimary.TButton",
            background=[("active", "#0f4f4a")],
        )

        self.style.configure(
            "Hero.TButton",
            foreground="#ffffff",
            background="#0f766e",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(16, 12),
            font=("Segoe UI", 11, "bold"),
        )
        self.style.map(
            "Hero.TButton",
            background=[("active", "#0d5f5a"), ("disabled", "#7dd3cf")],
        )
        self.style.configure(
            "ActiveHero.TButton",
            foreground="#ffffff",
            background="#115e59",
            borderwidth=0,
            focusthickness=3,
            focuscolor="",
            padding=(16, 12),
            font=("Segoe UI", 11, "bold"),
        )
        self.style.map(
            "ActiveHero.TButton",
            background=[("active", "#134e4a")],
        )

        self.style.configure(
            "Secondary.TButton",
            foreground="#64748b",
            background="#f4f6f8",
            borderwidth=1,
            relief="solid",
            focusthickness=2,
            focuscolor="",
            padding=(10, 6),
            font=("Segoe UI", 9),
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#e8ecf0"), ("disabled", "#f4f6f8")],
            foreground=[("active", "#334155")],
        )
        self.style.configure(
            "Danger.TButton",
            foreground="#64748b",
            background="#f4f6f8",
            borderwidth=1,
            relief="solid",
            focusthickness=2,
            focuscolor="",
            padding=(10, 6),
            font=("Segoe UI", 9),
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", "#e8ecf0"), ("disabled", "#f4f6f8")],
            foreground=[("active", "#334155")],
        )

        # Карточка управления
        control_card = ttk.Frame(root, style="Card.TFrame", padding=(14, 12))
        control_card.pack(fill=tk.X, padx=14, pady=(14, 8))

        title_label = tk.Label(
            control_card,
            text="Сценарии",
            bg="#ffffff",
            fg="#1e293b",
            font=("Segoe UI", 12, "bold"),
            anchor=tk.W,
        )
        title_label.pack(fill=tk.X)

        subtitle_label = tk.Label(
            control_card,
            text="Выберите сценарий для запуска",
            bg="#ffffff",
            fg="#94a3b8",
            font=("Segoe UI", 9),
            anchor=tk.W,
            pady=2,
        )
        subtitle_label.pack(fill=tk.X)

        primary_frame = ttk.Frame(control_card, style="Inner.TFrame")
        primary_frame.pack(fill=tk.X, pady=(8, 0))

        # Кнопки основных задач
        self.btn_linkedin = ttk.Button(primary_frame, text="Поиск в LinkedIn", command=self.run_linkedin, style="Primary.TButton")
        self.btn_analyze = ttk.Button(primary_frame, text="Анализ вакансий", command=self.run_analyze, style="Primary.TButton")
        self.btn_adapt = ttk.Button(primary_frame, text="Адаптация резюме", command=self.run_adapt, style="Primary.TButton")
        self.btn_all = ttk.Button(primary_frame, text="Поиск+Анализ+Адаптация", command=self.run_all, style="Hero.TButton")

        self.btn_linkedin.grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="ew")
        self.btn_analyze.grid(row=0, column=1, padx=(0, 8), pady=(0, 8), sticky="ew")
        self.btn_adapt.grid(row=0, column=2, pady=(0, 8), sticky="ew")
        self.btn_all.grid(row=1, column=0, columnspan=3, sticky="ew")

        primary_frame.grid_columnconfigure(0, weight=1)
        primary_frame.grid_columnconfigure(1, weight=1)
        primary_frame.grid_columnconfigure(2, weight=1)

        aux_frame = ttk.Frame(control_card, style="Inner.TFrame")
        aux_frame.pack(fill=tk.X, pady=(10, 0))

        aux_hint = tk.Label(
            aux_frame,
            text="Вспомогательные действия",
            bg="#ffffff",
            fg="#94a3b8",
            font=("Segoe UI", 8),
            anchor=tk.W,
        )
        aux_hint.pack(side=tk.LEFT)

        self.btn_clear = ttk.Button(aux_frame, text="Очистить лог", command=self.clear_log, style="Secondary.TButton")
        self.btn_cancel = ttk.Button(aux_frame, text="Отмена", command=self.cancel_task, style="Danger.TButton")

        self.btn_cancel.pack(side=tk.RIGHT)
        self.btn_clear.pack(side=tk.RIGHT, padx=(0, 8))

        self._main_buttons = {
            "linkedin": {
                "button": self.btn_linkedin,
                "label": "Поиск в LinkedIn",
                "normal_style": "Primary.TButton",
                "active_style": "ActivePrimary.TButton",
            },
            "analyze": {
                "button": self.btn_analyze,
                "label": "Анализ вакансий",
                "normal_style": "Primary.TButton",
                "active_style": "ActivePrimary.TButton",
            },
            "adapt": {
                "button": self.btn_adapt,
                "label": "Адаптация резюме",
                "normal_style": "Primary.TButton",
                "active_style": "ActivePrimary.TButton",
            },
            "all": {
                "button": self.btn_all,
                "label": "Поиск+Анализ+Адаптация",
                "normal_style": "Hero.TButton",
                "active_style": "ActiveHero.TButton",
            },
        }
        self._active_mode = ""

        # Шрифт, поддерживающий кириллицу
        log_font = font.Font(family="Segoe UI", size=10)
        
        # Карточка логов
        log_card = ttk.Frame(root, style="Card.TFrame", padding=(10, 10))
        log_card.pack(padx=14, pady=8, fill=tk.BOTH, expand=True)

        log_title = tk.Label(
            log_card,
            text="Лог выполнения",
            bg="#ffffff",
            fg="#1e293b",
            font=("Segoe UI", 10, "bold"),
            anchor=tk.W,
        )
        log_title.pack(fill=tk.X, pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            log_card,
            wrap=tk.WORD,
            height=30,
            state='disabled',
            font=log_font,
            bg="#f9fafb",
            fg="#1e293b",
            bd=1,
            relief=tk.SOLID,
            insertbackground="#111111",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Статус
        self.status_label = tk.Label(
            root,
            text="Готов к работе",
            bd=0,
            anchor=tk.W,
            bg="#e8ecf0",
            fg="#475569",
            padx=12,
            pady=10,
            font=("Segoe UI", 9, "bold"),
        )
        self.status_label.pack(fill=tk.X, padx=14, pady=(0, 14))

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

    def _apply_running_button_state(self, mode: str | None):
        self._active_mode = mode or ""

        for btn_mode, spec in self._main_buttons.items():
            button = spec["button"]
            label = spec["label"]
            if mode and btn_mode == mode:
                button.configure(style=spec["active_style"], text=f"● {label}")
                button.state(["!disabled"])
            else:
                button.configure(style=spec["normal_style"], text=label)
                if mode:
                    button.state(["disabled"])
                else:
                    button.state(["!disabled"])

    def _update_button_states(self, running: bool):
        if running:
            self._apply_running_button_state(self._active_mode)
            self.btn_cancel.state(["!disabled"])
            self.btn_clear.state(["disabled"])
        else:
            self._apply_running_button_state(None)
            self.btn_cancel.state(["disabled"])
            self.btn_clear.state(["!disabled"])

    def run_task(self, mode):
        if self.is_running:
            messagebox.showwarning("Предупреждение", "Задача уже выполняется!")
            return

        self.is_running = True
        self.cancel_event.clear()
        self._active_mode = mode
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
            self._active_mode = ""
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