#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Работа с .cfe КАК С ФАЙЛОМ: забрать расширение из базы через раннер и распаковать без конфигуратора."""
from src.tools.core import mcp, CFG
from src.onec.container_unpack import unpack as _unpack, extract_names, has_record_level_restrictions
from src.onec.extension_fetch import fetch_extension as _fetch


@mcp.tool()
def fetch_extension_file(ext_name: str, out_path: str = "") -> dict:
    """Скачать .cfe расширения из базы через живой раннер (без конфигуратора и ib_connection) → файл на диске {path,size,chunks}. Дальше unpack_extension_file."""
    return _fetch(CFG, ext_name, out_path)


@mcp.tool()
def unpack_extension_file(file_path: str, out_dir: str = "", with_names: bool = True) -> dict:
    """Распаковать .cfe/.cf с диска чистым Python (внутренний скобочный формат, не XML — не замена dump_extension). with_names=True → names[] (заимствованные объекты, роль) и rls{} (есть ли ограничения на уровне записей)."""
    if not out_dir:
        out_dir = file_path + ".unpacked"
    items = _unpack(file_path, out_dir)
    res = {"ok": bool(items), "out_dir": out_dir, "elements": len(items),
           "largest": sorted(items, key=lambda x: -x["size"])[:5]}
    if with_names:
        res["names"] = extract_names(out_dir)
        res["rls"] = has_record_level_restrictions(out_dir)
    return res
