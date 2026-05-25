"""
sheets.py — работа с Google Sheets и Google Docs через OAuth
"""
import logging
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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

def _get_token_dir() -> Path:
    """Возвращает стабильную директорию для хранения token.json."""
    if config.TOKEN_DIR:
        path = config.resolve_writable_path(config.TOKEN_DIR)
    elif getattr(sys, "frozen", False) and sys.platform == "darwin":
        path = config.get_preferred_user_data_dir()
    elif getattr(sys, "frozen", False):
        path = config.BASE_DIR
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
    secret_path = config.find_existing_data_file(config.CLIENT_SECRET_FILE)

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
            if secret_path is None:
                searched_paths = config.get_candidate_file_paths(config.CLIENT_SECRET_FILE)
                searched_lines = "\n".join(f"  - {path}" for path in searched_paths)
                macos_hint = ""
                if getattr(sys, "frozen", False) and sys.platform == "darwin":
                    preferred_path = config.resolve_data_file(config.CLIENT_SECRET_FILE)
                    easy_access_path = None
                    easy_access_dir = config.get_easy_access_data_dir()
                    if easy_access_dir is not None:
                        easy_access_path = easy_access_dir / config.CLIENT_SECRET_FILE
                    easy_access_hint = f"\nИли в более простую папку: {easy_access_path}" if easy_access_path else ""
                    macos_hint = (
                        "\nНа macOS файл рядом с .app может не находиться из-за App Translocation."
                        f"\nПоложите client_secret.json сюда: {preferred_path}"
                        f"{easy_access_hint}"
                        "\nИли укажите абсолютный путь через CLIENT_SECRET_FILE в .env."
                    )
                raise FileNotFoundError(
                    "Файл OAuth-credentials не найден.\n"
                    f"Проверены пути:\n{searched_lines}"
                    f"{macos_hint}"
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
_sheets_service = None
_master_cv_doc_cache: dict[str, str] = {}


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


def get_sheets_service():
    """Google Sheets API service (low-level, для чтения rich hyperlink метаданных)."""
    global _sheets_service
    if _sheets_service is None:
        creds = _get_credentials()
        if creds:
            _sheets_service = build("sheets", "v4", credentials=creds)
    return _sheets_service


def _looks_like_folder_id(value: str) -> bool:
    return _looks_like_doc_id(value)


def _resolve_drive_folder_id(folder_value: str) -> str:
    folder_value = (folder_value or "").strip()
    if not folder_value:
        return ""

    if "/folders/" in folder_value:
        return folder_value.split("/folders/")[1].split("?")[0].split("/")[0]

    if _looks_like_folder_id(folder_value):
        return folder_value

    drive = get_drive_service()
    if not drive:
        _log.warning("Drive service недоступен, не удалось разрешить папку по имени: %s", folder_value)
        return ""

    query = (
        "mimeType='application/vnd.google-apps.folder' and "
        f"name='{folder_value.replace("'", "\\'")}' and trashed=false"
    )
    response = drive.files().list(
        q=query,
        spaces="drive",
        fields="files(id,name)",
        pageSize=10,
    ).execute()
    folders = response.get("files", [])
    if not folders:
        _log.warning("Папка Drive не найдена по имени: %s", folder_value)
        return ""

    if len(folders) > 1:
        _log.warning(
            "Найдено несколько папок Drive с именем %r, используется первая: %s",
            folder_value,
            folders[0].get("id", ""),
        )

    return folders[0].get("id", "")


def get_base_cv(client: gspread.Client) -> str:
    """
    Читает базовое резюме с листа Master CV.
    Извлекает только содержимое CV, исключая служебные строки (System_prompt*, CV Doc Template, и т.п.).
    """
    _log.debug("Sheets: open spreadsheet=%s sheet=%s", config.SPREADSHEET_ID, config.SHEET_MASTER_CV)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_MASTER_CV)
    all_values = worksheet.get_all_values()
    
    # Список ярлыков служебных строк (их второе значение не входит в CV)
    metadata_labels = {
        "system_prompt",
        "cv doc template",
        "adapted_cvs_folder",
    }
    # Все ярлыки, которые начинаются с system_prompt_ (например system_prompt_nl_hook)
    metadata_prefixes = ("system_prompt_", "cv_doc_template")
    
    cv_lines = []
    
    for row in all_values:
        if not any(cell.strip() for cell in row):
            # Пустая строка
            continue
        
        # Получаем первый элемент (ярлык) и нормализуем для сравнения
        label = (row[0] or "").strip().lower()
        
        # Пропускаем явные метаданные
        if label in metadata_labels:
            continue
        if label.startswith(metadata_prefixes):
            continue
        
        # Добавляем строку в CV
        line = " | ".join(row).strip(" |")
        cv_lines.append(line)
    
    base_cv = "\n".join(cv_lines)
    _log.debug(
        "Sheets: base CV extraction mode=content_only lines=%d length=%d",
        len(cv_lines),
        len(base_cv),
    )
    return base_cv


