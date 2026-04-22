"""
llm.py — универсальный адаптер для LLM.
Переключение провайдера: поменяй LLM_PROVIDER в .env
Поддерживаемые провайдеры: gemini | openai | groq | cerebras
"""
import json
import hashlib
import logging
import config
from prompts import get_system_prompt, build_user_prompt


_log = logging.getLogger(__name__)


def _prompt_fingerprint(text: str) -> str:
    """Короткий отпечаток для проверки, что реально отправили в LLM (без логирования текста)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def generate_adapted_cv(base_cv: str, job_description: str) -> str:
    """Генерирует адаптированное резюме через выбранный LLM-провайдер."""
    return _strip_header(
        generate_text(
            system_prompt=get_system_prompt(),
            user_prompt=build_user_prompt(base_cv, job_description),
            temperature=0.7,
            model_kind="generation",
        )
    )


def generate_text(*, system_prompt: str, user_prompt: str, temperature: float = 0.2, model_kind: str = "scoring") -> str:
    """Универсальный вызов LLM для произвольных задач (в т.ч. Analyzer)."""
    model_info = get_effective_model_info(model_kind)
    provider = model_info["provider"]
    model_name = model_info["model"]
    model_source = model_info["source"]
    resolution_warning = model_info.get("warning", "")

    if resolution_warning:
        _log.warning("LLM model resolution: %s", resolution_warning)

    _log.info(
        "LLM request: provider=%s model=%s source=%s kind=%s temp=%.3f sys_fp=%s user_fp=%s sys_len=%d user_len=%d",
        provider,
        model_name,
        model_source,
        model_kind,
        float(temperature),
        _prompt_fingerprint(system_prompt),
        _prompt_fingerprint(user_prompt),
        len(system_prompt or ""),
        len(user_prompt or ""),
    )

    if provider == "gemini":
        return _gemini_raw(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            model_name=model_name,
        )
    if provider == "openai":
        return _openai_raw(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature, model_name=model_name)
    if provider == "groq":
        return _groq_raw(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature, model_name=model_name)
    if provider == "cerebras":
        return _cerebras_raw(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature, model_name=model_name)
    raise ValueError(f"Неизвестный LLM_PROVIDER: '{provider}'. Допустимые значения: gemini, openai, groq, cerebras")


def _provider_model_override(provider: str, model_kind: str) -> str:
    if provider == "gemini":
        return config.GEMINI_MODEL_GENERATION if model_kind == "generation" else config.GEMINI_MODEL_SCORING
    if provider == "openai":
        return config.OPENAI_MODEL_GENERATION if model_kind == "generation" else config.OPENAI_MODEL_SCORING
    if provider == "groq":
        return config.GROQ_MODEL_GENERATION if model_kind == "generation" else config.GROQ_MODEL_SCORING
    if provider == "cerebras":
        return config.CEREBRAS_MODEL_GENERATION if model_kind == "generation" else config.CEREBRAS_MODEL_SCORING
    return ""


def _provider_default_model(provider: str) -> str:
    if provider == "gemini":
        return config.GEMINI_MODEL
    if provider == "openai":
        return config.OPENAI_MODEL
    if provider == "groq":
        return config.GROQ_MODEL
    if provider == "cerebras":
        return config.CEREBRAS_MODEL
    return ""


def get_effective_model_info(model_kind: str = "generation") -> dict[str, str]:
    """Возвращает модель для активного провайдера и источник, почему выбрана именно она."""
    kind = (model_kind or "").strip().lower()
    if kind not in {"generation", "scoring"}:
        raise ValueError(f"Неизвестный model_kind: '{model_kind}'. Допустимые значения: generation, scoring")

    provider = (config.LLM_PROVIDER or "").strip().lower()
    if provider not in {"gemini", "openai", "groq", "cerebras"}:
        raise ValueError(f"Неизвестный LLM_PROVIDER: '{provider}'. Допустимые значения: gemini, openai, groq, cerebras")

    generic_model = config.LLM_MODEL_GENERATION if kind == "generation" else config.LLM_MODEL_SCORING
    provider_override = _provider_model_override(provider, kind)
    provider_default = _provider_default_model(provider)

    if provider_override:
        warning = ""
        if generic_model:
            warning = (
                f"{kind}: заполнены и provider-specific, и generic LLM_MODEL_*; "
                f"используется provider-specific '{provider_override}', generic '{generic_model}' игнорируется"
            )
        return {
            "provider": provider,
            "model": provider_override,
            "source": f"provider_{kind}",
            "warning": warning,
        }

    if provider_default:
        warning = ""
        if generic_model:
            warning = (
                f"{kind}: для провайдера '{provider}' используется default '{provider_default}'; "
                f"generic '{generic_model}' игнорируется"
            )
        return {
            "provider": provider,
            "model": provider_default,
            "source": "provider_default",
            "warning": warning,
        }

    if generic_model:
        return {
            "provider": provider,
            "model": generic_model,
            "source": f"legacy_generic_{kind}",
            "warning": (
                f"{kind}: для провайдера '{provider}' не задана модель; используется legacy generic '{generic_model}'"
            ),
        }

    raise ValueError(
        f"Не задана модель для провайдера '{provider}' (kind={kind}). "
        f"Укажите provider-specific модель или базовую модель провайдера в .env"
    )


def _get_model_name(model_kind: str) -> str:
    return get_effective_model_info(model_kind)["model"]


def get_effective_model_name(model_kind: str = "generation") -> str:
    """Возвращает фактическое имя модели для выбранного провайдера и типа задачи."""
    return get_effective_model_info(model_kind)["model"]


def generate_json(*, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict:
    """
    Просит модель вернуть JSON-объект. Пытается распарсить ответ максимально устойчиво.
    Возвращает dict (или кидает исключение, если распарсить не удалось).
    """
    text = generate_text(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature)
    text = text.strip()

    # Частый случай: модель оборачивает в ```json ... ```
    if text.startswith("```"):
        parts = text.split("```")
        # Берём самый большой блок между тройными бэктиками
        candidates = [p.strip() for p in parts if p.strip() and not p.strip().lower().startswith("json")]
        if candidates:
            text = max(candidates, key=len)

    # Пытаемся вырезать JSON по первым/последним скобкам
    l = text.find("{")
    r = text.rfind("}")
    if l != -1 and r != -1 and r > l:
        text = text[l : r + 1]

    return json.loads(text)


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


def _gemini_raw(*, system_prompt: str, user_prompt: str, temperature: float, model_name: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("Установите пакет: pip install google-genai")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=float(temperature),
        ),
    )
    return (response.text or "").strip()


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


def _openai_raw(*, system_prompt: str, user_prompt: str, temperature: float, model_name: str) -> str:
    try:
        import httpx
    except ImportError:
        raise ImportError("Установите пакет: pip install httpx")

    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": float(temperature),
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


def _groq_raw(*, system_prompt: str, user_prompt: str, temperature: float, model_name: str) -> str:
    try:
        import httpx
    except ImportError:
        raise ImportError("Установите пакет: pip install httpx")

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": float(temperature),
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


# ── Cerebras ──────────────────────────────────────────────────────────────────

def _cerebras(base_cv: str, job_description: str) -> str:
    try:
        from cerebras.cloud.sdk import Cerebras
    except ImportError:
        raise ImportError("Установите пакет: pip install cerebras-cloud-sdk")

    client = Cerebras(api_key=config.CEREBRAS_API_KEY)
    user_prompt = build_user_prompt(base_cv, job_description)
    completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        model=config.CEREBRAS_MODEL,
        max_completion_tokens=1024,
        temperature=0.7,
        top_p=1,
        stream=False
    )
    return completion.choices[0].message.content.strip()


def _cerebras_raw(*, system_prompt: str, user_prompt: str, temperature: float, model_name: str) -> str:
    try:
        from cerebras.cloud.sdk import Cerebras
    except ImportError:
        raise ImportError("Установите пакет: pip install cerebras-cloud-sdk")

    client = Cerebras(api_key=config.CEREBRAS_API_KEY)
    completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model_name,
        max_completion_tokens=1024,
        temperature=temperature,
        top_p=1,
        stream=False
    )
    return completion.choices[0].message.content.strip()