"""
analyzer.py — модуль анализа вакансий по URL.

Пайплайн:
  - Берём строки Tracker: URL заполнен, Description пуст
  - Скачиваем страницу, извлекаем текст вакансии
  - LLM: оцениваем BaseScoring и численные значения дополнительных критериев (Additional Filter)
  - Считаем AdditionalScoring (0..100) и SummaryScoring — средневзвешенное Base/Additional (веса в .env)
  - Записываем Description и скоринги в Tracker
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import config
import llm

_log = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)
            self._chunks.append(" ")

    def get_text(self) -> str:
        text = "".join(self._chunks)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _extract_text_from_html(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def fetch_job_description(url: str) -> str:
    """
    Скачивает URL и возвращает текст вакансии.
    Пока поддержка: HTML → простой text extraction.
    """
    try:
        import httpx
    except ImportError as e:
        raise ImportError("Нужно установить httpx: pip install httpx") from e

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CVAdapter/Analyzer",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    timeout = float(config.ANALYZER_HTTP_TIMEOUT_SEC)

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()

        if "text/html" in ctype or "<html" in resp.text.lower():
            text = _extract_text_from_html(resp.text)
        else:
            # На некоторых сайтах content-type может быть странным — всё равно пробуем как текст
            text = resp.text.strip()

    if not text:
        raise RuntimeError("Не удалось извлечь текст вакансии (пусто).")

    if len(text) > config.ANALYZER_MAX_DESCRIPTION_CHARS:
        text = text[: config.ANALYZER_MAX_DESCRIPTION_CHARS].rstrip() + "\n\n[...truncated...]"
    return text


@dataclass(frozen=True)
class CriterionScoreLine:
    """Одна строка разбора Additional: вес из листа, число от LLM, вклад в AdditionalScoring."""

    name: str
    weight: float
    instruction: str
    llm_value: float
    applied: float
    share_of_additional: float


@dataclass(frozen=True)
class AnalyzerResult:
    description: str
    base_scoring: float
    additional_scoring: float
    summary_scoring: float
    additional_values: dict[str, float]
    criterion_lines: tuple[CriterionScoreLine, ...] = ()
    extra_llm_keys: tuple[str, ...] = ()
    base_parse_note: str = ""
    summary_explain: str = ""


def _clamp_0_100(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x != x:  # NaN
        return 0.0
    return max(0.0, min(100.0, x))


def compute_summary_scoring_with_note(base: float, additional: float) -> tuple[float, str]:
    """
    SummaryScoring: средневзвешенное BaseScoring и AdditionalScoring.
    Оба входа в шкале 0..100; (w_b·Base + w_a·Additional) / (w_b + w_a), затем clamp 0..100.
    При Base=Additional=100 результат 100 (масштаб итога совпадает с «максимум 100%»).
    """
    b = _clamp_0_100(base)
    a = _clamp_0_100(additional)
    wb = max(0.0, float(config.BASE_SCORING_WEIGHT))
    wa = max(0.0, float(config.ADDITIONAL_SCORING_WEIGHT))
    t = wb + wa
    if t <= 0:
        raw = (b + a) / 2.0
        s = _clamp_0_100(raw)
        return s, (
            "SummaryScoring (веса в .env нулевые — простое среднее): "
            f"({b:.2f}+{a:.2f})/2 = {s:.2f}"
        )
    raw = (wb * b + wa * a) / t
    s = _clamp_0_100(raw)
    return s, (
        f"SummaryScoring (веса Base:Additional = {wb:g}:{wa:g}): "
        f"({wb:g}·{b:.2f} + {wa:g}·{a:.2f}) / {t:g} = {s:.2f} (шкала 0..100)"
    )


def _to_float(x: Any) -> float:
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return 0.0
    s = s.replace("%", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _pick_base_scoring_raw(data: dict) -> tuple[Any, str | None]:
    """Часто модель даёт другое имя поля — иначе получаем base_scoring = 0."""
    for k in ("base_scoring", "BaseScoring", "baseScore", "base_score", "Base", "match_score"):
        if k in data and data[k] is not None:
            return data[k], k
    return None, None


def _coerce_llm_percent(
    raw: Any,
    *,
    key_used: str | None,
) -> tuple[float, str]:
    """
    Приводит ответ модели к 0..100.
    float в (0, 1] считаем долей (0.72 → 72%). int и строки без дробной части — уже проценты (72 → 72).
    bool в JSON не используем (True дал бы 1).
    """
    if isinstance(raw, bool):
        return 0.0, f"{key_used}={raw!r} — логическое значение, ожидалось число"
    if raw is None:
        return 0.0, "значение null"

    scaled_from_unit_interval = False
    if isinstance(raw, float):
        x = float(raw)
        if 0.0 < x <= 1.0:
            x *= 100.0
            scaled_from_unit_interval = True
    elif isinstance(raw, int):
        x = float(raw)
    else:
        s = str(raw).strip()
        if not s:
            return 0.0, f"{key_used}={raw!r} — пусто"
        x = _to_float(s)
        # строка вида "0.72" / "0,8" — доля; "72" или "72%" — проценты
        dec = s.replace(",", ".")
        if 0.0 < x <= 1.0 and "." in dec:
            x *= 100.0
            scaled_from_unit_interval = True

    if x != x:
        return 0.0, f"{key_used}={raw!r} — не число"

    out = _clamp_0_100(x)
    if scaled_from_unit_interval:
        return out, f"{key_used}={raw!r}: доля 0..1 → ×100 → {out:.2f}"
    return out, f"{key_used}={raw!r}: как проценты 0..100 → {out:.2f}"


def _parse_base_scoring_from_llm(data: dict) -> tuple[float, str]:
    raw, key = _pick_base_scoring_raw(data)
    if key is None:
        keys = [str(k) for k in list(data.keys())[:15]]
        return 0.0, (
            "нет поля base_scoring (ожидались синонимы: base_scoring, BaseScoring, …). "
            f"Ключи в ответе: {keys}"
        )
    return _coerce_llm_percent(raw, key_used=key)


def _compute_additional_scoring(
    filters: list[dict], values: dict[str, Any]
) -> tuple[float, dict[str, float], tuple[CriterionScoreLine, ...]]:
    """
    values: criterion_name -> число, которое вернула модель (ожидается 0..weight)
    AdditionalScoring = clamp( sum(applied) / sum(weights) * 100, 0..100 )
    У каждого критерия вклад в эту сумму (до clamp итога): applied / total_weight * 100
    """
    total_weight = 0.0
    achieved = 0.0
    normalized: dict[str, float] = {}
    lines: list[CriterionScoreLine] = []

    for f in filters:
        name = f["name"]
        weight = float(f["weight"])
        instruction = str(f.get("instruction") or "")
        total_weight += weight
        raw = _to_float(values.get(name))
        val = max(0.0, min(weight, raw))
        normalized[name] = val
        achieved += val

    if total_weight <= 0:
        return 0.0, normalized, ()

    for f in filters:
        name = f["name"]
        weight = float(f["weight"])
        instruction = str(f.get("instruction") or "")
        raw = _to_float(values.get(name))
        val = normalized[name]
        share = val / total_weight * 100.0
        lines.append(
            CriterionScoreLine(
                name=name,
                weight=weight,
                instruction=instruction,
                llm_value=raw,
                applied=val,
                share_of_additional=share,
            )
        )

    return _clamp_0_100(achieved / total_weight * 100.0), normalized, tuple(lines)


def analyze_job(*, base_cv: str, job_description: str, additional_filters: list[dict]) -> AnalyzerResult:
    """
    Делает LLM-анализ текста вакансии:
      - BaseScoring 0..100 (соответствие базовому CV; требования вакансии = 100%)
      - Значения дополнительных критериев (в числах 0..weight)
    """
    filters_block = "\n".join(
        f"- {f['name']} | weight={f['weight']} | instruction={f.get('instruction','')}".strip()
        for f in additional_filters
    )

    system_prompt = (
        "Ты — аналитик вакансий. Твоя задача — оценить соответствие кандидата вакансии.\n"
        "Верни ТОЛЬКО JSON без пояснений.\n"
        "Правила:\n"
        '- Поле обязательно называй ровно "base_scoring" (число).\n'
        "- base_scoring: число от 0 до 100 (проценты совпадения CV с вакансией), не доля: "
        "нужно 72, а не 0.72.\n"
        "- additional_values: объект, ключи строго как названия критериев из списка, значения — числа.\n"
        "- Для каждого дополнительного критерия значение должно быть в диапазоне 0..weight "
        "(тоже в баллах критерия, не доля от weight).\n"
    )

    user_prompt = f"""## Базовое резюме кандидата
{base_cv}

