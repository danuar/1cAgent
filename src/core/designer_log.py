#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Чтение /Out-логов DESIGNER/ENTERPRISE. Раньше декодирование (utf-8-sig с
errors="replace") повторялось вручную в каждом deploy_*.py — и молча ПОРТИЛО
кириллицу без единой ошибки, если конкретный лог реально пришёл в cp1251
(errors="replace" глотает UnicodeDecodeError, а не переключает кодировку).
Теперь: пробуем utf-8-sig, при первом же "плохом" байте (символ замены /FFFD
в первых 200 симв. — verify_utf8=True) откатываемся на cp1251.
"""
from pathlib import Path


def read_designer_log(path, tail: int = 0) -> str:
    """
    path — Path/str к файлу лога (может не существовать — тогда "").
    tail — если > 0, вернуть только последние tail символов.
    """
    p = Path(path)
    if not p.exists():
        return ""
    raw = p.read_bytes()
    if not raw:
        return ""

    text = raw.decode("utf-8-sig", errors="replace")
    if "�" in text[:200]:
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError:
            pass  # так и оставляем utf-8-sig с replace — лучше, чем упасть
    return text[-tail:] if tail else text
