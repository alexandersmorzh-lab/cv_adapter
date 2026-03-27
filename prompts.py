"""
prompts.py — промпты для генерации адаптированного резюме
"""
import sys
from pathlib import Path
import config

PROMPT_FILE = "system_prompt.txt"

DEFAULT_SYSTEM_PROMPT = """Ты — профессиональный HR-консультант и карьерный коуч.
Твоя задача — адаптировать резюме кандидата под конкретную вакансию.

Правила адаптации:
1. Сохраняй только правдивую информацию из оригинального резюме — не придумывай факты.
2. Переставляй акценты: выдвигай вперёд опыт и навыки, наиболее релевантные вакансии.
3. Используй ключевые слова и формулировки из описания вакансии там, где это уместно.
4. Адаптируй summary/цель под конкретную позицию.
5. Сохраняй профессиональный тон и структуру резюме.
6. Отвечай на том же языке, на котором написано описание вакансии.
7. Верни только текст адаптированного резюме — без пояснений и комментариев.
"""


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def get_system_prompt() -> str:
    """Читает промпт из system_prompt.txt или возвращает дефолтный."""
    prompt_path = _get_base_dir() / PROMPT_FILE
    if prompt_path.exists():
        text = prompt_path.read_text(encoding="utf-8").strip()
        if text:
            print(f"      ℹ Используется промпт из {PROMPT_FILE}")
            return text
    return DEFAULT_SYSTEM_PROMPT


def build_user_prompt(base_cv: str, job_description: str) -> str:
    return f"""## Оригинальное резюме кандидата:
{base_cv}

## Описание вакансии:
{job_description}

Адаптируй резюме под эту вакансию согласно инструкциям.
"""
