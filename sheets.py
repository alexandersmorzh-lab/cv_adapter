"""
sheets.py — работа с Google Sheets через OAuth
"""
import sys
from pathlib import Path
from typing import Optional

import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_base_dir() -> Path:
    """Возвращает папку рядом с exe или со скриптом."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _authenticate() -> gspread.Client:
    """OAuth-авторизация. При первом запуске открывает браузер."""
    base = _get_base_dir()
    token_path = base / config.TOKEN_FILE
    secret_path = base / config.CLIENT_SECRET_FILE

    creds: Optional[Credentials] = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secret_path.exists():
                raise FileNotFoundError(
                    f"Файл OAuth-credentials не найден: {secret_path}\n"
                    "Скачайте его из Google Cloud Console и положите рядом с программой."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            print("\nОткрывается браузер для авторизации...")
            print("Если браузер не открылся — скопируйте ссылку выше вручную.\n")
            creds = flow.run_local_server(
                port=8080,
                open_browser=True,
                timeout_seconds=120,
            )

        token_path.write_text(creds.to_json(), encoding="utf-8")

    return gspread.authorize(creds)


def get_base_cv(client: gspread.Client) -> str:
    """Читает базовое резюме с листа Master CV (всё содержимое листа как текст)."""
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


def write_adapted_cv(worksheet: gspread.Worksheet, row_num: int, col_adapted: int, text: str) -> None:
    """Записывает адаптированное резюме в нужную ячейку."""
    worksheet.update_cell(row_num, col_adapted + 1, text)  # gspread: колонки с 1


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


def authenticate() -> gspread.Client:
    return _authenticate()