## Текст вакансии
{job_description}

## Дополнительные критерии (из листа Additional Filter)
{filters_block if filters_block else "(пусто)"}

Верни JSON в формате:
{{
  "base_scoring": 0-100,
  "additional_values": {{
    "<criterion_name>": <number in 0..weight>
  }}
}}
"""

    data = llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.2)
    base, base_note = _parse_base_scoring_from_llm(data)
    add_vals = data.get("additional_values") or {}
    if not isinstance(add_vals, dict):
        add_vals = {}

    additional_scoring, normalized_vals, criterion_lines = _compute_additional_scoring(
        additional_filters, add_vals
    )
    summary, summary_explain = compute_summary_scoring_with_note(base, additional_scoring)
    filter_names = {str(f["name"]) for f in additional_filters}
    extra_llm_keys = tuple(
        sorted(str(k) for k in add_vals if isinstance(k, str) and str(k) not in filter_names)
    )
    return AnalyzerResult(
        description=job_description,
        base_scoring=base,
        additional_scoring=additional_scoring,
        summary_scoring=summary,
        additional_values=normalized_vals,
        criterion_lines=criterion_lines,
        extra_llm_keys=extra_llm_keys,
        base_parse_note=base_note,
        summary_explain=summary_explain,
    )


def _print_scoring_breakdown(result: AnalyzerResult) -> None:
    """Читаемый разбор формул (включается при DEBUG=1 или ANALYZER_PRINT_SCORE_BREAKDOWN=1)."""
    print("         ─── разбор скоринга ───", flush=True)
    print(
        "         BaseScoring: одно число 0..100 от модели — насколько резюме закрывает "
        "формулировки вакансии (отдельно от таблицы критериев).",
        flush=True,
    )
    print(
        "         По Additional: числа — интерпретация модели по тексту вакансии и instruction из листа; "
        "цитаты из вакансии код не вытаскивает.",
        flush=True,
    )
    print(f"         → BaseScoring = {result.base_scoring:.2f}", flush=True)
    if result.base_parse_note:
        print(f"         (из JSON: {result.base_parse_note})", flush=True)

    tw = sum(line.weight for line in result.criterion_lines)
    if not result.criterion_lines:
        print(
            "         AdditionalScoring: нет строк в «Additional Filter» (или веса 0) → 0.00",
            flush=True,
        )
    else:
        print(
            "         AdditionalScoring: для каждого критерия модель ставит балл 0..weight; "
            "итог = сумма(учтённые_баллы) / сумма(weight) × 100, ограничение 0..100.",
            flush=True,
        )
        print(f"         → сумма весов (max баллов по блоку) = {tw:g}", flush=True)
        ach = sum(line.applied for line in result.criterion_lines)
        print(
            f"         → сумма учтённых баллов = {ach:g} → AdditionalScoring = {result.additional_scoring:.2f}",
            flush=True,
        )
        print(
            "         Критерий          | вес | LLM   | учтено | % от max | вклад в Add* | instruction (фрагмент)",
            flush=True,
        )
        for line in result.criterion_lines:
            pct_max = (line.applied / line.weight * 100.0) if line.weight else 0.0
            instr = line.instruction.replace("\n", " ")
            if len(instr) > 42:
                instr = instr[:39] + "..."
            print(
                f"         {line.name[:17]:17} | {line.weight:3g} | {line.llm_value:5.2f} | "
                f"{line.applied:6.2f} | {pct_max:6.1f}% | {line.share_of_additional:10.2f} | {instr}",
                flush=True,
            )
        print(
            "         * вклад в Add = учтено / сумма_весов × 100; сумма вкладов = AdditionalScoring (до общего clamp).",
            flush=True,
        )

    if result.extra_llm_keys:
        print(
            f"         ⚠ В JSON модели есть ключи не из листа (игнорируются): {', '.join(result.extra_llm_keys)}",
            flush=True,
        )

    if result.summary_explain:
        print(f"         {result.summary_explain}", flush=True)
    else:
        print(f"         SummaryScoring = {result.summary_scoring:.2f}", flush=True)
    print("         ───────────────────────", flush=True)


def run_analyzer(*, client, base_cv: str) -> tuple[int, int]:
    """
    Обрабатывает все строки Tracker: URL заполнен, Description пуст.
    Возвращает (успешно с LLM и скорингом, всего строк к обработке).
    """
    import sheets

    worksheet, rows, col_indices, _headers = sheets.get_tracker_rows_for_analyzer(client)
    if not rows:
        _log.debug("Analyzer: нет строк (URL есть, Description пуст)")
        return 0, 0

    additional_filters = sheets.read_additional_filters(client)
    print(
        f"      • Строк с URL без Description: {len(rows)}; "
        f"доп. критериев: {len(additional_filters)}",
        flush=True,
    )
    _log.debug("Analyzer: к обработке строк=%s, доп.критериев=%s", len(rows), len(additional_filters))

    ok = 0
    for idx, row in enumerate(rows, start=1):
        row_num = row["row_num"]
        url = row["url"]
        print(f"  [Analyzer {idx}/{len(rows)}] Строка {row_num}: {url}", flush=True)

        description_text: str | None = None
        try:
            print("         → загрузка страницы вакансии…", flush=True)
            description_text = fetch_job_description(url)
            print(f"         ✓ Текст со страницы: {len(description_text)} символов", flush=True)
            print(f"         → запрос к LLM ({config.LLM_PROVIDER}) для скоринга…", flush=True)
            result = analyze_job(
                base_cv=base_cv, job_description=description_text, additional_filters=additional_filters
            )
            sheets.write_analyzer_result(
                worksheet,
                row_num,
                col_indices,
                result.description,
                result.base_scoring,
                result.additional_scoring,
                result.summary_scoring,
            )
            if config.DEBUG or config.ANALYZER_PRINT_SCORE_BREAKDOWN:
                _print_scoring_breakdown(result)
            print(
                f"         ✓ Записано в таблицу: Base={result.base_scoring:.1f}, "
                f"Add={result.additional_scoring:.1f}, Sum={result.summary_scoring:.1f}",
                flush=True,
            )
            ok += 1
        except Exception as e:
            if description_text:
                try:
                    sheets.write_tracker_description_only(
                        worksheet, row_num, col_indices["description"], description_text
                    )
                    print(
                        f"         ⚠ Скоринг не выполнен ({e}). "
                        f"Текст вакансии ({len(description_text)} симв.) записан только в Description.",
                        flush=True,
                    )
                except Exception as w_err:
                    print(
                        f"         ✗ Ошибка Analyzer: {e}; не удалось записать Description: {w_err}",
                        flush=True,
                    )
            else:
                print(f"         ✗ Ошибка Analyzer: {e}", flush=True)

        if idx < len(rows):
            time.sleep(max(0, int(config.ANALYZER_RATE_LIMIT_SEC)))

    return ok, len(rows)


def check_wrong_phrases(description: str, wrong_phrases: list[str]) -> bool:
    """
    Проверяет, содержит ли Description хотя бы одну фразу из списка WrongPhrases.
    Возвращает True если найдена запрещённая фраза.
    """
    if not wrong_phrases or not description:
        return False
    
    description_lower = description.lower()
    for phrase in wrong_phrases:
        if phrase.lower() in description_lower:
            return True
    return False


def check_stop_requested() -> bool:
    """Проверяет, был ли отправлен сигнал остановки из GUI."""
    stop_file = Path.cwd() / ".stop_requested"
    return stop_file.exists()


def run_analyzer_search_database(*, client, base_cv: str) -> tuple[int, int, int]:
    """
    Новый поток обработки (04.04.2026):
    - Начинаем с листа Search DataBase
    - Processing all rows where Description is filled but SummaryScoring is empty
    - Фильтруем по WrongPhrases
    - Вычисляем BaseScoring, AdditionalScoring, SummaryScoring
    - Добавляем в Tracker те, которые > MIN_SUMMARY_SCORE и без TrackerID
    
    Возвращает: (успешно обработано, всего строк, добавлено в Tracker)
    """
    import sheets

    # 1. Читаем запрещённые фразы
    try:
        wrong_phrases = sheets.read_wrong_phrases(client)
        _log.debug("Analyzer: прочитано запрещённых фраз: %s", len(wrong_phrases))
    except Exception as e:
        _log.debug("Analyzer: не удалось прочитать WrongPhrases: %s", e)
        wrong_phrases = []

    # 2. Читаем строки из Search DataBase
    worksheet_search, rows, col_indices, headers = sheets.get_search_database_rows(client)
    if not rows:
        _log.debug("Analyzer: нет строк в Search DataBase (Description есть, SummaryScoring пуст)")
        return 0, 0, 0

    # 3. Читаем дополнительные критерии
    additional_filters = sheets.read_additional_filters(client)
    print(
        f"      • Строк в Search DataBase без SummaryScoring: {len(rows)}; "
        f"забанено фраз: {len(wrong_phrases)}; доп. критериев: {len(additional_filters)}",
        flush=True,
    )
    _log.debug(
        "Analyzer: к обработке строк=%s, запрещённых фраз=%s, доп.критериев=%s",
        len(rows),
        len(wrong_phrases),
        len(additional_filters),
    )

    ok = 0
    wrong_count = 0
    added_to_tracker = 0

    for idx, row in enumerate(rows, start=1):
        row_num = row["row_num"]
        description = row["description"]
        preview = description[:60].replace("\n", " ")
        print(f"  [SearchDB {idx}/{len(rows)}] Строка {row_num}: {preview}...", flush=True)

        # Проверить, получен ли сигнал остановки
        if check_stop_requested():
            print("\n⚠ Получен сигнал остановки.", flush=True)
            _log.debug("Analyzer: получен сигнал остановки на строке %s", row_num)
            break

        # Проверить WrongPhrases
        if check_wrong_phrases(description, wrong_phrases):
            # print("         ⚠ Найдена запрещённая фраза → WrongPhrases=1, скоринг=0", flush=True)
            try:
                sheets.write_search_database_result(
                    worksheet_search,
                    row_num,
                    col_indices,
                    base_scoring=0.0,
                    additional_scoring=0.0,
                    summary_scoring=0.0,
                    wrong_phrases_flag=1,
                )
                wrong_count += 1
                _log.debug("Analyzer: строка %s отклонена (WrongPhrases)", row_num)
            except Exception as e:
                print(f"         ✗ Ошибка записи результата: {e}", flush=True)
                _log.debug("Analyzer: ошибка записи для строки %s: %s", row_num, e)
            continue

        # Анализировать вакансию
        try:
            print(f"         → запрос к LLM ({config.LLM_PROVIDER}) для скоринга…", flush=True)
            result = analyze_job(
                base_cv=base_cv, job_description=description, additional_filters=additional_filters
            )
            
            # Записать результат в Search DataBase
            sheets.write_search_database_result(
                worksheet_search,
                row_num,
                col_indices,
                result.base_scoring,
                result.additional_scoring,
                result.summary_scoring,
                wrong_phrases_flag=0,
            )
            
            if config.DEBUG or config.ANALYZER_PRINT_SCORE_BREAKDOWN:
                _print_scoring_breakdown(result)
            
                print(
                    f"         ✓ Записано в Search DataBase: Base={result.base_scoring:.1f}, "
                    f"Add={result.additional_scoring:.1f}, Sum={result.summary_scoring:.1f}",
                    flush=True,
                )
            ok += 1

            # Проверить, нужно ли добавить в Tracker
            if result.summary_scoring > config.MIN_SUMMARY_SCORE:
                print(f"         → SummaryScoring={result.summary_scoring:.1f} > {config.MIN_SUMMARY_SCORE} → добавляю в Tracker",
                      flush=True)
                try:
                    next_id = sheets.get_next_tracker_id(client)
                    
                    # Подготовить данные строки для Tracker
                    tracker_row_data = {
                        "description": description,
                        "base_scoring": result.base_scoring,
                        "additional_scoring": result.additional_scoring,
                        "summary_scoring": result.summary_scoring,
                    }
                    
                    # Скопировать другие поля из row_data если есть
                    if "row_data" in row:
                        # Попытаться извлечь стандартные колонки из исходной строки
                        # (если они были заполнены в Search DataBase)
                        for field in ["timestamp", "title", "company", "location", "url", "source"]:
                            col_name = field.capitalize()
                            col_idx = sheets._find_col(headers, col_name)
                            if col_idx is not None:
                                tracker_row_data[field] = sheets._cell(row["row_data"], col_idx)
                    
                    # Добавить в Tracker
                    sheets.add_row_to_tracker(client, next_id, tracker_row_data)
                    
                    # Обновить TrackerID в Search DataBase
                    col_tracker_id = col_indices.get("tracker_id")
                    if col_tracker_id is not None:
                        sheets.update_search_database_tracker_id(
                            worksheet_search, row_num, col_tracker_id, next_id
                        )
                    
                    # print(f"         ✓ Добавлено в Tracker с ID={next_id}", flush=True)
                    added_to_tracker += 1
                    _log.debug("Analyzer: добавлена строка %s в Tracker с ID=%s", row_num, next_id)
                except Exception as e:
                    print(f"         ⚠ Не удалось добавить в Tracker: {e}", flush=True)
                    _log.debug("Analyzer: ошибка добавления в Tracker для строки %s: %s", row_num, e)

        except Exception as e:
            print(f"         ✗ Ошибка анализа: {e}", flush=True)
            _log.debug("Analyzer: ошибка анализа для строки %s: %s", row_num, e)

        if idx < len(rows):
            time.sleep(max(0, int(config.ANALYZER_RATE_LIMIT_SEC)))

    return ok, len(rows), added_to_tracker

