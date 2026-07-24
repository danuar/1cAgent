#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Поиск по локальному дампу ПОЛНОЙ типовой конфигурации (CFG["reference_config"],
см. src/core/config.py _REFERENCE_CONFIG_HINT — путь личный, под конкретную
машину, автопоиска нет). Дешёвые маленькие XML-примеры вместо угадывания
формата по памяти (см. HANDOFF.md "правило эскалации", #34).

Grep (re + Path.rglob), НЕ векторный/семантический поиск — для точных XML-
паттернов (тег/атрибут) это надёжнее и не требует инфраструктуры эмбеддингов.
Чистый Python, БЕЗ внешней зависимости от ripgrep-бинарника: `rg` недоступен
в PATH на этой машине (проверено), и требовать его отдельной установки от
других пользователей (см. README) — лишний барьер входа.

Обе функции возвращают МАЛЕНЬКИЕ фрагменты, не целые файлы — read_reference_
snippet дополнительно жёстко ограничен по числу строк за раз и не даёт выйти
путём за пределы reference_config (path traversal).
"""
import re
from pathlib import Path

_MAX_MATCHES_CAP = 100
_MAX_FILES_SCANNED = 20000  # защита от неограниченного по времени скана на 100К+ файлах
_CONTEXT_CHARS = 120
_MAX_SNIPPET_LINES = 400


def _reference_root(cfg: dict):
    root = cfg.get("reference_config")
    if not root or not Path(root).is_dir():
        return None
    return Path(root)


def search_reference(cfg: dict, pattern: str, glob: str = "**/*.xml", max_matches: int = 40) -> dict:
    root = _reference_root(cfg)
    if root is None:
        return {"ok": False, "reason": f"reference_config не настроен или папка не найдена: "
                                        f"{cfg.get('reference_config')!r} — см. src/core/config.py _REFERENCE_CONFIG_HINT"}
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "reason": f"невалидный regex: {e}"}

    max_matches = max(1, min(max_matches, _MAX_MATCHES_CAP))
    matches, scanned = [], 0
    for fp in root.rglob(glob or "**/*.xml"):
        if not fp.is_file():
            continue
        scanned += 1
        if scanned > _MAX_FILES_SCANNED:
            break
        try:
            text = fp.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        for m in rx.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            start = max(0, m.start() - _CONTEXT_CHARS)
            end = min(len(text), m.end() + _CONTEXT_CHARS)
            matches.append({
                "path": str(fp.relative_to(root)),
                "line": line_no,
                "match": m.group(0)[:200],
                "context": text[start:end].replace("\n", "\\n"),
            })
            if len(matches) >= max_matches:
                break
        if len(matches) >= max_matches:
            break

    return {"ok": True, "root": str(root), "files_scanned": scanned,
            "matches": matches, "truncated": len(matches) >= max_matches}


def read_reference_snippet(cfg: dict, path: str, start_line: int = 1, end_line: int = 200) -> dict:
    root = _reference_root(cfg)
    if root is None:
        return {"ok": False, "reason": f"reference_config не настроен или папка не найдена: {cfg.get('reference_config')!r}"}

    fp = (root / path).resolve()
    try:
        fp.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "reason": "путь вне reference_config — отказано"}
    if not fp.is_file():
        return {"ok": False, "reason": f"файл не найден: {path}"}

    if end_line - start_line + 1 > _MAX_SNIPPET_LINES:
        return {"ok": False, "reason": f"запрошено больше {_MAX_SNIPPET_LINES} строк за раз — сузьте диапазон"}

    lines = fp.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    chunk = lines[max(0, start_line - 1):end_line]
    return {"ok": True, "path": path, "start_line": start_line,
            "text": "\n".join(chunk), "total_lines": len(lines)}