def _extract_google_doc_id(value: str) -> str:
    """Извлекает Google Doc ID из URL/формулы/сырых значений."""
    text = (value or "").strip()
    if not text:
        return ""

    if _looks_like_doc_id(text):
        return text

    # Формула вида =HYPERLINK("https://docs.google.com/document/d/<ID>/edit", "Label")
    formula_url_match = re.search(r'HYPERLINK\(\s*"([^"]+)"', text, flags=re.IGNORECASE)
    if formula_url_match:
        text = formula_url_match.group(1).strip()

    url_match = re.search(r"/document/d/([A-Za-z0-9_-]{25,})", text)
    if url_match:
        return url_match.group(1)

    # Иногда URL может быть без /edit и с query params
    docs_url_match = re.search(r"docs\.google\.com/document/[^\s]*", text)
    if docs_url_match:
        tail = docs_url_match.group(0)
        url_match = re.search(r"/d/([A-Za-z0-9_-]{25,})", tail)
        if url_match:
            return url_match.group(1)

    return ""


def _find_first_doc_url(value: Any) -> str:
    """Рекурсивно ищет первую ссылку на Google Doc в произвольной структуре cellData."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text.startswith("http://") or text.startswith("https://"):
            if "docs.google.com/document" in text:
                return text
            return ""
        match = re.search(r"https?://docs\.google\.com/document/[^\s\"'>)]+", text)
        if match:
            return match.group(0)
        return ""

    if isinstance(value, dict):
        for nested in value.values():
            found = _find_first_doc_url(nested)
            if found:
                return found
        return ""

    if isinstance(value, list):
        for item in value:
            found = _find_first_doc_url(item)
            if found:
                return found
        return ""

    return ""


def _extract_link_from_cell_data(cell_data: dict[str, Any]) -> str:
    """Извлекает URL из cellData (rich hyperlink, text format runs, formula hyperlink)."""
    if not isinstance(cell_data, dict):
        return ""

    hyperlink = (cell_data.get("hyperlink") or "").strip()
    if hyperlink:
        return hyperlink

    for run in cell_data.get("textFormatRuns") or []:
        if not isinstance(run, dict):
            continue
        fmt = run.get("format") or {}
        if not isinstance(fmt, dict):
            continue
        link = fmt.get("link") or {}
        if not isinstance(link, dict):
            continue
        uri = (link.get("uri") or "").strip()
        if uri:
            return uri

    # Smart chips / rich links (новые типы ссылок в Google Sheets)
    for chip_run in cell_data.get("chipRuns") or []:
        if not isinstance(chip_run, dict):
            continue
        chip = chip_run.get("chip") or {}
        if not isinstance(chip, dict):
            continue

        rich_link = chip.get("richLinkProperties") or {}
        if isinstance(rich_link, dict):
            uri = (rich_link.get("uri") or "").strip()
            if uri:
                return uri

        # fallback на случай отличающейся структуры в API
        found_chip_url = _find_first_doc_url(chip)
        if found_chip_url:
            return found_chip_url

    user_entered = cell_data.get("userEnteredValue") or {}
    if isinstance(user_entered, dict):
        formula_value = (user_entered.get("formulaValue") or "").strip()
        if formula_value:
            formula_url_match = re.search(
                r'HYPERLINK\(\s*"([^"]+)"', formula_value, flags=re.IGNORECASE
            )
            if formula_url_match:
                return formula_url_match.group(1).strip()

    # fallback: если ячейка хранит URL как plain text
    formatted_value = (cell_data.get("formattedValue") or "").strip()
    if formatted_value.startswith("http://") or formatted_value.startswith("https://"):
        return formatted_value

    # Последний fallback: обойти все поля cellData и попробовать найти docs URL рекурсивно
    deep_found = _find_first_doc_url(cell_data)
    if deep_found:
        return deep_found

    return ""


def _get_master_cv_col_b_links() -> dict[int, str]:
    """Возвращает маппинг row_num -> URL из колонки B листа Master CV (включая rich links)."""
    sheets_service = get_sheets_service()
    if not sheets_service:
        _log.debug("Sheets API service недоступен: rich hyperlinks не будут извлечены")
        return {}

    safe_sheet_name = config.SHEET_MASTER_CV.replace("'", "''")
    source_range = f"'{safe_sheet_name}'!A:C"

    try:
        response = (
            sheets_service.spreadsheets()
            .get(
                spreadsheetId=config.SPREADSHEET_ID,
                ranges=[source_range],
                includeGridData=True,
                fields=(
                    "sheets(data(rowData(values("
                    "formattedValue,hyperlink,textFormatRuns(format(link)),"
                    "chipRuns(chip),userEnteredValue"
                    "))))"
                ),
            )
            .execute()
        )
    except Exception as error:
        _log.warning("Не удалось прочитать rich hyperlinks из %s: %s", config.SHEET_MASTER_CV, error)
        return {}

    links: dict[int, str] = {}
    for sheet in response.get("sheets", []):
        for data in sheet.get("data", []):
            row_data = data.get("rowData") or []
            for idx, row in enumerate(row_data, start=1):
                values = row.get("values") or []
                if len(values) < 2:
                    continue
                link = _extract_link_from_cell_data(values[1])
                if link:
                    links[idx] = link
    return links


def get_master_cv_variants(client: gspread.Client) -> list[dict[str, Any]]:
    """Читает варианты резюме из листа Master CV (строки Master_CV_*).

    Ожидаемая структура:
    - Колонка A: имя записи, начинается с Master_CV_
    - Колонка B: ссылка/ID Google Doc с текстом резюме
    - Колонка C: маска поиска по title (или '*')
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_MASTER_CV)
    all_values = worksheet.get_all_values()
    col_b_links = _get_master_cv_col_b_links()

    variants: list[dict[str, Any]] = []
    for row_num, row in enumerate(all_values, start=1):
        name = (row[0] if len(row) > 0 else "").strip()
        if not name or not name.lower().startswith("master_cv_"):
            continue

        title_mask = (row[2] if len(row) > 2 else "").strip()
        if not title_mask:
            _log.warning(
                "Master CV: строка %s (%s) пропущена: пустая маска в колонке C",
                row_num,
                name,
            )
            continue

        col_b_text = (row[1] if len(row) > 1 else "").strip()
        doc_ref = (col_b_links.get(row_num) or col_b_text).strip()
        doc_id = _extract_google_doc_id(doc_ref)
        if not doc_id:
            _log.warning(
                "Master CV: строка %s (%s) пропущена: не удалось извлечь Doc ID из колонки B (%r)",
                row_num,
                name,
                doc_ref or col_b_text,
            )
            continue

        variants.append(
            {
                "name": name,
                "title_mask": title_mask,
                "doc_id": doc_id,
                "doc_ref": doc_ref,
                "row_num": row_num,
            }
        )

    if not variants:
        raise ValueError(
            "Не найдены валидные строки Master_CV_* в листе Master CV "
            "(A=имя Master_CV_*, B=ссылка/ID Google Doc, C=маска title)."
        )

    return variants


