"""
cv_docs.py — работа с Google Docs и адаптированными резюме
"""
import logging
import re
import time
from typing import Optional, List, Dict, Any

import config
import llm
import sheets

_log = logging.getLogger(__name__)

# Плейсхолдер в шаблоне документа: поставьте {{CV_CONTENT}} в нужное место шаблона,
# чтобы LLM-текст вставлялся туда, сохраняя остальное форматирование документа.
# Если плейсхолдер отсутствует — весь контент шаблона будет заменён (fallback).
_PLACEHOLDER = "{{CV_CONTENT}}"

_APPLICANT_PLACEHOLDERS: dict[str, str] = {
    "{{NAME}}":     "name",
    "{{EMAIL}}":    "email",
    "{{PHONE}}":    "phone",
    "{{LINKEDIN}}": "linkedin",
}

_APPLICANT_PLACEHOLDER_DESCRIPTIONS: dict[str, str] = {
    "{{NAME}}":     "applicant full name",
    "{{EMAIL}}":    "applicant email",
    "{{PHONE}}":    "applicant phone",
    "{{LINKEDIN}}": "applicant LinkedIn URL",
}


def _build_applicant_instruction(applicant: dict) -> str:
    """Строит инструкцию для LLM только для полей, у которых есть значение.
    Если ни одного заполненного поля нет — возвращает пустую строку.
    """
    lines = [
        f"  {ph:<12} - {_APPLICANT_PLACEHOLDER_DESCRIPTIONS[ph]}"
        for ph, field in _APPLICANT_PLACEHOLDERS.items()
        if applicant.get(field)
    ]
    if not lines:
        return ""
    first_filled = next(
        ph for ph, field in _APPLICANT_PLACEHOLDERS.items() if applicant.get(field)
    )
    return (
        "IMPORTANT: wherever you need to write the applicant's personal details, "
        "use EXACTLY these placeholders (do not substitute real values):\n"
        + "\n".join(lines) + "\n"
        "For example, end the cover letter with: Kind regards, " + first_filled
    )

# ── Cover Letter detection ────────────────────────────────────────────────────

def _prompt_has_cover_letter(system_prompt: str) -> bool:
    """Возвращает True, если промпт упоминает cover letter / hook / сопроводительное письмо.
    Маркеры настраиваются через config.COVER_LETTER_MARKERS (.env: COVER_LETTER_MARKERS).
    """
    lp = system_prompt.lower()
    return any(m.lower() in lp for m in config.COVER_LETTER_MARKERS)


def _response_looks_complete(text: str, system_prompt: str) -> bool:
    """Эвристика: ответ выглядит полным, если:
    - последний непустой символ — знак завершения предложения/абзаца
    - И (если промпт требует cover letter) он действительно присутствует в тексте
    """
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped[-1] not in ".!?\"'»)":
        _log.debug("CV Docs: ответ LLM выглядит обрезанным (последний символ: %r)", stripped[-1])
        return False
    if _prompt_has_cover_letter(system_prompt):
        lp = stripped.lower()
        if not any(m.lower() in lp for m in config.COVER_LETTER_MARKERS):
            _log.debug("CV Docs: промпт требует cover letter, но в ответе он не найден")
            return False
    return True


def _trim_incomplete_cover_letter_section(text: str) -> str:
    """Если первый ответ начал секцию cover letter/hook, но оборвался на ней —
    срезаем эту незавершённую секцию, чтобы второй вызов заменил её полностью.

    Алгоритм: ищем последний заголовок Markdown (строку, начинающуюся с #),
    который содержит маркер из COVER_LETTER_MARKERS. Если текст после этого
    заголовка не заканчивается знаком конца предложения — обрезаем от него.
    """
    lines = text.split("\n")
    last_cl_heading_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            if any(m.lower() in stripped.lower() for m in config.COVER_LETTER_MARKERS):
                last_cl_heading_idx = i

    if last_cl_heading_idx is not None:
        section_text = "\n".join(lines[last_cl_heading_idx:]).rstrip()
        if section_text and section_text[-1] not in ".!?\"'»)":
            trimmed = "\n".join(lines[:last_cl_heading_idx]).rstrip()
            _log.debug(
                "CV Docs: обрезана незавершённая секция cover letter (с заголовка на строке %d)",
                last_cl_heading_idx,
            )
            return trimmed

    return text


def _is_retryable_llm_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "429" in text
        or "too_many_requests" in text
        or "queue_exceeded" in text
        or "rate limit" in text
    )


