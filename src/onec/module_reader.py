#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точечное чтение .bsl-файлов: вместо перечитывания всего модуля (в этой сессии
единственный модуль на 40+ тыс. симв. читался Read'ом 7 раз целиком) можно
запросить outline (список Процедура/Функция с номерами строк) или тело ровно
одной процедуры/функции. Процедуры/функции в BSL не вкладываются друг в друга,
поэтому парсинг построчный без стека.
"""
import re

_START_RE = re.compile(r'^\s*(Процедура|Функция)\s+([A-Za-zА-Яа-яЁё0-9_]+)', re.IGNORECASE)
_END_RE = {
    "процедура": re.compile(r'^\s*КонецПроцедуры', re.IGNORECASE),
    "функция": re.compile(r'^\s*КонецФункции', re.IGNORECASE),
}


def outline(text: str) -> list:
    """[{"line": N, "kind": "Процедура"|"Функция", "name": "..."}], построчно, дёшево."""
    result = []
    for idx, line in enumerate(text.splitlines(), start=1):
        m = _START_RE.match(line)
        if m:
            result.append({"line": idx, "kind": m.group(1), "name": m.group(2)})
    return result


def extract_procedure(text: str, name: str):
    """Тело процедуры/функции name (с шапкой и КонецПроцедуры/КонецФункции) или None, если не найдена."""
    lines = text.splitlines()
    name_lower = name.lower()
    i = 0
    while i < len(lines):
        m = _START_RE.match(lines[i])
        if m and m.group(2).lower() == name_lower:
            end_re = _END_RE[m.group(1).lower()]
            j = i + 1
            while j < len(lines) and not end_re.match(lines[j]):
                j += 1
            j = min(j, len(lines) - 1)
            return "\n".join(lines[i:j + 1])
        i += 1
    return None
