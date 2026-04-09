"""
resume_adapter.py — адаптация резюме для вакансий из Tracker
"""
import logging
import time
from pathlib import Path
from typing import Tuple

import gspread

import config
import sheets
import cv_docs

_log = logging.getLogger(__name__)


def check_stop_requested() -> bool:
    """Проверяет, был ли отправлен сигнал остановки из GUI."""
    stop_file = Path.cwd() / ".stop_requested"
    return stop_file.exists()


def run_resume_adapter(client: gspread.Client, base_cv: str, delay_sec: float = 2.0) -> Tuple[int, int]:
    """
    Обрабатывает все строки в листе Tracker и создает адаптированные резюме.
    
    Условия обработки:
    - Description заполнен (есть описание вакансии)
    - colnew_cv_file пуст (резюме ещё не создано)
    
    Args:
        client: gspread.Client
        base_cv: базовое резюме соискателя
        delay_sec: задержка между запросами к LLM (для rate limiting)
    
    Returns:
        (processed_ok, processed_total)
    """
    _log.info("Resume Adapter: начало обработки листа Tracker")
    
    # Читаем Master CV для параметров
    master_cv_meta = sheets.get_master_cv_metadata(client)
    template_doc_id = master_cv_meta["template_doc_id"]
    system_prompt = master_cv_meta["system_prompt"]
    adapted_cvs_folder_id = master_cv_meta["adapted_cvs_folder_id"]
    
    if not template_doc_id:
        raise ValueError("CV Doc Template не найден в листе Master CV (раздел 'CV Doc Template')")
    if not system_prompt:
        raise ValueError("System_prompt не найден в листе Master CV")
    
    # Если папка не указана, используем значение из .env или создаём новую
    if not adapted_cvs_folder_id:
        _log.warning("Resume Adapter: папка для резюме не указана в Master CV. Используем ADAPTED_CVS_FOLDER_ID из .env")
        adapted_cvs_folder_id = config.ADAPTED_CVS_FOLDER_ID
    
    # Читаем строки из Tracker
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_TRACKER)
    all_values = worksheet.get_all_values()
    
    if not all_values:
        _log.warning("Resume Adapter: лист Tracker пуст")
        return 0, 0
    
    headers = all_values[0]
    col_desc = sheets._find_col(headers, config.COL_DESCRIPTION)
    col_new_cv = sheets._find_col(headers, config.COL_NEW_CV_FILE)
    col_company = sheets._find_col(headers, "Company")
    col_title = sheets._find_col(headers, "Title")
    
    if col_desc is None or col_new_cv is None:
        raise ValueError(
            f"Нужные колонки не найдены в листе Tracker. "
            f"Description: {col_desc}, New CV File: {col_new_cv}"
        )
    
    # Собираем строки для обработки
    rows_to_process = []
    for i, row in enumerate(all_values[1:], start=2):
        desc = sheets._cell(row, col_desc)
        new_cv = sheets._cell(row, col_new_cv)
        company = sheets._cell(row, col_company) if col_company is not None else ""
        title = sheets._cell(row, col_title) if col_title is not None else ""
        
        # Обработать если Description заполнен, но New CV File пуст
        if desc and not new_cv:
            rows_to_process.append({
                "row_num": i,
                "description": desc,
                "company": company,
                "title": title,
            })
    
    print(f" найдено вакансий для подготовки резюме: {len(rows_to_process)}")
    
    processed_ok = 0
    processed_total = len(rows_to_process)
    
    for idx, row_info in enumerate(rows_to_process, start=1):
        row_num = row_info["row_num"]
        description = row_info["description"]
        company = row_info["company"]
        title = row_info["title"]
        
        # Проверить, получен ли сигнал остановки
        if check_stop_requested():
            print("\n⚠ Получен сигнал остановки.", flush=True)
            _log.debug("Resume Adapter: получен сигнал остановки на строке %s", row_num)
            break
        
        try:
            print(f"подготовка резюме {idx}/{processed_total}({company} / {title})")
            
            # Создаём адаптированное резюме
            doc_url = cv_docs.create_adapted_cv_document(
                base_cv=base_cv,
                job_description=description,
                system_prompt=system_prompt,
                template_doc_id=template_doc_id,
                adapted_cvs_folder_id=adapted_cvs_folder_id,
                job_title=title or "CV",
                company_name=company or "Company",
            )
            
            # Обновляем Tracker
            sheets.update_tracker_new_cv_file(worksheet, row_num, headers, doc_url)
            processed_ok += 1
            
            _log.info("Resume Adapter: ✓ строка %d успешно обработана", row_num)
            
            # Rate limiting
            if idx < processed_total:
                time.sleep(delay_sec)
                
        except Exception as e:
            _log.error("Resume Adapter: ✗ ошибка обработки строки %d: %s", row_num, e)
    
    _log.info("Resume Adapter: завершено. Обработано: %d/%d", processed_ok, processed_total)
    return processed_ok, processed_total
