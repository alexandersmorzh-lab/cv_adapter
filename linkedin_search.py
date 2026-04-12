"""
linkedin_search.py — импорт вакансий из LinkedIn в лист Search DataBase.

MVP-режим:
- читает активные строки из листа `Primary Filter`
- подключается к Chrome/Edge, запущенному с remote debugging
- открывает LinkedIn Jobs по параметрам поиска
- забирает вакансии и пишет их в `Search DataBase`

Важно:
- вход в LinkedIn должен быть выполнен в debug-браузере от имени пользователя
- Playwright устанавливается отдельно: `pip install -r requirements.txt` и `playwright install chromium`
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import config

_log = logging.getLogger(__name__)

STRICT_CARD_SELECTORS = [
    "ul.jobs-search__results-list > li",
    ".jobs-search-results__list-item",
    ".scaffold-layout__list-container li",
]

FALLBACK_CARD_SELECTORS = [
    ".job-card-container",
    "[data-job-id]",
]

POPUP_BUTTON_SELECTORS = [
    "button.artdeco-modal__dismiss",
    "button[aria-label*='Dismiss']",
    "button[aria-label*='Close']",
    "button:has-text('Got it')",
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "button:has-text('Not now')",
    "button:has-text('Maybe later')",
    "button:has-text('Skip')",
    "button:has-text('Close')",
    "button:has-text('Dismiss')",
    "button:has-text('Accepteren')",
    "button:has-text('Niet nu')",
    "button:has-text('Overslaan')",
    "button:has-text('Sluiten')",
    "button:has-text('Соглас')",
    "button:has-text('Принять')",
    "button:has-text('Закрыть')",
]

INDUSTRY_BUTTON_LABELS = ("Отрасли", "Отрасль", "Industries", "Industry")
ALL_FILTERS_BUTTON_LABELS = ("Все фильтры", "All filters", "Alle filters")
APPLY_FILTER_BUTTON_LABELS = (
    "Показать результаты",
    "Показать",
    "Применить",
    "Show results",
    "Apply",
)
FILTER_DIALOG_SELECTORS = [
    "[role='dialog']",
    ".artdeco-modal",
    ".jobs-search-box__filters-dropdown",
    ".search-reusables__all-filters-pill-panel",
]
FILTER_SEARCH_INPUT_SELECTORS = [
    "input[placeholder*='Search']",
    "input[placeholder*='Поиск']",
    "input[placeholder*='industry']",
    "input[placeholder*='Industry']",
    "input[placeholder*='отрасл']",
    "input[aria-label*='industry']",
    "input[aria-label*='Industry']",
    "input[aria-label*='отрасл']",
    "input[aria-label*='branche']",
    "input[type='text']",
]

INDUSTRY_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "it услуги и ит консалтинг": (
        "IT-услуги и ИТ-консалтинг",
        "IT Services and IT Consulting",
        "IT Services & IT Consulting",
        "IT-diensten en IT-consultancy",
    ),
    "разработка программного обеспечения": (
        "Разработка программного обеспечения",
        "Software Development",
        "Softwareontwikkeling",
    ),
    "финансовые услуги": (
        "Финансовые услуги",
        "Financial Services",
        "Financiële dienstverlening",
    ),
    "технологии информационные средства и интернет": (
        "Технологии, информационные средства и Интернет",
        "Technology, Information and Internet",
        "Technologie, informatie en internet",
    ),
}
INDUSTRY_CODE_MAP_FILE = Path(config.BASE_DIR) / "linkedin_industry_map.json"


def _find_col(headers: list[str], name: str) -> int | None:
    target = (name or "").strip().lower()
    for i, header in enumerate(headers):
        if (header or "").strip().lower() == target:
            return i
    return None


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _check_stop_requested() -> bool:
    return (Path.cwd() / ".stop_requested").exists()


def _require_playwright():
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ImportError(
            "Не установлен Playwright. Выполните: pip install -r requirements.txt и playwright install chromium"
        ) from e
    return async_playwright


def _default_search_database_headers() -> list[str]:
    return [
        "Timestamp",
        "Title",
        "Company",
        "Location",
        config.COL_URL,
        "Source",
        config.COL_DESCRIPTION,
        config.COL_BASE_SCORING,
        config.COL_ADDITIONAL_SCORING,
        config.COL_SUMMARY_SCORING,
        config.COL_WRONG_PHRASES,
        config.COL_TRACKER_ID,
    ]


def _ensure_search_database_sheet(client) -> tuple[Any, list[str], set[str]]:
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_SEARCH_DATABASE)
    all_values = worksheet.get_all_values()

    if not all_values:
        headers = _default_search_database_headers()
        worksheet.append_row(headers, value_input_option="USER_ENTERED")
        all_values = [headers]
        print(f"      • Лист '{config.SHEET_SEARCH_DATABASE}' был пуст — созданы заголовки.", flush=True)

    headers = all_values[0]
    col_url = _find_col(headers, config.COL_URL)
    col_desc = _find_col(headers, config.COL_DESCRIPTION)

    missing = []
    if col_url is None:
        missing.append(config.COL_URL)
    if col_desc is None:
        missing.append(config.COL_DESCRIPTION)

    if missing:
        raise ValueError(
            f"В листе '{config.SHEET_SEARCH_DATABASE}' не найдены обязательные колонки: {', '.join(missing)}. "
            f"Текущие заголовки: {headers}"
        )

    existing_urls = {
        _cell(row, col_url)
        for row in all_values[1:]
        if _cell(row, col_url)
    }
    return worksheet, headers, existing_urls


def _split_multi_value(raw: str, *, separators: str = ",;\n") -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = re.split(f"[{re.escape(separators)}]", raw)
    return [item.strip() for item in parts if item and item.strip()]


def _normalize_text(value: str) -> str:
    value = (value or "").strip().lower().replace("ё", "е")
    value = value.replace("&", " and ")
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _expand_industry_variants(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []

    variants = [raw]
    alias_key = _normalize_text(raw)
    variants.extend(INDUSTRY_NAME_ALIASES.get(alias_key, ()))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in variants:
        normalized = _normalize_text(item)
        if normalized and normalized not in seen:
            deduped.append(item.strip())
            seen.add(normalized)
    return deduped


def _tokenize_text(value: str) -> set[str]:
    return {token for token in _normalize_text(value).split() if len(token) >= 3}


def _score_text_match(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 100.0
    if left_norm in right_norm or right_norm in left_norm:
        return 90.0

    left_tokens = _tokenize_text(left)
    right_tokens = _tokenize_text(right)
    overlap = len(left_tokens & right_tokens)
    if overlap:
        coverage = overlap / max(1, min(len(left_tokens), len(right_tokens)))
    else:
        coverage = 0.0

    ratio = difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
    return ratio * 60.0 + coverage * 40.0


def _load_industry_code_map() -> dict[str, list[str]]:
    if not INDUSTRY_CODE_MAP_FILE.exists():
        return {}

    try:
        raw = json.loads(INDUSTRY_CODE_MAP_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"      ⚠ Не удалось прочитать словарь отраслей '{INDUSTRY_CODE_MAP_FILE.name}': {e}", flush=True)
        return {}

    if not isinstance(raw, dict):
        return {}

    mapping: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            codes = _split_multi_value(value)
        elif isinstance(value, list):
            codes = [str(item).strip() for item in value if str(item).strip()]
        else:
            continue

        normalized_key = _normalize_text(key)
        if normalized_key and codes:
            mapping[normalized_key] = list(dict.fromkeys(codes))

    return mapping


def _resolve_industry_codes(industries: list[str], explicit_codes: list[str] | None = None) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()

    for code in explicit_codes or []:
        code = str(code).strip()
        if code and code not in seen:
            resolved.append(code)
            seen.add(code)

    if resolved:
        return resolved

    code_map = _load_industry_code_map()
    if not code_map:
        return resolved

    for industry in industries:
        for variant in _expand_industry_variants(industry):
            codes = code_map.get(_normalize_text(variant), [])
            if not codes:
                continue
            for code in codes:
                code = str(code).strip()
                if code and code not in seen:
                    resolved.append(code)
                    seen.add(code)
            break

    return resolved


def _replace_query_param(url: str, name: str, value: Any) -> str:
    parsed = urlparse(url)
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != name]
    query_pairs.append((name, str(value)))
    return urlunparse(parsed._replace(query=urlencode(query_pairs, safe=",")))


def read_primary_filter_rows(client) -> list[dict[str, Any]]:
    """
    Читает активные строки из листа Primary Filter.

    Ожидаемые колонки:
      - role
      - location
      - date_range (например r86400 / r604800 / r2592000)
      - active (TRUE/FALSE)
    Опционально:
      - experience_levels
      - job_types
      - job_functions (legacy: прямые LinkedIn ID через URL)
      - industries / industry (читаемые названия отраслей)
      - industry_codes / linkedin_industry_codes / f_i (готовые коды LinkedIn для `f_I`)
      - weight / priority (вес позиции для распределения общего лимита)
    """
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(config.SHEET_PRIMARY_FILTER)
    values = worksheet.get_all_values()

    if not values:
        raise ValueError(
            f"Лист '{config.SHEET_PRIMARY_FILTER}' пуст. Создайте его и добавьте колонки: role, location, date_range, active."
        )

    headers = [(h or "").strip().lower() for h in values[0]]
    idx = {name: i for i, name in enumerate(headers)}

    required = ["role", "location", "active"]
    missing = [name for name in required if name not in idx]
    if missing:
        raise ValueError(
            f"В листе '{config.SHEET_PRIMARY_FILTER}' не хватает колонок: {', '.join(missing)}. Найдены: {headers}"
        )

    def parse_list(row: list[str], *col_names: str, separators: str = ",;\n") -> list[str]:
        result: list[str] = []
        for col_name in col_names:
            col_idx = idx.get(col_name, -1)
            if col_idx < 0 or col_idx >= len(row):
                continue
            result.extend(_split_multi_value(_cell(row, col_idx), separators=separators))
        return list(dict.fromkeys(result))

    def parse_weight(row: list[str]) -> float:
        for col_name in ("weight", "priority"):
            col_idx = idx.get(col_name, -1)
            if col_idx < 0 or col_idx >= len(row):
                continue
            raw = _cell(row, col_idx)
            if not raw:
                continue
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                continue
            return value if value > 0 else 1.0
        return 1.0

    searches: list[dict[str, Any]] = []
    for row in values[1:]:
        role = _cell(row, idx.get("role"))
        location = _cell(row, idx.get("location"))
        active = _cell(row, idx.get("active")).lower()
        if active not in {"true", "1", "yes", "y", "да"}:
            continue
        if not role:
            continue

        date_range = _cell(row, idx.get("date_range")) or "r604800"
        if not (date_range.startswith("r") and date_range[1:].isdigit()):
            print(f"      ⚠ Некорректный date_range='{date_range}' для '{role}', беру r604800", flush=True)
            date_range = "r604800"

        industry_names = parse_list(row, "industries", "industry", "linkedin_industries", separators=";\n")
        explicit_industry_codes = parse_list(row, "industry_codes", "linkedin_industry_codes", "f_i")

        searches.append(
            {
                "keywords": role,
                "location": location,
                "date_range": date_range,
                "weight": parse_weight(row),
                "experience_levels": parse_list(row, "experience_levels"),
                "job_types": parse_list(row, "job_types"),
                "job_functions": parse_list(row, "job_functions"),
                "industries": industry_names,
                "industry_codes": _resolve_industry_codes(industry_names, explicit_industry_codes),
            }
        )

    return searches


def build_linkedin_url(search: dict[str, Any], start: int = 0) -> str:
    params: dict[str, str] = {
        "keywords": str(search.get("keywords", "")),
        "location": str(search.get("location", "")),
        "f_TPR": str(search.get("date_range", "r604800")),
        "start": str(start),
        "sortBy": "DD",
    }

    if search.get("experience_levels"):
        params["f_E"] = ",".join(search["experience_levels"])
    if search.get("job_types"):
        params["f_JT"] = ",".join(search["job_types"])

    legacy_codes = [str(v).strip() for v in (search.get("job_functions") or []) if str(v).strip()]
    industry_codes = [str(v).strip() for v in (search.get("industry_codes") or []) if str(v).strip()]
    combined_codes = list(dict.fromkeys([*industry_codes, *legacy_codes]))
    if combined_codes:
        params["f_I"] = ",".join(combined_codes)

    return f"https://www.linkedin.com/jobs/search/?{urlencode(params, safe=',')}"


def _humanize_date_range(date_range: str) -> str:
    mapping = {
        "r86400": "последние 24 часа",
        "r604800": "последние 7 дней",
        "r2592000": "последние 30 дней",
    }
    return mapping.get(date_range, f"период LinkedIn ({date_range})")


def _fmt_optional_list(values: list[str]) -> str:
    return ", ".join(values) if values else "не задано"


def _build_weighted_caps(search_profile: list[dict[str, Any]], total_cap: int) -> list[int]:
    if total_cap <= 0 or not search_profile:
        return [0] * len(search_profile)

    weights = [max(0.0, float(search.get("weight", 1.0) or 0.0)) for search in search_profile]
    if sum(weights) <= 0:
        weights = [1.0] * len(search_profile)

    total_weight = sum(weights)
    raw_caps = [total_cap * weight / total_weight for weight in weights]
    caps = [int(cap) for cap in raw_caps]

    leftover = total_cap - sum(caps)
    ranked = sorted(
        range(len(search_profile)),
        key=lambda i: (raw_caps[i] - caps[i], weights[i], -i),
        reverse=True,
    )
    for i in ranked:
        if leftover <= 0:
            break
        caps[i] += 1
        leftover -= 1

    return caps


def _weight_sort_key(search: dict[str, Any]) -> tuple[float, str]:
    return (float(search.get("weight", 1.0) or 1.0), str(search.get("keywords", "")))


async def _get_active_filter_scope(page):
    for selector in FILTER_DIALOG_SELECTORS:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(count):
                candidate = locator.nth(idx)
                if await candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return page


async def _click_button_by_labels(scope, labels: tuple[str, ...], *, timeout_ms: int = 2500) -> bool:
    pattern = re.compile("|".join(re.escape(label) for label in labels), re.IGNORECASE)
    try:
        locator = scope.get_by_role("button", name=pattern)
        count = await locator.count()
        for idx in range(min(count, 8)):
            button = locator.nth(idx)
            if await button.is_visible():
                try:
                    await button.click(timeout=timeout_ms)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


async def _click_text_by_labels(scope, labels: tuple[str, ...], *, timeout_ms: int = 2000) -> bool:
    pattern = re.compile("|".join(re.escape(label) for label in labels), re.IGNORECASE)
    try:
        locator = scope.get_by_text(pattern)
        count = await locator.count()
        for idx in range(min(count, 8)):
            node = locator.nth(idx)
            if await node.is_visible():
                try:
                    await node.click(timeout=timeout_ms)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


async def _fill_filter_search_box(scope, page, value: str) -> bool:
    for selector in FILTER_SEARCH_INPUT_SELECTORS:
        try:
            locator = scope.locator(selector)
            count = await locator.count()
            for idx in range(count):
                box = locator.nth(idx)
                if await box.is_visible() and await box.is_enabled():
                    await box.fill("")
                    await box.fill(value)
                    await page.wait_for_timeout(700)
                    return True
        except Exception:
            continue
    return False


async def _collect_visible_industry_options(scope) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()

    try:
        labels = scope.locator("label")
        count = await labels.count()
        for idx in range(min(count, 300)):
            label = labels.nth(idx)
            if not await label.is_visible():
                continue
            text = re.sub(r"\s+", " ", (await label.inner_text()).strip())
            normalized = _normalize_text(text)
            if len(normalized) >= 3 and normalized not in seen:
                texts.append(text)
                seen.add(normalized)
    except Exception:
        pass

    try:
        checkboxes = scope.get_by_role("checkbox")
        count = await checkboxes.count()
        for idx in range(min(count, 150)):
            item = checkboxes.nth(idx)
            text = await item.evaluate(
                """
                el => (el.getAttribute('aria-label')
                    || el.labels?.[0]?.innerText
                    || el.closest('label')?.innerText
                    || '')
                """
            )
            text = re.sub(r"\s+", " ", str(text or "").strip())
            normalized = _normalize_text(text)
            if len(normalized) >= 3 and normalized not in seen:
                texts.append(text)
                seen.add(normalized)
    except Exception:
        pass

    return texts


def _pick_best_industry_option(requested: str, options: list[str]) -> str | None:
    best_option: str | None = None
    best_score = 0.0

    for variant in _expand_industry_variants(requested):
        for option in options:
            score = _score_text_match(variant, option)
            if score > best_score:
                best_option = option
                best_score = score

    return best_option if best_option and best_score >= 58.0 else None


async def _select_checkbox_by_text(scope, page, label_text: str) -> bool:
    exact_pattern = re.compile(rf"^\s*{re.escape(label_text)}\s*$", re.IGNORECASE)
    contains_pattern = re.compile(re.escape(label_text), re.IGNORECASE)

    for pattern in (exact_pattern, contains_pattern):
        try:
            checkbox = scope.get_by_role("checkbox", name=pattern)
            count = await checkbox.count()
            for idx in range(min(count, 5)):
                candidate = checkbox.nth(idx)
                if await candidate.is_visible():
                    try:
                        if not await candidate.is_checked():
                            await candidate.check(timeout=2000)
                        await page.wait_for_timeout(350)
                        return True
                    except Exception:
                        try:
                            await candidate.click(timeout=2000)
                            await page.wait_for_timeout(350)
                            return True
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            label_locator = scope.locator("label").filter(has_text=pattern)
            count = await label_locator.count()
            for idx in range(min(count, 5)):
                label = label_locator.nth(idx)
                if await label.is_visible():
                    await label.click(timeout=2000)
                    await page.wait_for_timeout(350)
                    return True
        except Exception:
            pass

    return False


async def _apply_industry_filters(page, industries: list[str]) -> str:
    requested = [item.strip() for item in industries if str(item).strip()]
    if not requested:
        return page.url

    opened = await _click_button_by_labels(page, INDUSTRY_BUTTON_LABELS, timeout_ms=2500)
    if not opened:
        opened = await _click_button_by_labels(page, ALL_FILTERS_BUTTON_LABELS, timeout_ms=2500)
        if not opened:
            raise RuntimeError("не найдена кнопка 'Отрасли' / 'All filters'")
        await page.wait_for_timeout(900)
        scope = await _get_active_filter_scope(page)
        if not await _click_button_by_labels(scope, INDUSTRY_BUTTON_LABELS, timeout_ms=2000):
            await _click_text_by_labels(scope, INDUSTRY_BUTTON_LABELS, timeout_ms=2000)
    else:
        await page.wait_for_timeout(700)

    scope = await _get_active_filter_scope(page)
    selected: list[str] = []
    missing: list[str] = []

    for industry in sorted(requested, key=len, reverse=True):
        matched_variant: str | None = None

        for variant in _expand_industry_variants(industry):
            await _fill_filter_search_box(scope, page, variant)
            visible_options = await _collect_visible_industry_options(scope)
            best_option = _pick_best_industry_option(industry, visible_options)

            if best_option and await _select_checkbox_by_text(scope, page, best_option):
                matched_variant = best_option
                break

            if await _select_checkbox_by_text(scope, page, variant):
                matched_variant = variant
                break

        if matched_variant:
            if _normalize_text(matched_variant) == _normalize_text(industry):
                selected.append(industry)
            else:
                selected.append(f"{industry} → {matched_variant}")
        else:
            visible_options = await _collect_visible_industry_options(scope)
            if visible_options:
                preview = "; ".join(visible_options[:8])
                print(f"   • Доступные варианты LinkedIn сейчас: {preview}", flush=True)
            missing.append(industry)

    if selected:
        print(f"   • Отрасли LinkedIn: {', '.join(selected)}", flush=True)
    if missing:
        print(f"   ⚠ Не удалось найти отрасли в фильтре LinkedIn: {', '.join(missing)}", flush=True)

    applied = await _click_button_by_labels(scope, APPLY_FILTER_BUTTON_LABELS, timeout_ms=3000)
    if not applied:
        applied = await _click_text_by_labels(scope, APPLY_FILTER_BUTTON_LABELS, timeout_ms=3000)

    if applied:
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
    else:
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        except Exception:
            pass

    return page.url


async def _get_job_cards(page) -> tuple[str | None, list[Any]]:
    for selector in STRICT_CARD_SELECTORS:
        cards = await page.query_selector_all(selector)
        if cards:
            return selector, cards

    # Fallback может зацепить рекомендации типа "Jobs you may be interested in".
    # Поэтому применяем его только если на странице нет явного признака пустой выдачи.
    if await _has_no_results_indicator(page):
        return None, []

    for selector in FALLBACK_CARD_SELECTORS:
        cards = await page.query_selector_all(selector)
        if cards:
            return selector, cards
    return None, []


async def _has_no_results_indicator(page) -> bool:
    try:
        body_text = (await page.locator("body").inner_text(timeout=2000)).lower()
    except Exception:
        return False

    markers = [
        "no matching jobs found",
        "no jobs found",
        "we couldn't find",
        "we couldn’t find",
        "no exact matches",
        "didn't find any jobs",
        "didn’t find any jobs",
        "не удалось обнаружить ни одной вакансии",
        "не найдено вакансий",
        "не найдено подходящих вакансий",
        "вакансий не найдено",
        "geen vacatures",
        "geen resultaten",
    ]

    return any(marker in body_text for marker in markers)


async def _dismiss_known_popups(page) -> int:
    closed = 0
    for selector in POPUP_BUTTON_SELECTORS:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for idx in range(min(count, 3)):
                button = locator.nth(idx)
                if await button.is_visible():
                    await button.click(timeout=1500)
                    closed += 1
                    await page.wait_for_timeout(600)
                    break
        except Exception:
            continue
    return closed


async def _describe_page_state(page) -> str:
    try:
        title = (await page.title()).strip()
    except Exception:
        title = "<title unavailable>"

    url = page.url
    try:
        body_text = (await page.locator("body").inner_text(timeout=2000)).lower()
    except Exception:
        body_text = ""

    if "login" in url.lower() or "sign in" in title.lower() or "войти" in body_text:
        return f"похоже, страница требует входа в LinkedIn | title='{title}' | url={url}"

    no_results_markers = [
        "no matching jobs found",
        "no jobs found",
        "geen vacatures",
        "geen resultaten",
        "we couldn’t find",
        "we couldn't find",
        "no exact matches",
        "didn't find any jobs",
        "didn’t find any jobs",
        "не удалось обнаружить ни одной вакансии",
        "не найдено вакансий",
        "не найдено подходящих вакансий",
        "вакансий не найдено",
    ]
    if any(marker in body_text for marker in no_results_markers):
        return f"по текущим фильтрам LinkedIn не показывает вакансии | title='{title}' | url={url}"

    popup_markers = [
        "premium",
        "cookie",
        "cookies",
        "notification",
        "meldingen",
        "notificaties",
        "try premium",
        "advertisement",
        "advertentie",
    ]
    if any(marker in body_text for marker in popup_markers):
        return f"похоже, выдачу перекрывает баннер/попап | title='{title}' | url={url}"

    return f"не удалось распознать состояние страницы | title='{title}' | url={url}"


def _windows_debug_browser_hint() -> str:
    return (
        '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
        '--remote-debugging-port=9222 --user-data-dir="C:\\Projects\\cv_adapter\\.chrome-debug-profile"'
    )


def _debug_port_available() -> bool:
    import httpx

    debug_url = config.LINKEDIN_CHROME_DEBUG_URL.rstrip("/")
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(f"{debug_url}/json/version")
            response.raise_for_status()
        return True
    except Exception:
        return False


def _find_browser_executable() -> str | None:
    configured = (config.LINKEDIN_BROWSER_PATH or "").strip()
    if configured and Path(configured).exists():
        return configured

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _launch_debug_browser() -> str:
    browser_path = _find_browser_executable()
    if not browser_path:
        raise FileNotFoundError(
            "Не найден Chrome/Edge. Установите Google Chrome или укажите путь в LINKEDIN_BROWSER_PATH."
        )

    parsed = urlparse(config.LINKEDIN_CHROME_DEBUG_URL)
    port = parsed.port or 9222
    user_data_dir = Path(config.LINKEDIN_BROWSER_USER_DATA_DIR).expanduser()
    user_data_dir.mkdir(parents=True, exist_ok=True)

    args = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        config.LINKEDIN_BROWSER_START_URL,
    ]

    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return browser_path


def _ensure_debug_browser_available() -> None:
    if _debug_port_available():
        print("      • Debug browser уже запущен.", flush=True)
        return

    if not config.LINKEDIN_AUTO_START_BROWSER:
        raise RuntimeError(
            "Не найден браузер с включённым remote debugging.\n"
            f"Запустите Chrome/Edge так:\n  {_windows_debug_browser_hint()}"
        )

    print("      • Debug browser не найден — запускаю автоматически...", flush=True)
    browser_path = _launch_debug_browser()

    deadline = time.time() + 15.0
    while time.time() < deadline:
        if _debug_port_available():
            print(f"      • Запущен браузер: {browser_path}", flush=True)
            print(
                "      • Если это первый запуск, войдите в LinkedIn в открывшемся окне и повторите поиск.",
                flush=True,
            )
            return
        time.sleep(1.0)

    raise RuntimeError(
        "Браузер был запущен, но debug-порт не поднялся вовремя.\n"
        f"Проверьте окно браузера или запустите вручную:\n  {_windows_debug_browser_hint()}"
    )


async def _scrape_linkedin_search(page, search: dict[str, Any], scrape_cap: int, known_urls: set[str]) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    seen_urls = set(known_urls)
    start = 0
    page_num = 1
    filtered_base_url: str | None = None

    raw_date_range = search.get("date_range", "r604800")
    industries = search.get("industries") or []
    industry_codes = search.get("industry_codes") or []
    print(f"\n🔍 LinkedIn поиск: {search['keywords']}", flush=True)
    print(f"   • Локация: {search.get('location', 'any')}", flush=True)
    print(f"   • Период: {_humanize_date_range(raw_date_range)} ({raw_date_range})", flush=True)
    print(f"   • Вес позиции: {float(search.get('weight', 1.0) or 1.0):g}", flush=True)
    print(f"   • Квота на этот проход: до {scrape_cap} вакансий", flush=True)
    print(f"   • Уровни: {_fmt_optional_list(search.get('experience_levels') or [])}", flush=True)
    print(f"   • Типы занятости: {_fmt_optional_list(search.get('job_types') or [])}", flush=True)
    print(f"   • Отрасли: {_fmt_optional_list(industries)}", flush=True)
    if industry_codes:
        print(f"   • Коды отраслей LinkedIn (f_I): {', '.join(industry_codes)}", flush=True)
        print("   • Фильтр отраслей будет применён через URL-параметр f_I.", flush=True)
    print(
        "   • Пагинация LinkedIn: start=0,25,50... это смещение результатов, а не число добавленных вакансий.",
        flush=True,
    )

    while len(jobs) < scrape_cap:
        if _check_stop_requested():
            print("   ⚠ Получен сигнал остановки — прекращаю LinkedIn поиск.", flush=True)
            break

        url = _replace_query_param(filtered_base_url, "start", start) if filtered_base_url else build_linkedin_url(search, start)
        print(f"   📄 Page {page_num} (start={start})", flush=True)

        try:
            navigation_issue = None
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=config.LINKEDIN_NAVIGATION_TIMEOUT_MS,
                )
            except Exception as nav_error:
                navigation_issue = nav_error
                print(
                    "   ⚠ Навигация страницы сработала нестабильно — проверяю, открылась ли выдача фактически.",
                    flush=True,
                )

            await page.wait_for_timeout(config.LINKEDIN_PAGE_LOAD_WAIT_MS)

            page_url = page.url.lower()
            page_title = (await page.title()).strip()
            if "login" in page_url or "sign in" in page_title.lower():
                raise RuntimeError(
                    "LinkedIn требует вход. В debug-браузере нужно вручную войти в аккаунт пользователя."
                )

            dismissed = await _dismiss_known_popups(page)
            if dismissed:
                print(f"   • Закрыто всплывающих окон/баннеров: {dismissed}", flush=True)
                await page.wait_for_timeout(1500)

            if industries and start == 0 and filtered_base_url is None and not industry_codes:
                try:
                    filtered_base_url = await _apply_industry_filters(page, industries)
                except Exception as filter_error:
                    print(f"   ⚠ Не удалось применить фильтр 'Отрасли': {filter_error}", flush=True)
                    filtered_base_url = page.url

            for _ in range(max(1, int(config.LINKEDIN_SCROLL_ROUNDS))):
                await page.keyboard.press("End")
                await page.wait_for_timeout(1200)

            matched_selector, cards = await _get_job_cards(page)
            if not cards:
                dismissed_more = await _dismiss_known_popups(page)
                if dismissed_more:
                    print(f"   • Дополнительно закрыто баннеров: {dismissed_more}", flush=True)
                    await page.wait_for_timeout(1500)
                    matched_selector, cards = await _get_job_cards(page)

            if not cards:
                state = await _describe_page_state(page)
                if navigation_issue is not None:
                    print(f"   ⚠ Причина навигации: {navigation_issue}", flush=True)
                print(f"   ⚠ Карточки вакансий не найдены. Состояние: {state}", flush=True)
                break

            print(
                f"   • LinkedIn вернул карточек на странице: {len(cards)} (selector: {matched_selector})",
                flush=True,
            )

            new_this_page = 0
            skipped_duplicates = 0
            for card in cards:
                if len(jobs) >= scrape_cap:
                    break
                if _check_stop_requested():
                    break

                try:
                    link_el = await card.query_selector(
                        "a.job-card-container__link, a.job-card-list__title--link"
                    )
                    if not link_el:
                        continue

                    href = await link_el.get_attribute("href")
                    if not href:
                        continue

                    if href.startswith("http"):
                        job_url = href.split("?")[0]
                    else:
                        job_url = f"https://www.linkedin.com{href.split('?')[0]}"

                    if job_url in seen_urls:
                        skipped_duplicates += 1
                        continue

                    title = (await link_el.get_attribute("aria-label") or "").strip()
                    if not title:
                        strong = await link_el.query_selector("strong")
                        title = (await strong.inner_text()).strip() if strong else ""
                    if not title:
                        continue

                    company = ""
                    for selector in [
                        ".artdeco-entity-lockup__subtitle span",
                        ".job-card-container__primary-description",
                    ]:
                        el = await card.query_selector(selector)
                        if el:
                            company = (await el.inner_text()).strip()
                            if company:
                                break
                    if not company:
                        company = "Unknown"

                    location = ""
                    for selector in [
                        ".artdeco-entity-lockup__metadata span",
                        ".job-card-container__metadata-wrapper span",
                        ".job-card-container__metadata-item",
                    ]:
                        el = await card.query_selector(selector)
                        if el:
                            location = (await el.inner_text()).strip()
                            if location:
                                break
                    if not location:
                        location = str(search.get("location", ""))

                    description = ""
                    try:
                        await link_el.click()
                        await page.wait_for_timeout(2200)
                        for selector in [
                            ".jobs-description__content",
                            ".jobs-description",
                            ".show-more-less-html",
                        ]:
                            desc_el = await page.query_selector(selector)
                            if desc_el:
                                description = (await desc_el.inner_text()).strip()
                                if description:
                                    break
                    except Exception:
                        description = description or ""

                    jobs.append(
                        {
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": job_url,
                            "source": "linkedin",
                            "description": description,
                        }
                    )
                    seen_urls.add(job_url)
                    new_this_page += 1
                    print(f"      ✓ [{len(jobs)}] {title} @ {company}", flush=True)
                    await asyncio.sleep(config.LINKEDIN_CARD_DELAY_SEC)
                except Exception as e:
                    print(f"      ⚠ Пропуск карточки: {e}", flush=True)
                    continue

            print(
                f"   • Итого по странице: добавлено {new_this_page}, пропущено дубликатов {skipped_duplicates}",
                flush=True,
            )

            if new_this_page == 0:
                print("   ℹ Новых вакансий на странице нет — завершаю этот поиск.", flush=True)
                break

            start += 25
            page_num += 1
            await asyncio.sleep(config.LINKEDIN_PAGE_DELAY_SEC)
        except Exception as e:
            print(f"   ✗ Ошибка страницы LinkedIn: {e}", flush=True)
            break

    print(f"   ✅ Поиск завершён: {len(jobs)} вакансий", flush=True)
    return jobs


async def _collect_jobs(search_profile: list[dict[str, Any]], existing_urls: set[str]) -> list[dict[str, str]]:
    async_playwright = _require_playwright()
    _ensure_debug_browser_available()

    all_jobs: list[dict[str, str]] = []
    debug_url = config.LINKEDIN_CHROME_DEBUG_URL.rstrip("/")
    total_cap = max(0, int(config.LINKEDIN_SCRAPE_CAP))
    initial_caps = _build_weighted_caps(search_profile, total_cap)

    print("\n📊 Распределение общего лимита по весам:", flush=True)
    for idx, search in enumerate(search_profile, start=1):
        print(
            f"   [{idx}] {search['keywords']} | вес={float(search.get('weight', 1.0) or 1.0):g} | стартовая квота={initial_caps[idx - 1]}",
            flush=True,
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(debug_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(30000)

        try:
            shared_pool = 0
            top_up_candidates: list[dict[str, Any]] = []

            for idx, search in enumerate(search_profile):
                if _check_stop_requested():
                    break

                allocated = initial_caps[idx]
                remaining_global = max(0, total_cap - len(all_jobs))
                allocated = min(allocated, remaining_global)
                if allocated <= 0:
                    continue

                known_urls = set(existing_urls)
                known_urls.update(job["url"] for job in all_jobs if job.get("url"))
                jobs = await _scrape_linkedin_search(page, search, allocated, known_urls)
                all_jobs.extend(jobs)

                found = len(jobs)
                unused = max(0, allocated - found)
                if unused > 0:
                    shared_pool += unused
                    print(
                        f"   • '{search['keywords']}' использовал {found} из {allocated}; возвращаю в общий пул {unused}.",
                        flush=True,
                    )

                # Кандидат на добор только если позиция показала хорошую отдачу и упёрлась в квоту.
                if found >= allocated and allocated > 0:
                    top_up_candidates.append(search)

                if len(all_jobs) >= total_cap:
                    print("⚠ Достигнут лимит LinkedIn_SCRAPE_CAP — остановка.", flush=True)
                    break

            if shared_pool > 0 and len(all_jobs) < total_cap and not _check_stop_requested():
                if not top_up_candidates:
                    print(
                        f"\nℹ В общем пуле осталось {shared_pool}, но нет позиций с доказанной отдачей для добора — второй проход пропускаю.",
                        flush=True,
                    )
                else:
                    print(
                        f"\n🔄 Запускаю добор из общего пула: осталось {shared_pool} вакансий для перераспределения.",
                        flush=True,
                    )
                    progress_made = True
                    while shared_pool > 0 and len(all_jobs) < total_cap and progress_made:
                        progress_made = False
                        for search in sorted(top_up_candidates, key=_weight_sort_key, reverse=True):
                            if shared_pool <= 0 or len(all_jobs) >= total_cap or _check_stop_requested():
                                break

                            top_up = min(shared_pool, max(0, total_cap - len(all_jobs)))
                            if top_up <= 0:
                                break

                            print(
                                f"   • Добор для '{search['keywords']}' (вес={float(search.get('weight', 1.0) or 1.0):g}): ещё до {top_up} вакансий.",
                                flush=True,
                            )
                            known_urls = set(existing_urls)
                            known_urls.update(job["url"] for job in all_jobs if job.get("url"))
                            extra_jobs = await _scrape_linkedin_search(page, search, top_up, known_urls)
                            used = len(extra_jobs)
                            all_jobs.extend(extra_jobs)

                            if used > 0:
                                shared_pool -= used
                                progress_made = True
                                print(
                                    f"   • Добор из '{search['keywords']}': найдено ещё {used}; в пуле осталось {shared_pool}.",
                                    flush=True,
                                )
                            else:
                                print(
                                    f"   • Для '{search['keywords']}' дополнительных вакансий не найдено; убираю из кандидатов на добор.",
                                    flush=True,
                                )
                        if not progress_made and shared_pool > 0:
                            print(
                                f"   ℹ Оставшиеся {shared_pool} вакансий в пуле не удалось добрать по доступным позициям.",
                                flush=True,
                            )
        finally:
            await page.close()

    return all_jobs


def _make_sheet_row(headers: list[str], job: dict[str, str]) -> list[str]:
    row = [""] * len(headers)
    mapping = {
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "Title": job.get("title", ""),
        "Company": job.get("company", ""),
        "Location": job.get("location", ""),
        config.COL_URL: job.get("url", ""),
        "Source": job.get("source", "linkedin"),
        config.COL_DESCRIPTION: job.get("description", ""),
        config.COL_BASE_SCORING: "",
        config.COL_ADDITIONAL_SCORING: "",
        config.COL_SUMMARY_SCORING: "",
        config.COL_WRONG_PHRASES: "",
        config.COL_TRACKER_ID: "",
    }

    for col_idx, header in enumerate(headers):
        for col_name, value in mapping.items():
            if (header or "").strip().lower() == (col_name or "").strip().lower():
                row[col_idx] = value
                break
    return row


def run_linkedin_search_import(*, client) -> tuple[int, int, int]:
    """
    Запускает импорт вакансий из LinkedIn в Search DataBase.

    Возвращает:
      (найдено вакансий, добавлено новых строк, пропущено дубликатов)
    """
    worksheet, headers, existing_urls = _ensure_search_database_sheet(client)
    search_profile = read_primary_filter_rows(client)

    if not search_profile:
        print(f"      ℹ В '{config.SHEET_PRIMARY_FILTER}' нет активных поисков (active=TRUE).", flush=True)
        return 0, 0, 0

    print(
        f"      • Активных поисков: {len(search_profile)}; известных URL: {len(existing_urls)}; лимит: {config.LINKEDIN_SCRAPE_CAP}",
        flush=True,
    )

    jobs = asyncio.run(_collect_jobs(search_profile, existing_urls))
    if not jobs:
        return 0, 0, 0

    rows_to_append: list[list[str]] = []
    skipped = 0

    for job in jobs:
        url = (job.get("url") or "").strip()
        if not url:
            skipped += 1
            continue
        if url in existing_urls:
            skipped += 1
            continue
        rows_to_append.append(_make_sheet_row(headers, job))
        existing_urls.add(url)

    if rows_to_append:
        worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    return len(jobs), len(rows_to_append), skipped