def _generate_adapted_cv_text_with_retry(
    *, system_prompt: str, base_cv: str, job_description: str, applicant_instruction: str = ""
) -> str:
    """Генерирует адаптированный текст резюме через LLM.

    Логика двух вызовов:
    1. Первый вызов — полный промпт (CV + всё что в промпте).
    2. Если промпт требует cover letter / hook И первый ответ выглядит обрезанным —
       делаем второй вызов только для недостающей части и склеиваем результаты.
    Маркеры cover letter настраиваются в .env (COVER_LETTER_MARKERS).
    """
    user_prompt = f"Базовое резюме:\n{base_cv}\n\n---\n\nОписание вакансии:\n{job_description}"
    retry_delay_sec = 10

    def _call(sp: str, up: str) -> str:
        try:
            return llm.generate_text(
                system_prompt=sp,
                user_prompt=up,
                temperature=0.7,
                model_kind="generation",
            )
        except Exception as error:
            if not _is_retryable_llm_error(error):
                raise
            _log.warning(
                "CV Docs: LLM вернул временную ошибку (%s). Повтор через %s сек.",
                error, retry_delay_sec,
            )
            time.sleep(retry_delay_sec)
            return llm.generate_text(
                system_prompt=sp,
                user_prompt=up,
                temperature=0.7,
                model_kind="generation",
            )

    # Вызов 1: полный промпт
    result = _call(system_prompt, user_prompt)

    # Проверяем нужен ли второй вызов
    needs_cover_letter = _prompt_has_cover_letter(system_prompt)
    if needs_cover_letter and not _response_looks_complete(result, system_prompt):
        _log.info(
            "CV Docs: первый ответ выглядит неполным и промпт требует cover letter — "
            "делаем второй вызов для Hook + Cover Letter"
        )
        cl_system_prompt = (
            "You are a professional cover letter writer. "
            "Write ONLY the Hook paragraph and Cover Letter for the job below. "
            "Use the same language as the job description. "
            "Be concise, professional, and complete the text fully — do not cut off mid-sentence."
            + ((" " + applicant_instruction) if applicant_instruction else "")
        )
        name_hint = " Use {{NAME}} in the closing signature." if "{{NAME}}" in applicant_instruction else ""
        cl_user_prompt = (
            f"Job description:\n{job_description}\n\n"
            "Write a Hook paragraph and a full Cover Letter for this position. "
            "Format with ## Hook and ## Cover Letter headings."
            + name_hint
        )
        cover_letter_part = _call(cl_system_prompt, cl_user_prompt)
        trimmed_result = _trim_incomplete_cover_letter_section(result)
        result = trimmed_result + "\n\n" + cover_letter_part
        _log.debug("CV Docs: второй вызов завершён, текст склеен")
    elif needs_cover_letter:
        _log.debug("CV Docs: промпт с cover letter — первый ответ выглядит полным, второй вызов не нужен")

    return result