def select_master_cv_for_title(master_cv_variants: list[dict[str, Any]], title: str) -> dict[str, Any]:
    """Выбирает подходящий вариант CV по title.

    Правила:
    - ищем contains(match) без учета регистра по маскам из колонки C, кроме '*'
    - если нет совпадений, используем запись с маской '*'
    - если и '*' нет, используем первую запись списка
    """
    if not master_cv_variants:
        raise ValueError("Список вариантов Master CV пуст")

    title_norm = (title or "").strip().lower()
    defaults = [v for v in master_cv_variants if str(v.get("title_mask", "")).strip() == "*"]

    matches: list[dict[str, Any]] = []
    if title_norm:
        for variant in master_cv_variants:
            mask = str(variant.get("title_mask", "")).strip()
            if not mask or mask == "*":
                continue
            if mask.lower() in title_norm:
                matches.append(variant)

    if matches:
        return {
            "variant": matches[0],
            "reason": "matched",
            "multiple_matches": len(matches) > 1,
            "multiple_defaults": len(defaults) > 1,
            "matched_count": len(matches),
            "default_count": len(defaults),
        }

    if defaults:
        return {
            "variant": defaults[0],
            "reason": "fallback_star",
            "multiple_matches": False,
            "multiple_defaults": len(defaults) > 1,
            "matched_count": 0,
            "default_count": len(defaults),
        }

    return {
        "variant": master_cv_variants[0],
        "reason": "fallback_first",
        "multiple_matches": False,
        "multiple_defaults": False,
        "matched_count": 0,
        "default_count": 0,
    }


