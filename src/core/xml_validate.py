#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML well-formedness check ПЕРЕД LoadConfigFromFiles — общая для module_deploy.py/
extension_deploy.py/metadata_deploy.py. Найдено вживую (#билет15): невалидный XML
(например неэкранированный "&" в тексте DCS-запроса) не даёт быструю понятную
ошибку — DESIGNER молча висит МИНУТАМИ с пустым /Out-логом, выглядит как
зависание, а не как ошибка формата. xml.etree.ElementTree.parse() ловит это за
миллисекунды, ДО похода в DESIGNER.
"""
import xml.etree.ElementTree as ET
from pathlib import Path


def validate_xml_files(paths) -> list:
    """paths — итерируемое путей (файлы НЕ-.xml и несуществующие тихо пропускаются).
    Возвращает список строк-ошибок вида "путь: причина" (пусто = всё чисто)."""
    problems = []
    for p in paths:
        p = Path(p)
        if p.suffix.lower() != ".xml" or not p.exists():
            continue
        try:
            ET.parse(str(p))
        except ET.ParseError as e:
            problems.append(f"{p}: {e}")
    return problems