def create_adapted_cv_document(
    base_cv: str,
    job_description: str,
    system_prompt: str,
    template_doc_id: str,
    adapted_cvs_folder_id: str,
    job_title: str,
    company_name: str,
    applicant: dict | None = None,
) -> tuple[str, str]:
    """
    Создает адаптированное резюме в новом Google Doc.

    Если переданы реквизиты applicant — добавляет в промпт инструкцию использовать
    плейсхолдеры {{NAME}}, {{EMAIL}}, {{PHONE}}, {{LINKEDIN}}, а после вставки текста
    заменяет их реальными значениями (в теле документа и в шапке шаблона).

    Args:
        base_cv: базовое резюме
        job_description: описание вакансии
        system_prompt: системный промпт для LLM
        template_doc_id: ID документа-шаблона
        adapted_cvs_folder_id: ID папки для хранения резюме
        job_title: название должности (для имени файла)
        company_name: название компании (для имени файла)
        applicant: словарь с полями name/email/phone/linkedin (из Master CV)

    Returns:
        (doc_url, raw_llm_text)
    """
    try:
        # 1. Если есть реквизиты — добавляем инструкцию использовать плейсхолдеры
        effective_applicant = applicant or {}
        has_applicant_data = any(
            effective_applicant.get(k) for k in ("name", "email", "phone", "linkedin")
        )
        effective_prompt = system_prompt
        if has_applicant_data:
            applicant_instruction = _build_applicant_instruction(effective_applicant)
            effective_prompt = system_prompt.rstrip() + "\n\n" + applicant_instruction
            _log.debug("CV Docs: реквизиты загружены, инструкция плейсхолдеров добавлена в промпт")
        else:
            applicant_instruction = ""

        # 2. Генерируем адаптированное резюме
        _log.info("CV Docs: генерация адаптированного резюме для %s/%s", company_name, job_title)
        adapted_cv_text = _generate_adapted_cv_text_with_retry(
            system_prompt=effective_prompt,
            base_cv=base_cv,
            job_description=job_description,
            applicant_instruction=applicant_instruction,
        )

        # 3. Копируем шаблон документа
        doc_name = f"CV_{company_name}_{job_title}".replace(" ", "_")[:40]
        _log.info("CV Docs: копирование шаблона документа: %s", doc_name)
        new_doc_id = sheets.copy_google_doc(template_doc_id, doc_name, adapted_cvs_folder_id)

        # 4. Заменяем текст в новом документе
        _log.info("CV Docs: обновление текста в документе: %s", new_doc_id)
        _replace_text_in_doc(new_doc_id, adapted_cv_text)

        # 5. Заменяем плейсхолдеры реквизитов (в тексте LLM и в шапке шаблона)
        if has_applicant_data:
            _replace_applicant_placeholders(new_doc_id, effective_applicant)

        # 6. Возвращаем ссылку и сырой текст LLM
        doc_url = sheets.get_doc_link(new_doc_id)
        _log.info("CV Docs: ✓ резюме создано: %s", doc_url)
        return doc_url, adapted_cv_text

    except Exception:
        raise


def _replace_text_in_doc(doc_id: str, new_content: str) -> None:
    """
    Заменяет контент в Google Doc на LLM-сгенерированный Markdown-текст.

    LLM возвращает Markdown; функция парсит его и применяет named styles Google Docs
    (TITLE, HEADING_1, HEADING_2, HEADING_3, LIST_PARAGRAPH, NORMAL_TEXT) а также
    inline-форматирование (bold, italic). Named styles берутся из шаблона документа,
    поэтому шрифты, цвета и отступы заголовков соответствуют шаблону.

    Алгоритм (два режима вставки):

    1. РЕЖИМ ПЛЕЙСХОЛДЕРА (предпочтительный):
       Находит {{CV_CONTENT}} в скопированном документе, удаляет его и вставляет
       на его место отформатированный текст. Всё остальное оформление шаблона
       (колонтитулы, поля страницы, секции, фото в header) остаётся нетронутым.

    2. РЕЖИМ FALLBACK (плейсхолдер не найден):
       Удаляет всё тело документа, вставляет текст с начала.
       Шрифты заголовков из named styles шаблона всё равно применяются.
    """
    docs_service = sheets.get_docs_service()
    if not docs_service:
        raise RuntimeError("Google Docs API не инициализирован (нет credentials)")

    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()

        paragraphs = _parse_markdown_to_paragraphs(new_content)
        plain_text = "\n".join(p["text"] for p in paragraphs)

        placeholder_index = _find_placeholder_index(doc, _PLACEHOLDER)

        if placeholder_index is not None:
            _log.debug(
                "CV Docs: найден плейсхолдер '%s' в позиции %d — оформление шаблона сохранено",
                _PLACEHOLDER,
                placeholder_index,
            )
            delete_requests = [{
                "deleteContentRange": {
                    "range": {
                        "startIndex": placeholder_index,
                        "endIndex": placeholder_index + len(_PLACEHOLDER),
                    }
                }
            }]
            insert_index = placeholder_index
        else:
            _log.warning(
                "CV Docs: плейсхолдер '%s' не найден в документе %s — "
                "весь контент шаблона будет заменён. "
                "Добавьте '%s' в шаблон для сохранения его оформления.",
                _PLACEHOLDER, doc_id, _PLACEHOLDER,
            )
            doc_content = doc.get("body", {}).get("content", [])
            end_index = doc_content[-1].get("endIndex", 1) if doc_content else 1
            insert_index = 1
            delete_requests = []
            if end_index > 2:
                delete_requests.append({
                    "deleteContentRange": {
                        "range": {"startIndex": 1, "endIndex": end_index - 1}
                    }
                })

        # 1. Удаляем старое содержимое
        if delete_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": delete_requests}
            ).execute()

        # 2. Вставляем plain text (без markdown-маркеров)
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": insert_index}, "text": plain_text}}]},
        ).execute()

        # 3. Применяем named styles и inline-форматирование
        _apply_paragraph_styles(doc_id, docs_service, paragraphs, start_index=insert_index)

        _log.debug("CV Docs: markdown-контент вставлен и отформатирован в документе %s", doc_id)

    except Exception:
        raise