def _extract_text_from_doc_elements(elements: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for element in elements or []:
        paragraph = element.get("paragraph")
        if isinstance(paragraph, dict):
            for paragraph_element in paragraph.get("elements", []):
                text_run = paragraph_element.get("textRun") or {}
                if isinstance(text_run, dict):
                    chunks.append(text_run.get("content", ""))

        table = element.get("table")
        if isinstance(table, dict):
            for table_row in table.get("tableRows", []):
                for table_cell in table_row.get("tableCells", []):
                    chunks.append(_extract_text_from_doc_elements(table_cell.get("content", [])))

        toc = element.get("tableOfContents")
        if isinstance(toc, dict):
            chunks.append(_extract_text_from_doc_elements(toc.get("content", [])))

    return "".join(chunks)


def get_google_doc_text(doc_id: str) -> str:
    """Читает plain text из Google Doc по document ID."""
    docs = get_docs_service()
    if not docs:
        raise RuntimeError("Google Docs API не инициализирован (нет credentials)")

    try:
        document = docs.documents().get(documentId=doc_id).execute()
    except Exception as error:
        raise RuntimeError(f"Не удалось прочитать Google Doc {doc_id}: {error}") from error

    body_content = (document.get("body") or {}).get("content") or []
    text = _extract_text_from_doc_elements(body_content).replace("\u000b", "\n").strip()
    if not text:
        raise ValueError(f"Google Doc {doc_id} пуст или не содержит текст")
    return text


def get_master_cv_text_for_variant(variant: dict[str, Any]) -> str:
    """Возвращает текст резюме для выбранного варианта Master CV (с кэшем на запуск)."""
    doc_id = str(variant.get("doc_id", "")).strip()
    if not doc_id:
        raise ValueError(f"У варианта {variant.get('name', '')} отсутствует doc_id")

    if doc_id in _master_cv_doc_cache:
        return _master_cv_doc_cache[doc_id]

    text = get_google_doc_text(doc_id)
    _master_cv_doc_cache[doc_id] = text
    return text


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


def get_tracker_rows_for_manual_scoring(client: gspread.Client):
    """
    Возвращает строки Tracker для ручного скоринга:
    - Description заполнен
    - SummaryScoring пуст

    Для совместимости с разными таблицами:
    - Description и SummaryScoring используются как критерий отбора
    - Остальные колонки скоринга опциональны
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()

    if not all_values:
        return worksheet, [], {}, []

    headers = all_values[0]

    col_desc = _find_col(headers, config.COL_DESCRIPTION)
    col_sum = _find_col(headers, config.COL_SUMMARY_SCORING)

    # Без этих колонок невозможно корректно отобрать строки под критерий задачи.
    if col_desc is None or col_sum is None:
        return worksheet, [], {}, headers

    col_title = _find_col(headers, "Title")
    col_base = _find_col(headers, config.COL_BASE_SCORING)
    col_base_reason = _find_col(headers, config.COL_BASE_SCORE_REASON)
    col_add = _find_col(headers, config.COL_ADDITIONAL_SCORING)
    col_add_reason = _find_col(headers, config.COL_ADD_SCORE_REASON)
    col_wrong = _find_col(headers, config.COL_WRONG_PHRASES)
    col_selected_cv = _find_col(headers, "Selected_CV")
    col_gap_analysis = _find_col(headers, "Gap_Analysis")

    col_indices = {
        "description": col_desc,
        "summary_scoring": col_sum,
        "title": col_title,
        "base_scoring": col_base,
        "base_score_reason": col_base_reason,
        "additional_scoring": col_add,
        "add_score_reason": col_add_reason,
        "wrong_phrases": col_wrong,
        "selected_cv": col_selected_cv,
        "gap_analysis": col_gap_analysis,
    }

    rows_to_process = []
    for i, row in enumerate(all_values[1:], start=2):
        desc = _cell(row, col_desc)
        summary = _cell(row, col_sum)
        if desc and not summary:
            title = _cell(row, col_title) if col_title is not None else ""
            rows_to_process.append(
                {
                    "row_num": i,
                    "description": desc,
                    "title": title,
                    "row_data": row,
                }
            )

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


def get_base_scoring_system_prompt(client: gspread.Client) -> str:
    """
    Читает системный промпт для BaseScoring с листа BaseScoring.
    Ожидаемый формат: строка, где в колонке A лежит "SystemPrompt",
    а текст промпта лежит в колонке B.
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_BASE_SCORING)
    all_values = worksheet.get_all_values()

    for row in all_values:
        key = row[0].strip() if len(row) > 0 else ""
        if key.lower() != "systemprompt":
            continue
        prompt = row[1].strip() if len(row) > 1 else ""
        if prompt:
            return prompt
        break

    raise ValueError(
        f"На листе '{config.SHEET_BASE_SCORING}' не найдена заполненная строка "
        "с ключом 'SystemPrompt' в колонке A и текстом в колонке B"
    )


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
    col_base_reason = _find_col(headers, config.COL_BASE_SCORE_REASON)
    col_add = _find_col(headers, config.COL_ADDITIONAL_SCORING)
    col_add_reason = _find_col(headers, config.COL_ADD_SCORE_REASON)
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
        "base_score_reason": col_base_reason,
        "additional_scoring": col_add,
        "add_score_reason": col_add_reason,
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
    base_score_reason: str = "",
    add_score_reason: str = "",
    wrong_phrases_flag: int = 0,
) -> None:
    """Записывает результат анализа в Search DataBase."""
    updates = [
        (row_num, col_indices["base_scoring"] + 1, _fmt_score(base_scoring)),
        (row_num, col_indices["additional_scoring"] + 1, _fmt_score(additional_scoring)),
        (row_num, col_indices["summary_scoring"] + 1, _fmt_score(summary_scoring)),
    ]

    if col_indices.get("base_score_reason") is not None:
        updates.append((row_num, col_indices["base_score_reason"] + 1, (base_score_reason or "").strip()))

    if col_indices.get("add_score_reason") is not None:
        updates.append((row_num, col_indices["add_score_reason"] + 1, (add_score_reason or "").strip()))
    
    # Если есть колонка WrongPhrases, добавить флаг
    if col_indices.get("wrong_phrases") is not None:
        updates.append((row_num, col_indices["wrong_phrases"] + 1, wrong_phrases_flag))
    
    cells = [gspread.Cell(r, c, v) for (r, c, v) in updates]
    worksheet.update_cells(cells, value_input_option="USER_ENTERED")


