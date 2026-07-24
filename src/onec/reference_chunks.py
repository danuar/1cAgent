#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#54: разбор эталонного корпуса (CFG["reference_config"]) на ЧАНКИ ОТДЕЛЬНЫХ
процедур/функций — для семантического индекса (см. embeddings_client.py/
semantic_index.py). Переиспользует module_reader.outline() (уже парсит границы
Процедура/Функция построчно, без стека) — не пишем парсер заново.

Индексируем ВСЕ процедуры/функции, НЕ только Экспорт — сознательное решение
(обсуждено с пользователем): типичный паттерн БСП — тонкая Экспорт-обёртка
вызывает ЗАКРЫТУЮ процедуру с реальной логикой ("Функция Пересчитать(...)
Экспорт Возврат ПересчитатьВнутренняя(...) КонецФункции") — если
индексировать только Экспорт, найдётся пустая обёртка, а вся СУТЬ (как именно
считается) останется невидимой. Реальный подсчёт на корпусе пользователя:
642669 процедур/функций всего, из них 209188 (~32.5%) — Экспорт (см.
HANDOFF #54 про то, как считали). Минус закрытых процедур — у них РЕЖЕ есть
doc-комментарий (комментарии "Параметры:/Возвращаемое значение:" пишут для
вызова ИЗВНЕ модуля) — но само ИМЯ процедуры в 1С обычно осмысленное русское
словосочетание, для эмбеддинга не провал.

Чанк — ИМЯ + doc-комментарий НАД процедурой, если есть — короткий текст для
эмбеддинга, НЕ тело процедуры целиком (тело может быть огромным, для
эмбеддинга важен СМЫСЛ, не код). Точное тело — отдельным шагом через
read_module(path, procedure=Имя), см. module_reader.py.
"""
import re
from pathlib import Path

from src.onec import module_reader

_EXPORT_RE = re.compile(r'\bЭкспорт\b', re.IGNORECASE)
_DOC_COMMENT_MAX_LINES = 15  # не тащить в чанк много — только шапку-комментарий


def _leading_comment(lines: list, decl_idx: int) -> str:
    """
    Комментарий НАД строкой объявления процедуры (decl_idx — 0-based индекс
    строки объявления). Идём вверх, пока строки НАЧИНАЮТСЯ с '//' — ОДНА
    пустая строка допускается как разделитель (частый паттерн: пустая строка
    между комментарием и Процедура/Функция), вторая пустая — останов.
    """
    out = []
    i = decl_idx - 1
    blank_seen = False
    while i >= 0 and len(out) < _DOC_COMMENT_MAX_LINES:
        line = lines[i].strip()
        if line.startswith("//"):
            out.append(line.lstrip("/ "))
            blank_seen = False
            i -= 1
        elif line == "" and not blank_seen:
            blank_seen = True
            i -= 1
        else:
            break
    return "\n".join(reversed(out))


def iter_export_chunks(root: Path):
    """
    Генератор {path, module, name, kind, line, export, comment} для КАЖДОЙ
    процедуры/функции во всех .bsl-файлах под root (Экспорт и закрытых —
    см. докстринг модуля про то, почему закрытые тоже нужны).
    path   — путь файла относительно root (для read_reference_snippet/чтения).
    module — путь БЕЗ хвоста /Ext/Module.bsl (например "CommonModules/
             ОбщегоНазначения") — то, что реально пишется в BSL как вызов
             "ОбщегоНазначения.Имя(...)" (для закрытых процедур вызов
             возможен только ИЗНУТРИ того же модуля — export=False сигналит
             об этом при показе результата).
    """
    for fp in root.rglob("*.bsl"):
        try:
            text = fp.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        lines = text.splitlines()
        for item in module_reader.outline(text):
            decl_idx = item["line"] - 1
            line_text = lines[decl_idx] if decl_idx < len(lines) else ""
            is_export = bool(_EXPORT_RE.search(line_text))
            rel = fp.relative_to(root)
            parts = rel.parts
            # #54: срез по КОМПОНЕНТАМ пути (Path.parts), НЕ строковым суффиксом —
            # строковый .endswith("/Ext/Module.bsl") ломается, если относительный
            # путь САМ начинается с "Ext/..." (без ведущего разделителя перед "Ext"),
            # найдено тестом на сужённом root. Компонентное сравнение устойчиво
            # к этому в любом случае.
            if len(parts) >= 2 and parts[-2] == "Ext" and parts[-1] in (
                    "Module.bsl", "ManagerModule.bsl", "ObjectModule.bsl"):
                module_path = "/".join(parts[:-2])
            else:
                module_path = "/".join(parts)
            yield {
                "path": str(rel),
                "module": module_path,
                "name": item["name"],
                "kind": item["kind"],
                "line": item["line"],
                "export": is_export,
                "comment": _leading_comment(lines, decl_idx),
            }


def chunk_embed_text(chunk: dict) -> str:
    """Короткий текст ИМЕННО для эмбеддинга — module+имя+вид+комментарий, без пути/строки (это метаданные, не смысл)."""
    parts = [f"{chunk['kind']} {chunk['module']}.{chunk['name']}"]
    if chunk["comment"]:
        parts.append(chunk["comment"])
    return "\n".join(parts)
