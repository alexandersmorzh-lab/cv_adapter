"""
config.py — загрузка настроек из .env файла
"""
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable
from dotenv import load_dotenv

# Исправление кодировки для Windows (чтобы печатать Unicode символы)
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8')

APP_NAME = "CVAdapter"
IS_FROZEN = bool(getattr(sys, "frozen", False))
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else SCRIPT_DIR
DEFAULT_CLIENT_SECRET_FILE = "client_secret.json"
DEFAULT_SYSTEM_PROMPT_FILE = "system_prompt.txt"
DEFAULT_ENV_FILE = ".env"
DEFAULT_ENV_TEMPLATE_FILE = ".env.example"


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path.expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(path.expanduser())
    return unique


def get_bundle_resources_dir() -> Path | None:
    if IS_FROZEN and sys.platform == "darwin":
        resources_dir = BASE_DIR.parent / "Resources"
        return resources_dir
    return None


def get_macos_app_bundle_dir() -> Path | None:
    if not (IS_FROZEN and sys.platform == "darwin"):
        return None
    contents_dir = BASE_DIR.parent
    if contents_dir.name != "Contents":
        return None
    app_dir = contents_dir.parent
    if app_dir.suffix != ".app":
        return None
    return app_dir


def get_preferred_user_data_dir() -> Path:
    if IS_FROZEN and sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return BASE_DIR


def get_easy_access_data_dir() -> Path | None:
    if IS_FROZEN and sys.platform == "darwin":
        return Path.home() / "Documents" / APP_NAME
    return None


def get_shared_macos_data_dir() -> Path | None:
    if IS_FROZEN and sys.platform == "darwin":
        return Path("/Library/Application Support") / APP_NAME
    return None


def get_runtime_search_dirs() -> list[Path]:
    dirs: list[Path] = []

    if IS_FROZEN and sys.platform == "darwin":
        dirs.append(get_preferred_user_data_dir())
        easy_access_dir = get_easy_access_data_dir()
        if easy_access_dir is not None:
            dirs.append(easy_access_dir)
        shared_dir = get_shared_macos_data_dir()
        if shared_dir is not None:
            dirs.append(shared_dir)

    dirs.append(Path.cwd())
    dirs.append(BASE_DIR)

    resources_dir = get_bundle_resources_dir()
    if resources_dir is not None:
        dirs.append(resources_dir)

    app_bundle_dir = get_macos_app_bundle_dir()
    if app_bundle_dir is not None:
        dirs.append(app_bundle_dir.parent)

    dirs.append(SCRIPT_DIR)
    return _unique_paths(dirs)


def get_candidate_file_paths(file_name: str, *, extra_dirs: Iterable[Path] | None = None) -> list[Path]:
    path = Path(file_name).expanduser()
    if path.is_absolute():
        return [path]

    search_dirs = list(extra_dirs or []) + get_runtime_search_dirs()
    return [directory / path for directory in _unique_paths(search_dirs)]


def find_existing_data_file(file_name: str, *, extra_dirs: Iterable[Path] | None = None) -> Path | None:
    for candidate in get_candidate_file_paths(file_name, extra_dirs=extra_dirs):
        if candidate.exists():
            return candidate
    return None


def resolve_data_file(file_name: str, *, extra_dirs: Iterable[Path] | None = None) -> Path:
    existing = find_existing_data_file(file_name, extra_dirs=extra_dirs)
    if existing is not None:
        return existing

    path = Path(file_name).expanduser()
    if path.is_absolute():
        return path
    return get_preferred_user_data_dir() / path


def resolve_writable_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return get_preferred_user_data_dir() / path


def install_data_file(source_path: str | Path, target_name: str) -> Path:
    source = Path(source_path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Файл не найден: {source}")

    target_path = get_preferred_user_data_dir() / target_name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_path)
    return target_path


def _copy_first_available_file(source_names: Iterable[str], target_name: str) -> str | None:
    target_path = get_preferred_user_data_dir() / target_name
    if target_path.exists():
        return None

    for source_name in source_names:
        source_path = find_existing_data_file(source_name)
        if source_path is None or source_path == target_path:
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        return f"Подготовлен файл {target_name}: {target_path} (источник: {source_path})"

    return None


