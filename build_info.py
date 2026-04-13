"""
build_info.py — сведения о сборке и коммите.
"""

from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

BUILD_INFO_FILE = "build_info.json"


def _runtime_dirs() -> list[Path]:
    script_dir = Path(__file__).resolve().parent
    dirs = [script_dir, Path.cwd()]

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        dirs.insert(0, exe_dir)
        if sys.platform == "darwin":
            dirs.insert(1, exe_dir.parent / "Resources")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in dirs:
        normalized = str(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(path)
    return unique


def _read_embedded_build_info() -> dict | None:
    for directory in _runtime_dirs():
        candidate = directory / BUILD_INFO_FILE
        if not candidate.exists():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _fallback_build_info() -> dict:
    commit = _git_output("rev-parse", "HEAD")
    short_commit = _git_output("rev-parse", "--short", "HEAD")
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    committed_at = _git_output("show", "-s", "--format=%cI", "HEAD")
    dirty = bool(_git_output("status", "--porcelain"))

    return {
        "source": "git" if commit else "unknown",
        "commit": commit,
        "commit_short": short_commit,
        "branch": branch,
        "built_at": committed_at,
        "dirty": dirty,
    }


@lru_cache(maxsize=1)
def get_build_info() -> dict:
    embedded = _read_embedded_build_info()
    if embedded:
        return embedded
    return _fallback_build_info()


def get_build_label() -> str:
    info = get_build_info()
    short_commit = info.get("commit_short") or info.get("commit") or "unknown"
    built_at = info.get("built_at") or ""
    if built_at:
        built_at = built_at.replace("T", " ")[:19]
        return f"{short_commit} @ {built_at}"
    return str(short_commit)


def get_build_log_line() -> str:
    info = get_build_info()
    parts = [
        f"source={info.get('source') or 'unknown'}",
        f"commit={info.get('commit_short') or info.get('commit') or 'unknown'}",
    ]
    if info.get("branch"):
        parts.append(f"branch={info['branch']}")
    if info.get("built_at"):
        parts.append(f"built_at={info['built_at']}")
    if info.get("dirty"):
        parts.append("dirty=yes")
    return "[build] " + " | ".join(parts)