def write_tracker_manual_scoring_result(
    worksheet: gspread.Worksheet,
    row_num: int,
    col_indices: dict,
    base_scoring: float,
    additional_scoring: float,
    summary_scoring: float,
    base_score_reason: str = "",
    add_score_reason: str = "",
    wrong_phrases_flag: int | None = None,
    selected_cv: str = "",
    gap_analysis: str = "",
) -> None:
    """Записывает результаты ручного скоринга в Tracker только в существующие колонки."""
    updates: list[tuple[int, int, Any]] = []

    if col_indices.get("base_scoring") is not None:
        updates.append((row_num, col_indices["base_scoring"] + 1, _fmt_score(base_scoring)))

    if col_indices.get("additional_scoring") is not None:
        updates.append((row_num, col_indices["additional_scoring"] + 1, _fmt_score(additional_scoring)))

    if col_indices.get("summary_scoring") is not None:
        updates.append((row_num, col_indices["summary_scoring"] + 1, _fmt_score(summary_scoring)))

    if col_indices.get("base_score_reason") is not None:
        updates.append((row_num, col_indices["base_score_reason"] + 1, (base_score_reason or "").strip()))

    if col_indices.get("add_score_reason") is not None:
        updates.append((row_num, col_indices["add_score_reason"] + 1, (add_score_reason or "").strip()))

    if wrong_phrases_flag is not None and col_indices.get("wrong_phrases") is not None:
        updates.append((row_num, col_indices["wrong_phrases"] + 1, wrong_phrases_flag))

    if col_indices.get("selected_cv") is not None and selected_cv:
        updates.append((row_num, col_indices["selected_cv"] + 1, selected_cv.strip()))

    if col_indices.get("gap_analysis") is not None and gap_analysis:
        updates.append((row_num, col_indices["gap_analysis"] + 1, gap_analysis.strip()))

    if not updates:
        _log.debug("Tracker manual scoring: нет доступных колонок для записи (строка %s)", row_num)
        return

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
    transfer_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    col_mapping = {
        "ID": row_id,
        config.COL_DESCRIPTION: row_data.get("description", ""),
        config.COL_BASE_SCORING: _fmt_score(row_data.get("base_scoring", 0.0)),
        config.COL_BASE_SCORE_REASON: row_data.get("base_score_reason", ""),
        config.COL_ADDITIONAL_SCORING: _fmt_score(row_data.get("additional_scoring", 0.0)),
        config.COL_ADD_SCORE_REASON: row_data.get("add_score_reason", ""),
        config.COL_SUMMARY_SCORING: _fmt_score(row_data.get("summary_scoring", 0.0)),
        config.COL_TRACKER_ID: row_id,
        "DateTime": row_data.get("datetime", transfer_dt),
        "Selected_CV": row_data.get("selected_cv", ""),
        "Gap_Analysis": row_data.get("gap_analysis", ""),
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

def _looks_like_doc_id(value: str) -> bool:
    """Проверяет, похоже ли значение на настоящий Google Doc/Drive ID.
    Реальный ID: 25-60 символов, только буквы, цифры, дефисы и подчёркивания.
    """
    return bool(value and 25 <= len(value) <= 60 and re.fullmatch(r"[A-Za-z0-9_\-]+", value))


def get_master_cv_metadata(client: gspread.Client) -> dict:
    """Читает специальные поля из листа Master CV (обе колонки A и B).
    
    Ожидает структуру:
      "Master CV" -> содержание базового резюме
      "CV Doc Template" -> ссылка на Google Doc с шаблоном
            "System_prompt" или "System_prompt_*" -> текст системного промпта
      "Adapted_CVs_Folder" -> ID папки для хранения резюме (опционально)
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_MASTER_CV)
    all_values = worksheet.get_all_values()
    col_b_links = _get_master_cv_col_b_links()
    
    result = {
        "master_cv_text": "",
        "template_doc_id": "",
        "system_prompt": "",
        "system_prompt_label": "",
        "adapted_cvs_folder_id": "",
        "applicant": {
            "name": "",
            "email": "",
            "phone": "",
            "linkedin": "",
        },
    }
    prompt_rows: list[tuple[str, str]] = []
    preferred_label = (config.MASTER_CV_SYSTEM_PROMPT_LABEL or "System_prompt").strip().lower()
    
    # Предполагаем col A - название раздела, col B - значение
    for row_num, row in enumerate(all_values, start=1):
        if len(row) < 2:
            continue
        label = row[0].strip().lower()
        value = row[1].strip()
        
        if label == "master cv":
            result["master_cv_text"] = value
        elif label == "cv doc template":
            # Для rich links (smart chips) в колонке B берём ссылку из cellData,
            # иначе используем plain text из get_all_values().
            template_ref = (col_b_links.get(row_num) or value).strip()
            doc_id = _extract_google_doc_id(template_ref)
            if doc_id:
                result["template_doc_id"] = doc_id
            else:
                _log.warning(
                    "Master CV: значение 'CV Doc Template' = %r (row=%s, raw=%r) не похоже на Google Doc URL или ID. "
                    "Укажите полную ссылку вида https://docs.google.com/document/d/ВАШ_ID/edit "
                    "или просто ID документа (длинная строка из букв и цифр).",
                    template_ref,
                    row_num,
                    value,
                )
                result["template_doc_id"] = ""
        elif label == preferred_label or label == "system_prompt" or label.startswith("system_prompt_"):
            if value:
                prompt_rows.append((label, value))
        elif label == "adapted_cvs_folder":
            if "/folders/" in value:
                result["adapted_cvs_folder_id"] = value.split("/folders/")[1]
            else:
                result["adapted_cvs_folder_id"] = value
        elif label == "applicant name":
            result["applicant"]["name"] = value
        elif label == "applicant email":
            result["applicant"]["email"] = value
        elif label == "applicant phone":
            result["applicant"]["phone"] = value
        elif label == "applicant linkedin":
            result["applicant"]["linkedin"] = value

    prompt_map = {label: value for label, value in prompt_rows}

    if preferred_label in prompt_map:
        result["system_prompt"] = prompt_map[preferred_label]
        result["system_prompt_label"] = preferred_label
    elif "system_prompt" in prompt_map:
        result["system_prompt"] = prompt_map["system_prompt"]
        result["system_prompt_label"] = "system_prompt"
    elif prompt_rows:
        # Fallback: берём первый найденный System_prompt_* в порядке строк листа.
        result["system_prompt_label"] = prompt_rows[0][0]
        result["system_prompt"] = prompt_rows[0][1]

    if result["template_doc_id"]:
        _log.info("Master CV: используется CV Doc Template id=%s", result["template_doc_id"])
    
    return result


def copy_google_doc(template_doc_id: str, new_title: str, folder_id: str = None) -> str:
    """Копирует Google Doc. Возвращает ID нового документа."""
    drive = get_drive_service()
    if not drive:
        raise RuntimeError("Google Drive API не инициализирован (нет credentials)")

    resolved_folder_id = _resolve_drive_folder_id(folder_id or "")
    
    try:
        file_metadata = {"name": new_title}
        if resolved_folder_id:
            file_metadata["parents"] = [resolved_folder_id]
        
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


def write_new_cv_text(
    worksheet: gspread.Worksheet,
    row_num: int,
    headers: list,
    text: str,
) -> None:
    """Записывает сырой LLM-текст резюме в колонку 'New CV text' в Tracker.
    Если колонка отсутствует — пропускает без ошибки.
    """
    col = _find_col(headers, config.COL_NEW_CV_TEXT)
    if col is not None:
        worksheet.update_cell(row_num, col + 1, text)
    else:
        _log.debug(
            "Tracker: колонка '%s' не найдена — текст CV не сохранён. "
            "Добавьте колонку '%s' на лист Tracker для сохранения сырого текста LLM.",
            config.COL_NEW_CV_TEXT, config.COL_NEW_CV_TEXT,
        )