"""
Helper to build `linkedin_industry_map.json` from real LinkedIn Jobs URLs.

Recommended workflow:
1) In LinkedIn Jobs, select ONE industry manually.
2) Copy the resulting URL from the browser.
3) Run:
   python scripts/linkedin_industry_dictionary.py --url "<url>" --industries "Разработка программного обеспечения"
4) Repeat for the next industry.

Notes:
- The code is extracted from URL parameter `f_I`.
- If a URL contains multiple industry codes, exact mapping is ambiguous.
  Use one industry per manual search for a reliable dictionary, or pass `--pairwise`
  only when you explicitly want to map names and codes in the same order.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MAP_FILE = BASE_DIR / "linkedin_industry_map.json"


def _split_names(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]", raw or "") if part.strip()]


def _extract_codes(url: str) -> list[str]:
    query = parse_qs(urlparse(url).query)
    raw = (query.get("f_I") or [""])[0]
    return [code.strip() for code in raw.split(",") if code.strip()]


def _load_map(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_map(path: Path, data: dict[str, list[str]]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _show_map(path: Path, data: dict[str, list[str]]) -> None:
    print(f"Файл словаря: {path}")
    if not data:
        print("Словарь пока пуст.")
        return
    for name, codes in sorted(data.items(), key=lambda item: item[0].lower()):
        if isinstance(codes, str):
            codes = [codes]
        print(f"- {name}: {', '.join(str(code) for code in codes)}")


def _upsert_mapping(data: dict[str, list[str]], name: str, codes: list[str]) -> None:
    existing = data.get(name, [])
    if isinstance(existing, str):
        existing = [existing]
    merged = list(dict.fromkeys([*(str(code).strip() for code in existing), *(str(code).strip() for code in codes)]))
    data[name] = [code for code in merged if code]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local LinkedIn industry dictionary from a Jobs search URL")
    parser.add_argument("--url", help="LinkedIn jobs URL containing f_I=...")
    parser.add_argument("--industries", help="Industry names/aliases separated by ';'")
    parser.add_argument("--pairwise", action="store_true", help="Map names to codes in the same order when counts match")
    parser.add_argument("--show", action="store_true", help="Print current dictionary and exit")
    parser.add_argument("--map-file", default=str(DEFAULT_MAP_FILE), help="Path to JSON dictionary file")
    args = parser.parse_args()

    map_file = Path(args.map_file).expanduser().resolve()
    data = _load_map(map_file)

    if args.show:
        _show_map(map_file, data)
        return

    url = (args.url or input("Вставьте LinkedIn URL: ").strip())
    codes = _extract_codes(url)
    if not codes:
        raise SystemExit("В URL не найден параметр f_I. Сначала выберите отрасль(и) в LinkedIn Jobs.")

    print(f"Найдены коды отраслей (f_I): {', '.join(codes)}")

    names_raw = args.industries
    if names_raw is None:
        names_raw = input("Названия отраслей через ';' (или Enter, чтобы только посмотреть коды): ").strip()
    names = _split_names(names_raw)
    if not names:
        print("Сохранение пропущено — показаны только коды.")
        return

    if len(codes) == 1:
        for name in names:
            _upsert_mapping(data, name, codes)
        _save_map(map_file, data)
        print(f"Сохранено в словарь: {', '.join(names)} -> {codes[0]}")
        print(f"Файл: {map_file}")
        return

    if args.pairwise:
        if len(names) != len(codes):
            raise SystemExit(
                f"Нельзя сопоставить pairwise: names={len(names)}, codes={len(codes)}. "
                "Используйте один industry на один URL или выровняйте количество."
            )
        for name, code in zip(names, codes):
            _upsert_mapping(data, name, [code])
        _save_map(map_file, data)
        print("Сохранено pairwise:")
        for name, code in zip(names, codes):
            print(f"- {name} -> {code}")
        print(f"Файл: {map_file}")
        return

    print("\n⚠ В URL несколько кодов, поэтому точное сопоставление неоднозначно.")
    print("Рекомендуемый простой способ:")
    print("  1. В LinkedIn выбрать ОДНУ отрасль")
    print("  2. Скопировать URL")
    print("  3. Запустить этот скрипт ещё раз")
    print("\nЕсли вы уверены, что порядок совпадает, можно повторить с флагом --pairwise.")


if __name__ == "__main__":
    main()
