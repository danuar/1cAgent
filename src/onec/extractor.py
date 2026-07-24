#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Вырезание процедуры/функции по номеру строки ошибки 1С.
Чиним не весь модуль (не влезет в 5k), а только охватывающую
Процедуру/Функцию (~десятки строк), потом вклеиваем обратно.
Самопроверка:  python3 extractor.py
"""
import re

_HEADER = re.compile(r"^\s*(?:Асинхронная\s+)?(?:Процедура|Функция|Procedure|Function)\b", re.I)
_END = re.compile(r"^\s*(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b", re.I)
_DIRECTIVE = re.compile(r"^\s*&")                       # &НаКлиенте, &НаСервере ...
_NAME = re.compile(r"^\s*(?:Асинхронная\s+)?(?:Процедура|Функция|Procedure|Function)\s+([^\s(]+)", re.I)


def extract_function(code: str, line: int):
    """
    line — 1-based номер строки (как в ошибке 1С).
    -> {start, end, name, text, certain} (1-based, включительно) или None,
    если строка вне процедуры/функции (тело модуля / Перем / область).
    """
    lines = code.splitlines()
    n = len(lines)
    if line < 1 or line > n:
        return None
    idx = line - 1

    # ближайший заголовок на idx или выше
    header = None
    for i in range(idx, -1, -1):
        if _HEADER.match(lines[i]):
            header = i
            break
    if header is None:
        return None                       # тело модуля

    # ближайший Конец на header или ниже; битый модуль — режем по следующему заголовку
    end, certain = None, True
    for j in range(header + 1, n):
        if _END.match(lines[j]):
            end = j
            break
        if _HEADER.match(lines[j]):       # следующая функция раньше Конца
            end, certain = j - 1, False
            break
    if end is None:
        end, certain = n - 1, False
    if end < idx:
        return None                       # строка за концом функции → тело

    # прихватываем директивы &... прямо над заголовком
    start = header
    while start - 1 >= 0 and _DIRECTIVE.match(lines[start - 1]):
        start -= 1

    m = _NAME.match(lines[header])
    return {
        "start": start + 1,
        "end": end + 1,
        "name": m.group(1) if m else "?",
        "certain": certain,
        "text": "\n".join(lines[start:end + 1]),
    }


def replace_span(code: str, start: int, end: int, new_text: str) -> str:
    """Заменяет строки [start..end] (1-based, включительно) на new_text."""
    lines = code.splitlines()
    return "\n".join(lines[:start - 1] + new_text.splitlines() + lines[end:])


# ---- самопроверка ----
if __name__ == "__main__":
    MODULE = (
        "Перем КэшМетаданных;\n"                 # 1  тело модуля
        "\n"                                       # 2
        "&НаСервере\n"                             # 3
        "Функция ПолучитьСумму(Товары)\n"          # 4
        "    Сумма = 0;\n"                         # 5
        "    Для Каждого Стр Из Товары Цикл\n"     # 6
        "        Сумма = Сумма + Стр.Цена;\n"      # 7
        "    КонецДля;\n"                          # 8  <-- ошибка тут
        "    Возврат Сумма;\n"                     # 9
        "КонецФункции\n"                           # 10
        "\n"                                       # 11
        "Процедура Прочее()\n"                     # 12
        "    Сообщить(1);\n"                       # 13
        "КонецПроцедуры"                           # 14
    )
    for probe in (8, 13, 1):
        f = extract_function(MODULE, probe)
        print(f"\n--- строка {probe} ---")
        if f is None:
            print("вне функции (тело модуля)")
        else:
            print(f"{f['name']}  строки {f['start']}..{f['end']}  certain={f['certain']}")
            print(f["text"])