def _parse_inline_formatting(text: str) -> tuple[str, list[dict]]:
    """
    Разбирает inline Markdown-разметку в строке.
    Возвращает (plain_text, runs), где каждый run:
      {'start': int, 'end': int, 'bold': bool, 'italic': bool}

    Поддерживает: ***bold+italic***, **bold**, __bold__, *italic*, _italic_, `code`.
    """
    chars: list[str] = []
    runs: list[dict] = []
    i = 0

    while i < len(text):
        # *** bold+italic ***
        if text[i:i + 3] == "***":
            close = text.find("***", i + 3)
            if close != -1:
                start = len(chars)
                chars.extend(text[i + 3:close])
                runs.append({"start": start, "end": len(chars), "bold": True, "italic": True})
                i = close + 3
                continue
        # ** bold **
        if text[i:i + 2] == "**":
            close = text.find("**", i + 2)
            if close != -1:
                start = len(chars)
                chars.extend(text[i + 2:close])
                runs.append({"start": start, "end": len(chars), "bold": True, "italic": False})
                i = close + 2
                continue
        # __ bold __
        if text[i:i + 2] == "__":
            close = text.find("__", i + 2)
            if close != -1:
                start = len(chars)
                chars.extend(text[i + 2:close])
                runs.append({"start": start, "end": len(chars), "bold": True, "italic": False})
                i = close + 2
                continue
        # * italic * (не **)
        if text[i] == "*" and text[i:i + 2] != "**":
            close = text.find("*", i + 1)
            if close != -1 and text[close:close + 2] != "**":
                start = len(chars)
                chars.extend(text[i + 1:close])
                runs.append({"start": start, "end": len(chars), "bold": False, "italic": True})
                i = close + 1
                continue
        # _ italic _ (не __)
        if text[i] == "_" and text[i:i + 2] != "__":
            close = text.find("_", i + 1)
            if close != -1 and text[close:close + 2] != "__":
                start = len(chars)
                chars.extend(text[i + 1:close])
                runs.append({"start": start, "end": len(chars), "bold": False, "italic": True})
                i = close + 1
                continue
        # `code` — убираем маркеры, текст оставляем как есть
        if text[i] == "`":
            close = text.find("`", i + 1)
            if close != -1:
                chars.extend(text[i + 1:close])
                i = close + 1
                continue
        # обычный символ
        chars.append(text[i])
        i += 1

    return "".join(chars), runs


def _parse_markdown_to_paragraphs(text: str) -> list[dict]:
    """
    Парсит Markdown-текст в список параграфов для Google Docs API.

    Каждый параграф — словарь:
      {
        'text':   str,          # plain text без markdown-маркеров
        'style':  str,          # Google Docs namedStyleType
        'bullet': bool,         # применить LIST_PARAGRAPH с буллетом
        'runs':   list[dict],   # inline bold/italic (start, end, bold, italic)
      }

    Маппинг Markdown → named style:
      #      → TITLE
      ##     → HEADING_1
      ###    → HEADING_2
      ####+  → HEADING_3
      - / * / + / 1. → NORMAL_TEXT + bullet
      ---    → пропускается (горизонтальная черта)
      иное   → NORMAL_TEXT
    """
    paragraphs: list[dict] = []

    for line in text.split("\n"):
        # Горизонтальная черта — пропускаем
        if re.fullmatch(r"-{3,}|={3,}|\*{3,}", line.strip()):
            continue

        style = "NORMAL_TEXT"
        bullet = False
        content = line

        if line.startswith("# "):
            style, content = "TITLE", line[2:]
        elif line.startswith("## "):
            style, content = "HEADING_1", line[3:]
        elif line.startswith("### "):
            style, content = "HEADING_2", line[4:]
        elif line.startswith("#### "):
            style, content = "HEADING_3", line[5:]
        elif re.match(r"^#{5,} ", line):
            style, content = "HEADING_3", re.sub(r"^#{5,} ", "", line)
        elif re.match(r"^[-*+] ", line):
            bullet, content = True, line[2:]
        elif re.match(r"^\d+\. ", line):
            bullet, content = True, re.sub(r"^\d+\. ", "", line)

        plain, runs = _parse_inline_formatting(content)
        paragraphs.append({"text": plain, "style": style, "bullet": bullet, "runs": runs})

    return paragraphs


