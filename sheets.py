"""
sheets.py — работа с Google Sheets и Google Docs через OAuth
"""
import logging
import sys
import os
from pathlib import Path
from typing import Optional

import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config

# Добавили документы и Drive для работы с Google Docs и папками
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
_log = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    """Возвращает папку рядом с exe или со скриптом."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _get_token_dir() -> Path:
    """Возвращает стабильную директорию для хранения token.json."""
    if config.TOKEN_DIR:
        path = Path(config.TOKEN_DIR).expanduser()
    elif getattr(sys, "frozen", False):
        path = _get_base_dir()
    else:
        return Path(__file__).resolve().parent

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_token_path() -> Path:
    return _get_token_dir() / config.TOKEN_FILE


def _credentials_have_required_scopes(creds: Credentials) -> bool:
    if not creds or not creds.scopes:
        return False
    required = set(SCOPES)
    actual = set(creds.scopes)
    return required.issubset(actual)


def _load_saved_credentials(token_path: Path) -> Optional[Credentials]:
    if not token_path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception as e:
        _log.debug("OAuth: не удалось прочитать token.json: %s", e)
        return None
    if not creds:
        return None
    if not _credentials_have_required_scopes(creds):
        _log.debug("OAuth: token имеет недостаточные scopes, требуется переавторизация")
        return None

    # Просроченный токен с refresh_token — нормальный кейс, его нужно обновить, а не удалять.
    if creds.expired and creds.refresh_token:
        _log.debug("OAuth: credentials истекли, но доступны для refresh")
        return creds

    if not creds.valid:
        _log.debug("OAuth: credentials невалидны и не могут быть обновлены")
        return None

    return creds


def _authenticate() -> gspread.Client:
    """OAuth-авторизация. При первом запуске открывает браузер."""
    token_path = get_token_path()
    secret_path = _get_base_dir() / config.CLIENT_SECRET_FILE

    _log.debug("OAuth: token_path=%s secret=%s", token_path, secret_path)

    creds: Optional[Credentials] = _load_saved_credentials(token_path)

    if creds is None:
        print(f"[OAuth] Не найден валидный token.json в {token_path}", flush=True)
        if token_path.exists():
            _log.debug("OAuth: удаляем устаревший token.json с неправильными scope")
            try:
                token_path.unlink()
                print(f"[OAuth] Удален устаревший token.json", flush=True)
            except OSError:
                pass

    if creds is None or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            _log.debug("OAuth: refresh access token")
            print("[OAuth] Обновляем токен доступа...", flush=True)
            creds.refresh(Request())
        else:
            if not secret_path.exists():
                raise FileNotFoundError(
                    f"Файл OAuth-credentials не найден: {secret_path}\n"
                    "Скачайте его из Google Cloud Console и положите рядом с программой."
                )
            print("[OAuth] Требуется новая авторизация через браузер", flush=True)
            _log.debug("OAuth: полный логин через браузер (локальный сервер :8080)")
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            print("\nОткрывается браузер для авторизации...", flush=True)
            print("Если браузер не открылся — скопируйте ссылку выше вручную.\n", flush=True)
            creds = flow.run_local_server(
                port=8080,
                open_browser=True,
                timeout_seconds=120,
            )

        token_path.write_text(creds.to_json(), encoding="utf-8")
        print(f"[OAuth] Token сохранён: {token_path}", flush=True)
        _log.debug("OAuth: token сохранён в %s", token_path)

    _log.debug("OAuth: gspread.authorize")
    return gspread.authorize(creds)


# Глобальные объекты для Google APIs
_credentials: Optional[Credentials] = None
_docs_service = None
_drive_service = None


def _get_credentials() -> Credentials:
    """Получить credentials - используются для гуглапи."""
    global _credentials
    if _credentials is None:
        token_path = get_token_path()
        creds = _load_saved_credentials(token_path)
        if creds is None and token_path.exists():
            _log.debug("OAuth: token.json не подходит, удаляем и требуем новую авторизацию")
            try:
                token_path.unlink()
            except OSError:
                pass
            creds = None
        if creds is None:
            # неавторизованная функция должна запускаться через sheets.authenticate
            return None
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        _credentials = creds
    return _credentials


def get_docs_service():
    """Google Docs API service."""
    global _docs_service
    if _docs_service is None:
        creds = _get_credentials()
        if creds:
            _docs_service = build("docs", "v1", credentials=creds)
    return _docs_service


def get_drive_service():
    """Google Drive API service."""
    global _drive_service
    if _drive_service is None:
        creds = _get_credentials()
        if creds:
            _drive_service = build("drive", "v3", credentials=creds)
    return _drive_service


def get_base_cv(client: gspread.Client) -> str:
    """Читает базовое резюме с листа Master CV (всё содержимое листа как текст)."""
    _log.debug("Sheets: open spreadsheet=%s sheet=%s", config.SPREADSHEET_ID, config.SHEET_MASTER_CV)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_MASTER_CV)
    all_values = worksheet.get_all_values()
    # Объединяем все ячейки в один текст
    lines = [" | ".join(row).strip(" |") for row in all_values if any(cell.strip() for cell in row)]
    return "\n".join(lines)


def get_tracker_rows(client: gspread.Client):
    """
    Возвращает список словарей строк Tracker, которые нужно обработать:
    - есть заполненная колонка Description
    - пустая колонка Adapted CV
    Также возвращает worksheet и индексы колонок.
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()

    if not all_values:
        return worksheet, [], {}, []

    headers = all_values[0]

    # Ищем нужные колонки (регистронезависимо)
    col_desc = _find_col(headers, config.COL_DESCRIPTION)
    col_adapted = _find_col(headers, config.COL_ADAPTED_CV)

    if col_desc is None:
        raise ValueError(f"Колонка '{config.COL_DESCRIPTION}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_adapted is None:
        raise ValueError(f"Колонка '{config.COL_ADAPTED_CV}' не найдена в листе Tracker. Заголовки: {headers}")

    col_indices = {"description": col_desc, "adapted_cv": col_adapted}
    rows_to_process = []

    for i, row in enumerate(all_values[1:], start=2):  # start=2 т.к. строка 1 — заголовок
        desc = _cell(row, col_desc)
        adapted = _cell(row, col_adapted)
        if desc and not adapted:
            rows_to_process.append({"row_num": i, "description": desc, "row_data": row})

    return worksheet, rows_to_process, col_indices, headers


def get_tracker_rows_for_analyzer(client: gspread.Client):
    """
    Возвращает строки Tracker, которые должен обработать Analyzer:
    - URL заполнен
    - Description пуст
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()

    if not all_values:
        return worksheet, [], {}, []

    headers = all_values[0]
    col_url = _find_col(headers, config.COL_URL)
    col_desc = _find_col(headers, config.COL_DESCRIPTION)
    col_base = _find_col(headers, config.COL_BASE_SCORING)
    col_add = _find_col(headers, config.COL_ADDITIONAL_SCORING)
    col_sum = _find_col(headers, config.COL_SUMMARY_SCORING)

    if col_url is None:
        raise ValueError(f"Колонка '{config.COL_URL}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_desc is None:
        raise ValueError(f"Колонка '{config.COL_DESCRIPTION}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_base is None:
        raise ValueError(f"Колонка '{config.COL_BASE_SCORING}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_add is None:
        raise ValueError(f"Колонка '{config.COL_ADDITIONAL_SCORING}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_sum is None:
        raise ValueError(f"Колонка '{config.COL_SUMMARY_SCORING}' не найдена в листе Tracker. Заголовки: {headers}")

    col_indices = {
        "url": col_url,
        "description": col_desc,
        "base_scoring": col_base,
        "additional_scoring": col_add,
        "summary_scoring": col_sum,
    }

    rows_to_process = []
    for i, row in enumerate(all_values[1:], start=2):
        url = _cell(row, col_url)
        desc = _cell(row, col_desc)
        if url and not desc:
            rows_to_process.append({"row_num": i, "url": url, "row_data": row})

    return worksheet, rows_to_process, col_indices, headers


def get_tracker_rows_for_adaptation(client: gspread.Client, min_summary_score: float):
    """
    Возвращает строки Tracker, которые должны пойти в адаптацию CV:
    - Description заполнен
    - Adapted CV пуст
    - SummaryScoring >= min_summary_score
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()

    if not all_values:
        return worksheet, [], {}, []

    headers = all_values[0]
    col_desc = _find_col(headers, config.COL_DESCRIPTION)
    col_adapted = _find_col(headers, config.COL_ADAPTED_CV)
    col_sum = _find_col(headers, config.COL_SUMMARY_SCORING)

    if col_desc is None:
        raise ValueError(f"Колонка '{config.COL_DESCRIPTION}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_adapted is None:
        raise ValueError(f"Колонка '{config.COL_ADAPTED_CV}' не найдена в листе Tracker. Заголовки: {headers}")
    if col_sum is None:
        raise ValueError(f"Колонка '{config.COL_SUMMARY_SCORING}' не найдена в листе Tracker. Заголовки: {headers}")

    col_indices = {"description": col_desc, "adapted_cv": col_adapted, "summary_scoring": col_sum}
    rows_to_process = []

    for i, row in enumerate(all_values[1:], start=2):
        desc = _cell(row, col_desc)
        adapted = _cell(row, col_adapted)
        summary_raw = _cell(row, col_sum)
        summary = _to_float(summary_raw)
        if desc and not adapted and summary >= min_summary_score:
            rows_to_process.append(
                {"row_num": i, "description": desc, "summary_scoring": summary, "row_data": row}
            )

    return worksheet, rows_to_process, col_indices, headers


def read_additional_filters(client: gspread.Client):
    """
    Читает лист Additional Filter.
    Ожидаемый формат:
      - строка 1: заголовки
      - col1: criterion_name
      - col2: weight (max points)
      - col3: instruction for numeric mapping
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_ADDITIONAL_FILTER)
    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) == 1:
        return []

    filters = []
    for row in all_values[1:]:
        name = row[0].strip() if len(row) > 0 else ""
        weight_raw = row[1].strip() if len(row) > 1 else ""
        instruction = row[2].strip() if len(row) > 2 else ""
        if not name:
            continue
        weight = _to_float(weight_raw)
        if weight <= 0:
            continue
        filters.append({"name": name, "weight": weight, "instruction": instruction})
    return filters


def write_tracker_description_only(
    worksheet: gspread.Worksheet,
    row_num: int,
    col_description: int,
    description: str,
) -> None:
    """Только текст вакансии в Description (например, если LLM/скоринг недоступен)."""
    worksheet.update_cell(row_num, col_description + 1, description)


def write_analyzer_result(
    worksheet: gspread.Worksheet,
    row_num: int,
    col_indices: dict,
    description: str,
    base_scoring: float,
    additional_scoring: float,
    summary_scoring: float,
) -> None:
    """Пишет результат Analyzer в Tracker одной batch-операцией."""
    updates = [
        (row_num, col_indices["description"] + 1, description),
        (row_num, col_indices["base_scoring"] + 1, _fmt_score(base_scoring)),
        (row_num, col_indices["additional_scoring"] + 1, _fmt_score(additional_scoring)),
        (row_num, col_indices["summary_scoring"] + 1, _fmt_score(summary_scoring)),
    ]
    cells = [gspread.Cell(r, c, v) for (r, c, v) in updates]
    worksheet.update_cells(cells, value_input_option="USER_ENTERED")


def write_adapted_cv(worksheet: gspread.Worksheet, row_num: int, col_adapted: int, text: str) -> None:
    """Записывает адаптированное резюме в нужную ячейку."""
    worksheet.update_cell(row_num, col_adapted + 1, text)  # gspread: колонки с 1


def read_wrong_phrases(client: gspread.Client) -> list[str]:
    """
    Читает список запрещённых фраз из листа WrongPhrases.
    Ожидается: колонка А содержит фразы (по одной на строку).
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_WRONG_PHRASES)
    all_values = worksheet.get_all_values()
    
    phrases = []
    for row in all_values:
        if row and row[0].strip():
            phrases.append(row[0].strip())
    
    return phrases


def get_search_database_rows(client: gspread.Client):
    """
    Читает строки из листа Search DataBase для анализа:
    - Description заполнен
    - SummaryScoring пуст
    Возвращает: (worksheet, rows, col_indices, headers)
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_SEARCH_DATABASE)
    all_values = worksheet.get_all_values()

    if not all_values:
        return worksheet, [], {}, []

    headers = all_values[0]
    
    # Найти нужные колонки
    col_desc = _find_col(headers, config.COL_DESCRIPTION)
    col_base = _find_col(headers, config.COL_BASE_SCORING)
    col_add = _find_col(headers, config.COL_ADDITIONAL_SCORING)
    col_sum = _find_col(headers, config.COL_SUMMARY_SCORING)
    col_wrong = _find_col(headers, config.COL_WRONG_PHRASES)
    col_tracker_id = _find_col(headers, config.COL_TRACKER_ID)

    if col_desc is None:
        raise ValueError(f"Колонка '{config.COL_DESCRIPTION}' не найдена в листе {config.SHEET_SEARCH_DATABASE}. Заголовки: {headers}")
    if col_base is None:
        raise ValueError(f"Колонка '{config.COL_BASE_SCORING}' не найдена в листе {config.SHEET_SEARCH_DATABASE}. Заголовки: {headers}")
    if col_add is None:
        raise ValueError(f"Колонка '{config.COL_ADDITIONAL_SCORING}' не найдена в листе {config.SHEET_SEARCH_DATABASE}. Заголовки: {headers}")
    if col_sum is None:
        raise ValueError(f"Колонка '{config.COL_SUMMARY_SCORING}' не найдена в листе {config.SHEET_SEARCH_DATABASE}. Заголовки: {headers}")

    col_indices = {
        "description": col_desc,
        "base_scoring": col_base,
        "additional_scoring": col_add,
        "summary_scoring": col_sum,
        "wrong_phrases": col_wrong,
        "tracker_id": col_tracker_id,
    }

    rows_to_process = []
    for i, row in enumerate(all_values[1:], start=2):
        desc = _cell(row, col_desc)
        summary = _cell(row, col_sum)
        # Обработать, если Description заполнен, но SummaryScoring пуст
        if desc and not summary:
            rows_to_process.append({"row_num": i, "description": desc, "row_data": row})

    return worksheet, rows_to_process, col_indices, headers


def write_search_database_result(
    worksheet: gspread.Worksheet,
    row_num: int,
    col_indices: dict,
    base_scoring: float,
    additional_scoring: float,
    summary_scoring: float,
    wrong_phrases_flag: int = 0,
) -> None:
    """Записывает результат анализа в Search DataBase."""
    updates = [
        (row_num, col_indices["base_scoring"] + 1, _fmt_score(base_scoring)),
        (row_num, col_indices["additional_scoring"] + 1, _fmt_score(additional_scoring)),
        (row_num, col_indices["summary_scoring"] + 1, _fmt_score(summary_scoring)),
    ]
    
    # Если есть колонка WrongPhrases, добавить флаг
    if col_indices.get("wrong_phrases") is not None:
        updates.append((row_num, col_indices["wrong_phrases"] + 1, wrong_phrases_flag))
    
    cells = [gspread.Cell(r, c, v) for (r, c, v) in updates]
    worksheet.update_cells(cells, value_input_option="USER_ENTERED")


def get_next_tracker_id(client: gspread.Client) -> int:
    """Получает следующий доступный ID для листа Tracker."""
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()

    if not all_values or len(all_values) == 1:
        return 1

    headers = all_values[0]
    col_id = _find_col(headers, "ID")
    
    if col_id is None:
        # Если колонки ID нет, просто считаем количество строк
        return len(all_values)

    max_id = 0
    for row in all_values[1:]:
        id_str = _cell(row, col_id)
        if id_str:
            try:
                row_id = int(id_str)
                max_id = max(max_id, row_id)
            except ValueError:
                pass

    return max_id + 1


def add_row_to_tracker(
    client: gspread.Client,
    row_id: int,
    row_data: dict,
) -> None:
    """
    Добавляет новую строку в лист Tracker.
    row_data должен содержать следующие поля:
    - timestamp, title, company, location, url, source, description, 
    - base_scoring, additional_scoring, summary_scoring, tracker_id
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()

    if not all_values:
        raise ValueError(f"Лист {config.SHEET_TRACKER} пуст или не найден")

    headers = all_values[0]
    
    # Подготовить значения для всех колонок
    new_row = [""] * len(headers)
    
    # Маппинг требуемых колонок
    col_mapping = {
        "ID": row_id,
        config.COL_DESCRIPTION: row_data.get("description", ""),
        config.COL_BASE_SCORING: _fmt_score(row_data.get("base_scoring", 0.0)),
        config.COL_ADDITIONAL_SCORING: _fmt_score(row_data.get("additional_scoring", 0.0)),
        config.COL_SUMMARY_SCORING: _fmt_score(row_data.get("summary_scoring", 0.0)),
        config.COL_TRACKER_ID: row_id,
    }
    
    # Заполнить стандартные поля, если есть
    optional_fields = {
        "Timestamp": row_data.get("timestamp", ""),
        "Title": row_data.get("title", ""),
        "Company": row_data.get("company", ""),
        "Location": row_data.get("location", ""),
        config.COL_URL: row_data.get("url", ""),
        "Source": row_data.get("source", ""),
    }
    
    col_mapping.update(optional_fields)
    
    # Найти индексы колонок и заполнить значения
    for col_idx, header in enumerate(headers):
        for col_name, value in col_mapping.items():
            if header.strip().lower() == col_name.strip().lower():
                new_row[col_idx] = value
                break
    
    worksheet.append_row(new_row, value_input_option="USER_ENTERED")


def update_search_database_tracker_id(
    worksheet: gspread.Worksheet,
    row_num: int,
    col_tracker_id: int,
    tracker_id: int,
) -> None:
    """Обновляет колонку TrackerID в Search DataBase."""
    worksheet.update_cell(row_num, col_tracker_id + 1, tracker_id)


# ── helpers ───────────────────────────────────────────────────────────────────

def _find_col(headers: list, name: str) -> Optional[int]:
    """Возвращает 0-based индекс колонки по имени (регистронезависимо)."""
    name_lower = name.strip().lower()
    for i, h in enumerate(headers):
        if h.strip().lower() == name_lower:
            return i
    return None


def _cell(row: list, index: int) -> str:
    """Безопасно получает значение ячейки."""
    try:
        return row[index].strip()
    except IndexError:
        return ""


def _to_float(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value.replace("%", "").replace(",", ".").strip())
    except ValueError:
        return 0.0


def _fmt_score(score: float) -> float:
    # Храним как число (не строка с %), чтобы было удобно фильтровать в Sheets
    if score != score:  # NaN
        return 0.0
    return max(0.0, min(100.0, float(score)))


def authenticate() -> gspread.Client:
    return _authenticate()


# ── Google Docs & Drive Functions ──────────────────────────────────────────

def get_master_cv_metadata(client: gspread.Client) -> dict:
    """Читает специальные поля из листа Master CV (обе колонки A и B).
    
    Ожидает структуру:
      "Master CV" -> содержание базового резюме
      "CV Doc Template" -> ссылка на Google Doc с шаблоном
      "System_prompt" -> текст системного промпта
      "Adapted_CVs_Folder" -> ID папки для хранения резюме (опционально)
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_MASTER_CV)
    all_values = worksheet.get_all_values()
    
    result = {
        "master_cv_text": "",
        "template_doc_id": "",
        "system_prompt": "",
        "adapted_cvs_folder_id": "",
    }
    
    # Предполагаем col A - название раздела, col B - значение
    for row in all_values:
        if len(row) < 2:
            continue
        label = row[0].strip().lower()
        value = row[1].strip()
        
        if label == "master cv":
            result["master_cv_text"] = value
        elif label == "cv doc template":
            # Может быть либо полная ссылка, либо просто ID
            if "/d/" in value:
                result["template_doc_id"] = value.split("/d/")[1].split("/")[0]
            else:
                result["template_doc_id"] = value
        elif label == "system_prompt":
            result["system_prompt"] = value
        elif label == "adapted_cvs_folder":
            if "/folders/" in value:
                result["adapted_cvs_folder_id"] = value.split("/folders/")[1]
            else:
                result["adapted_cvs_folder_id"] = value
    
    return result


def copy_google_doc(template_doc_id: str, new_title: str, folder_id: str = None) -> str:
    """Копирует Google Doc. Возвращает ID нового документа."""
    drive = get_drive_service()
    if not drive:
        raise RuntimeError("Google Drive API не инициализирован (нет credentials)")
    
    try:
        file_metadata = {"name": new_title}
        if folder_id:
            file_metadata["parents"] = [folder_id]
        
        result = drive.files().copy(
            fileId=template_doc_id,
            body=file_metadata,
            fields="id"
        ).execute()
        
        new_doc_id = result.get("id")
        _log.debug("Скопирован документ: %s -> %s (%s)", template_doc_id, new_title, new_doc_id)
        return new_doc_id
    except Exception as e:
        _log.error("Ошибка копирования документа: %s", e)
        raise


def get_doc_link(doc_id: str) -> str:
    """Формирует ссылку на Google Doc."""
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def update_tracker_new_cv_file(
    worksheet: gspread.Worksheet,
    row_num: int,
    headers: list,
    doc_link: str,
) -> None:
    """Обновляет колонку New CV File в Tracker."""
    col = _find_col(headers, config.COL_NEW_CV_FILE)
    if col is not None:
        worksheet.update_cell(row_num, col + 1, doc_link)