def bootstrap_runtime_support_files() -> list[str]:
    messages: list[str] = []
    if not (IS_FROZEN and sys.platform == "darwin"):
        return messages

    target_dir = get_preferred_user_data_dir()
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        messages.append(f"Создана рабочая папка macOS: {target_dir}")

    for source_names, target_name in (
        ((DEFAULT_ENV_FILE, DEFAULT_ENV_TEMPLATE_FILE), DEFAULT_ENV_FILE),
        ((DEFAULT_CLIENT_SECRET_FILE,), DEFAULT_CLIENT_SECRET_FILE),
        ((DEFAULT_SYSTEM_PROMPT_FILE,), DEFAULT_SYSTEM_PROMPT_FILE),
    ):
        copied_message = _copy_first_available_file(source_names, target_name)
        if copied_message:
            messages.append(copied_message)

    client_secret_path = target_dir / DEFAULT_CLIENT_SECRET_FILE
    if not client_secret_path.exists():
        easy_access_dir = get_easy_access_data_dir()
        easy_access_hint = ""
        if easy_access_dir is not None:
            easy_access_hint = f" или в {easy_access_dir}"
        messages.append(
            f"Добавьте {DEFAULT_CLIENT_SECRET_FILE} в {target_dir}{easy_access_hint} перед первой авторизацией Google"
        )

    return messages


RUNTIME_BOOTSTRAP_MESSAGES = bootstrap_runtime_support_files()