def _apply_paragraph_styles(
    doc_id: str,
    docs_service,
    paragraphs: list[dict],
    start_index: int,
) -> None:
    """
    Применяет named styles, буллеты и inline-форматирование к вставленным параграфам.

    Google Docs API: batchUpdate разбивается на чанки по 100 запросов,
    чтобы не превысить лимит размера запроса.
    """
    if not paragraphs:
        return

    style_requests: list[dict] = []
    current_index = start_index

    for i, para in enumerate(paragraphs):
        text_len = len(para["text"])
        para_start = current_index
        is_last = i == len(paragraphs) - 1
        # endIndex для API: включает \n-разделитель для не-последних параграфов
        para_end = para_start + text_len + (0 if is_last else 1)

        # Named style (NORMAL_TEXT — стиль по умолчанию, не нужно задавать явно)
        if para["style"] != "NORMAL_TEXT":
            style_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": para_start, "endIndex": para_end},
                    "paragraphStyle": {"namedStyleType": para["style"]},
                    "fields": "namedStyleType",
                }
            })

        # Bullet list
        if para.get("bullet") and para["text"].strip():
            style_requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": para_start, "endIndex": para_end},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        # Inline bold/italic
        for run in para.get("runs", []):
            fmt: dict = {}
            if run.get("bold"):
                fmt["bold"] = True
            if run.get("italic"):
                fmt["italic"] = True
            if fmt:
                style_requests.append({
                    "updateTextStyle": {
                        "range": {
                            "startIndex": para_start + run["start"],
                            "endIndex": para_start + run["end"],
                        },
                        "textStyle": fmt,
                        "fields": ",".join(fmt.keys()),
                    }
                })

        current_index += text_len + 1  # +1 за \n

    if not style_requests:
        return

    _log.debug(
        "CV Docs: применяем %d style-запросов к документу %s",
        len(style_requests), doc_id,
    )
    chunk_size = 100
    for i in range(0, len(style_requests), chunk_size):
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": style_requests[i:i + chunk_size]},
        ).execute()


def _replace_applicant_placeholders(doc_id: str, applicant: dict) -> None:
    """Заменяет плейсхолдеры реквизитов реальными значениями через replaceAllText.
    Работает во всём документе сразу: в теле, шапке, колонтитулах и подписях.
    Пропускает плейсхолдеры с пустым значением без замены.
    """
    docs_service = sheets.get_docs_service()
    if not docs_service:
        raise RuntimeError("Google Docs API не инициализирован")

    requests = []
    for placeholder, field in _APPLICANT_PLACEHOLDERS.items():
        value = applicant.get(field, "")
        if not value:
            continue
        requests.append({
            "replaceAllText": {
                "containsText": {"text": placeholder, "matchCase": True},
                "replaceText": value,
            }
        })

    if not requests:
        return

    result = docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()

    counts = [
        r.get("replaceAllText", {}).get("occurrencesChanged", 0)
        for r in result.get("replies", [])
    ]
    _log.debug(
        "CV Docs: заменено плейсхолдеров реквизитов: %s",
        dict(zip(_APPLICANT_PLACEHOLDERS.keys(), counts)),
    )


def _find_placeholder_index(doc: dict, placeholder: str) -> int | None:
    """
    Ищет точную позицию (startIndex) плейсхолдера в теле документа.
    Обходит абзацы и ячейки таблиц, проверяет каждый text run.
    Возвращает None, если плейсхолдер не найден.

    Примечание: Google Docs может разбить строку на несколько text run-ов;
    в этом случае функция не найдёт плейсхолдер и сработает fallback.
    Чтобы этого избежать — набирайте {{CV_CONTENT}} в шаблоне одним куском
    без промежуточного редактирования.
    """
    def _search_in_content(content: list) -> int | None:
        for element in content:
            # Обычный абзац
            if "paragraph" in element:
                for para_el in element["paragraph"]["elements"]:
                    text_run = para_el.get("textRun", {})
                    text = text_run.get("content", "")
                    if placeholder in text:
                        offset = text.index(placeholder)
                        return para_el["startIndex"] + offset
            # Ячейки таблиц
            if "table" in element:
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        result = _search_in_content(cell.get("content", []))
                        if result is not None:
                            return result
        return None

    body_content = doc.get("body", {}).get("content", [])
    return _search_in_content(body_content)


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
