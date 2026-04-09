"""
cv_docs.py — работа с Google Docs и адаптированными резюме
"""
import logging
import re
from typing import Optional, List, Dict, Any

import llm
import sheets

_log = logging.getLogger(__name__)


def create_adapted_cv_document(
    base_cv: str,
    job_description: str,
    system_prompt: str,
    template_doc_id: str,
    adapted_cvs_folder_id: str,
    job_title: str,
    company_name: str,
) -> str:
    """
    Создает адаптированное резюме в новом Google Doc.
    
    Процесс:
    1. Генерирует адаптированный текст через LLM
    2. Копирует шаблон документа
    3. Заменяет текст в копии на адаптированный
    4. Возвращает URL нового документа
    
    Args:
        base_cv: базовое резюме
        job_description: описание вакансии
        system_prompt: системный промпт для LLM
        template_doc_id: ID документа-шаблона
        adapted_cvs_folder_id: ID папки для хранения резюме
        job_title: название должности (для имени файла)
        company_name: название компании (для имени файла)
    
    Returns:
        URL нового документа
    """
    try:
        # 1. Генерируем адаптированное резюме
        _log.info("CV Docs: генерация адаптированного резюме для %s/%s", company_name, job_title)
        adapted_cv_text = llm.generate_text(
            system_prompt=system_prompt,
            user_prompt=f"Базовое резюме:\n{base_cv}\n\n---\n\nОписание вакансии:\n{job_description}",
            temperature=0.7,
            model_kind="generation",
        )
        
        # 2. Копируем шаблон документа
        doc_name = f"CV_{company_name}_{job_title}".replace(" ", "_")[:40]
        _log.info("CV Docs: копирование шаблона документа: %s", doc_name)
        new_doc_id = sheets.copy_google_doc(template_doc_id, doc_name, adapted_cvs_folder_id)
        
        # 3. Заменяем текст в новом документе
        _log.info("CV Docs: обновление текста в документе: %s", new_doc_id)
        _replace_text_in_doc(new_doc_id, adapted_cv_text)
        
        # 4. Возвращаем ссылку
        doc_url = sheets.get_doc_link(new_doc_id)
        _log.info("CV Docs: ✓ резюме создано: %s", doc_url)
        return doc_url
        
    except Exception as e:
        _log.error("CV Docs: ошибка создания адаптированного резюме: %s", e)
        raise


def _replace_text_in_doc(doc_id: str, new_content: str) -> None:
    """
    Заменяет весь текст в Google Doc на новый, сохраняя форматирование.
    
    Алгоритм:
    1. Читаем текущий документ
    2. Извлекаем весь текст документа
    3. Используем replaceAllText для замены всего текста на новый
    """
    docs_service = sheets.get_docs_service()
    if not docs_service:
        raise RuntimeError("Google Docs API не инициализирован (нет credentials)")
    
    try:
        # Получаем текущий документ
        doc = docs_service.documents().get(documentId=doc_id).execute()
        
        # Извлекаем весь текст документа
        full_text = _extract_full_text(doc)
        
        # Если документ пустой, просто вставляем текст
        if not full_text.strip():
            requests = [{
                "insertText": {
                    "location": {"index": 1},
                    "text": new_content
                }
            }]
        else:
            # Заменяем весь существующий текст на новый
            requests = [{
                "replaceAllText": {
                    "containsText": {
                        "text": full_text,
                        "matchCase": False
                    },
                    "replaceText": new_content
                }
            }]
        
        body = {"requests": requests}
        docs_service.documents().batchUpdate(documentId=doc_id, body=body).execute()
        
        _log.debug("CV Docs: текст обновлён в документе %s", doc_id)
        
    except Exception as e:
        _log.error("CV Docs: ошибка обновления текста в документе: %s", e)
        raise


def _extract_full_text(doc: dict) -> str:
    """
    Извлекает весь текст из Google Doc документа.
    """
    content = doc.get("body", {}).get("content", [])
    text_parts = []
    
    for element in content:
        if "paragraph" in element:
            for paragraph_element in element["paragraph"]["elements"]:
                if "textRun" in paragraph_element:
                    text_parts.append(paragraph_element["textRun"]["content"])
    
    return "".join(text_parts)


def extract_text_from_description(description: str, max_length: int = 2000) -> str:
    """Извлекает чистый текст из описания вакансии для LLM."""
    # Удаляем HTML теги если есть
    text = re.sub(r"<[^>]+>", "", description)
    # Удаляем множественные пробелы
    text = re.sub(r"\s+", " ", text).strip()
    # Ограничиваем длину
    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text