ENV_FILE = find_existing_data_file(".env")
if ENV_FILE is not None:
    load_dotenv(ENV_FILE)


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    v = get(key, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _first_float(*keys: str, default: float = 0.5) -> float:
    for k in keys:
        raw = get(k, "").strip()
        if raw == "":
            continue
        try:
            return float(raw)
        except ValueError:
            pass
    return default


# Отладка: DEBUG=1 — лог шагов приложения; DEBUG_HTTP=1 — ещё и сырой HTTP (urllib3/httpx)
DEBUG: bool = _env_bool("DEBUG", False)
DEBUG_HTTP: bool = _env_bool("DEBUG_HTTP", False)
PAUSE_ON_EXIT: bool = _env_bool("PAUSE_ON_EXIT", True)


# Google Sheets
SPREADSHEET_ID: str = get("SPREADSHEET_ID")          # ID таблицы из URL
SHEET_MASTER_CV: str = get("SHEET_MASTER_CV", "Master CV")
SHEET_TRACKER: str = get("SHEET_TRACKER", "Tracker")
SHEET_ADDITIONAL_FILTER: str = get("SHEET_ADDITIONAL_FILTER", "Additional Filter")
SHEET_SEARCH_DATABASE: str = get("SHEET_SEARCH_DATABASE", "Search DataBase")
SHEET_BASE_SCORING: str = get("SHEET_BASE_SCORING", "BaseScoring")
SHEET_PRIMARY_FILTER: str = get("SHEET_PRIMARY_FILTER", "Primary Filter")
SHEET_WRONG_PHRASES: str = get("SHEET_WRONG_PHRASES", "WrongPhrases")

COL_URL: str = get("COL_URL", "URL")
COL_DESCRIPTION: str = get("COL_DESCRIPTION", "Description")
COL_ADAPTED_CV: str = get("COL_ADAPTED_CV", "Adapted CV")
COL_BASE_SCORING: str = get("COL_BASE_SCORING", "BaseScoring")
COL_BASE_SCORE_REASON: str = get("COL_BASE_SCORE_REASON", "BaseScoreReason")
COL_ADDITIONAL_SCORING: str = get("COL_ADDITIONAL_SCORING", "AdditionalScoring")
COL_ADD_SCORE_REASON: str = get("COL_ADD_SCORE_REASON", "AddScoreReason")
COL_SUMMARY_SCORING: str = get("COL_SUMMARY_SCORING", "SummaryScoring")
COL_WRONG_PHRASES: str = get("COL_WRONG_PHRASES", "WrongPhrases")
COL_TRACKER_ID: str = get("COL_TRACKER_ID", "TrackerID")
COL_NEW_CV_FILE: str = get("COL_NEW_CV_FILE", "New CV File")

# Google Docs (для адаптированных резюме)
# CV_TEMPLATE_DOC_ID — ID Google Doc шаблона (из Master CV, раздел "CV Doc Template")
# ADAPTED_CVS_FOLDER_ID — ID папки на Drive для хранения созданных резюме (из Master CV)
CV_TEMPLATE_DOC_ID: str = ""  # заполняется из Master CV
ADAPTED_CVS_FOLDER_ID: str = ""  # заполняется из Master CV
ADAPTED_CVS_FOLDER_NAME: str = get("ADAPTED_CVS_FOLDER_NAME", "Adapted_CVs")

# Analyzer
MIN_SUMMARY_SCORE: float = float(get("MIN_SUMMARY_SCORE", "0") or "0")
# SummaryScoring: средневзвешенное BaseScoring и AdditionalScoring (оба 0..100), итог clamp 0..100.
# Веса: BASE_SCORING_WEIGHT и ADDITIONAL_SCORING_WEIGHT; иначе — SUMMARY_* (устаревшие имена).
BASE_SCORING_WEIGHT: float = max(0.0, _first_float("BASE_SCORING_WEIGHT", "SUMMARY_BASE_WEIGHT"))
ADDITIONAL_SCORING_WEIGHT: float = max(0.0, _first_float("ADDITIONAL_SCORING_WEIGHT", "SUMMARY_ADDITIONAL_WEIGHT"))
ANALYZER_HTTP_TIMEOUT_SEC: int = int(get("ANALYZER_HTTP_TIMEOUT_SEC", "30") or "30")
ANALYZER_MAX_DESCRIPTION_CHARS: int = int(get("ANALYZER_MAX_DESCRIPTION_CHARS", "20000") or "20000")
ANALYZER_RATE_LIMIT_SEC: int = int(get("ANALYZER_RATE_LIMIT_SEC", "15") or "15")
# Подробный вывод формул Base/Additional/Summary и таблицы критериев в консоль
ANALYZER_PRINT_SCORE_BREAKDOWN: bool = _env_bool("ANALYZER_PRINT_SCORE_BREAKDOWN", False)

# LinkedIn Search (первая стадия импорта вакансий)
LINKEDIN_CHROME_DEBUG_URL: str = get("LINKEDIN_CHROME_DEBUG_URL", "http://localhost:9222")
LINKEDIN_AUTO_START_BROWSER: bool = _env_bool("LINKEDIN_AUTO_START_BROWSER", True)
LINKEDIN_BROWSER_PATH: str = get("LINKEDIN_BROWSER_PATH", "")
LINKEDIN_BROWSER_USER_DATA_DIR: str = get(
    "LINKEDIN_BROWSER_USER_DATA_DIR",
    str(get_preferred_user_data_dir() / ".chrome-debug-profile"),
)
LINKEDIN_BROWSER_START_URL: str = get("LINKEDIN_BROWSER_START_URL", "https://www.linkedin.com/feed/")
LINKEDIN_SCRAPE_CAP: int = int(get("LINKEDIN_SCRAPE_CAP", "60") or "60")
LINKEDIN_PAGE_LOAD_WAIT_MS: int = int(get("LINKEDIN_PAGE_LOAD_WAIT_MS", "4000") or "4000")
LINKEDIN_NAVIGATION_TIMEOUT_MS: int = int(get("LINKEDIN_NAVIGATION_TIMEOUT_MS", "45000") or "45000")
LINKEDIN_SCROLL_ROUNDS: int = int(get("LINKEDIN_SCROLL_ROUNDS", "4") or "4")
LINKEDIN_CARD_DELAY_SEC: float = float(get("LINKEDIN_CARD_DELAY_SEC", "0.8") or "0.8")
LINKEDIN_PAGE_DELAY_SEC: float = float(get("LINKEDIN_PAGE_DELAY_SEC", "2.0") or "2.0")

# OAuth
CLIENT_SECRET_FILE: str = get("CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_FILE: str = get("TOKEN_FILE", "token.json")
TOKEN_DIR: str = get("TOKEN_DIR", "")

# LLM
LLM_PROVIDER: str = get("LLM_PROVIDER", "gemini")   # gemini | openai | groq | cerebras
LLM_MODEL_GENERATION: str = get("LLM_MODEL_GENERATION", "")
LLM_MODEL_SCORING: str = get("LLM_MODEL_SCORING", "")
GEMINI_API_KEY: str = get("GEMINI_API_KEY")
GEMINI_MODEL: str = get("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_MODEL_GENERATION: str = get("GEMINI_MODEL_GENERATION", "")
GEMINI_MODEL_SCORING: str = get("GEMINI_MODEL_SCORING", "")
OPENAI_API_KEY: str = get("OPENAI_API_KEY")
OPENAI_MODEL: str = get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_GENERATION: str = get("OPENAI_MODEL_GENERATION", "")
OPENAI_MODEL_SCORING: str = get("OPENAI_MODEL_SCORING", "")
GROQ_API_KEY: str = get("GROQ_API_KEY")
GROQ_MODEL: str = get("GROQ_MODEL", "llama3-8b-8192")
GROQ_MODEL_GENERATION: str = get("GROQ_MODEL_GENERATION", "")
GROQ_MODEL_SCORING: str = get("GROQ_MODEL_SCORING", "")
CEREBRAS_API_KEY: str = get("CEREBRAS_API_KEY")
CEREBRAS_MODEL: str = get("CEREBRAS_MODEL", "llama3.1-8b")
CEREBRAS_MODEL_GENERATION: str = get("CEREBRAS_MODEL_GENERATION", "")
CEREBRAS_MODEL_SCORING: str = get("CEREBRAS_MODEL_SCORING", "")
