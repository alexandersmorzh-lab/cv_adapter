"""
llm.py — универсальный адаптер для LLM.
Переключение провайдера: поменяй LLM_PROVIDER в .env
Поддерживаемые провайдеры: gemini | openai | groq
"""
import config
from prompts import get_system_prompt, build_user_prompt


def generate_adapted_cv(base_cv: str, job_description: str) -> str:
    """Генерирует адаптированное резюме через выбранный LLM-провайдер."""
    provider = config.LLM_PROVIDER.lower()

    if provider == "gemini":
        result = _gemini(base_cv, job_description)
    elif provider == "openai":
        result = _openai(base_cv, job_description)
    elif provider == "groq":
        result = _groq(base_cv, job_description)
    else:
        raise ValueError(f"Неизвестный LLM_PROVIDER: '{provider}'. Допустимые значения: gemini, openai, groq")

    return _strip_header(result)


def _strip_header(text: str) -> str:
    """Убирает заголовки вида ## Адаптированное резюме: которые модель добавляет сама."""
    text = text.strip()
    lines = text.splitlines()
    if lines and lines[0].startswith('#'):
        lines = lines[1:]
        # Убираем пустые строки после заголовка
        while lines and not lines[0].strip():
            lines = lines[1:]
    return '\n'.join(lines).strip()


# ── Gemini (Google) ───────────────────────────────────────────────────────────

def _gemini(base_cv: str, job_description: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("Установите пакет: pip install google-genai")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    user_prompt = build_user_prompt(base_cv, job_description)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=get_system_prompt(),
        ),
    )
    return response.text.strip()


# ── OpenAI ────────────────────────────────────────────────────────────────────

def _openai(base_cv: str, job_description: str) -> str:
    try:
        import httpx
    except ImportError:
        raise ImportError("Установите пакет: pip install httpx")

    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": build_user_prompt(base_cv, job_description)},
        ],
        "temperature": 0.7,
    }
    with httpx.Client(timeout=60) as client:
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text}")

    return response.json()["choices"][0]["message"]["content"].strip()


# ── Groq ──────────────────────────────────────────────────────────────────────

def _groq(base_cv: str, job_description: str) -> str:
    try:
        import httpx
    except ImportError:
        raise ImportError("Установите пакет: pip install httpx")

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": build_user_prompt(base_cv, job_description)},
        ],
        "temperature": 0.7,
    }
    with httpx.Client(timeout=60) as client:
        response = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    if response.status_code != 200:
        raise RuntimeError(f"Groq API error {response.status_code}: {response.text}")

    return response.json()["choices"][0]["message"]["content"].strip()