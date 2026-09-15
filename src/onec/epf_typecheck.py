#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Страховка от тихой порчи .epf при разборке конфигуратором НЕ В ТОЙ БАЗЕ.

Живой случай, стоивший пользователю рабочего дня: внешнюю обработку из УТ 11.5
разбирали с /F compiler_db (пустая служебная база). Конфигуратор не смог
разрешить типы вроде СправочникСсылка.Номенклатура — их просто нет в той базе —
и записал в XML безобидное на вид

    <Type><v8:Type>xs:string</v8:Type>
      <v8:StringQualifiers><v8:Length>0</v8:Length>
        <v8:AllowedLength>Variable</v8:AllowedLength></v8:StringQualifiers></Type>

Сборка закрепила подмену. Обработка открывается, но поля выбора больше не поля
выбора, отбор по сегменту не работает, а код падает на Ссылка.Код с "Значение
не является значением объектного типа". Сравнение дампов НИЧЕГО не показывает:
дамп испорченного и дамп исходного совпадают, потому что оба сделаны той же
слепой базой.

Отсюда правило: строка неограниченной длины на месте реквизита формы — почти
всегда след схлопнутого ссылочного типа. Настоящих строк с Length=0 в формах
мало, поэтому эвристика даёт мало ложных срабатываний, а цена пропуска —
сломанная обработка у пользователя.
"""
import re
from pathlib import Path

# xs:string + Length 0 + AllowedLength Variable — подпись схлопнутого типа.
_SUSPECT = re.compile(
    r'<(Attribute|Column)\s+name="([^"]+)"[^>]*>'      # чей это тип
    r'(?:(?!</\1>).)*?'                                 # не выходя за его границы
    r'<v8:Type>xs:string</v8:Type>\s*'
    r'<v8:StringQualifiers>\s*<v8:Length>0</v8:Length>',
    re.S)

# Типы, которые ссылаются на объекты конфигурации. Если их в дампе нет совсем —
# база почти наверняка не та (сам объект обработки не в счёт, он всегда есть).
_CFG_TYPE = re.compile(r'<v8:Type>cfg:([A-Za-z]+)\.')


def scan_plain_dump(out_dir: str) -> dict:
    """
    Просмотреть плоскую выгрузку и оценить, не потеряны ли ссылочные типы.

    Возвращает {"degraded": bool, "suspects": [{"file", "kind", "name"}],
                "cfg_types": N, "reason": "..."} — где cfg_types считает только
    ссылки на объекты конфигурации, кроме самого ExternalDataProcessorObject.
    """
    out = Path(out_dir)
    suspects, cfg_types = [], 0

    for xml in sorted(out.glob("*.xml")):
        try:
            text = xml.read_text(encoding="utf-8")
        except Exception:
            continue
        for kind in _CFG_TYPE.findall(text):
            if kind not in ("ExternalDataProcessorObject", "ExternalReportObject"):
                cfg_types += 1
        for kind, name in ((m.group(1), m.group(2)) for m in _SUSPECT.finditer(text)):
            suspects.append({"file": xml.name, "kind": kind, "name": name})

    degraded = bool(suspects) and cfg_types == 0
    res = {"degraded": degraded, "suspects": suspects[:20],
           "suspects_total": len(suspects), "cfg_types": cfg_types}
    if degraded:
        res["reason"] = (
            f"в выгрузке {len(suspects)} реквизит(ов)/колонок типа «строка неограниченной "
            f"длины» и НИ ОДНОГО ссылочного типа конфигурации. Это подпись того, что "
            f"конфигуратор разбирал .epf в базе, где типов этой обработки не существует "
            f"(по умолчанию — compiler_db). Ссылочные типы реквизитов формы уже потеряны; "
            f"собирать обратно нельзя. Передайте ib_connection той базы, которой "
            f"принадлежит обработка."
        )
    return res
