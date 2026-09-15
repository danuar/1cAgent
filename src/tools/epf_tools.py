#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#65, РЕЖИМ B: правка внешних обработок С ФОРМАМИ без ручного конфигуратора.
Вся механика и грабли с двумя форматами выгрузки — в src/onec/epf_build.py.
Раньше единственным способом поменять код формы-раннера было "открой .epf в
конфигураторе и вставь текст руками".
"""
from pathlib import Path

from src.tools.core import mcp, CFG
from src.onec.epf_build import (read_form_module as _read_form_module,
                                write_form_module as _write_form_module,
                                patch_form_module as _patch_form_module,
                                dump_epf as _dump_epf,
                                build_epf as _build_epf)


def _resolve(epf_path: str) -> str:
    """Пустой путь = форма-раннер агента (самый частый случай)."""
    return epf_path or CFG["epf_runner"]


@mcp.tool()
def read_epf_form_module(epf_path: str = "", form_name: str = "Форма",
                         ib_connection: str = "") -> dict:
    """Чтение. Модуль формы из .epf (epf_path пустой = раннер агента) → {ok, module, path, types}; types.degraded=True — типы реквизитов потеряны.
    ib_connection — родная база обработки; иначе ссылочные типы реквизитов молча схлопываются в строку. Пустой = compiler_db, годится только для раннера агента."""
    return _read_form_module(CFG, _resolve(epf_path), form_name=form_name,
                             ib_connection=ib_connection)


@mcp.tool()
def write_epf_form_module(module_text: str = "", epf_path: str = "",
                          form_name: str = "Форма", module_path: str = "",
                          ib_connection: str = "", allow_type_loss: bool = False) -> dict:
    """Заменить модуль формы внутри .epf (dump→подмена→сборка во временный файл, .epf.bak рядом). Текст — module_text или файл module_path. Гейты: ParseError и потеря типов (allow_type_loss=True снимает). Открытая в 1С обработка увидит изменения после переоткрытия.
    ib_connection — родная база обработки; иначе ссылочные типы реквизитов молча схлопываются в строку. Пустой = compiler_db, годится только для раннера агента."""
    if not module_text and module_path:
        p = Path(module_path)
        if not p.exists():
            return {"ok": False, "reason": f"нет файла модуля: {p}"}
        module_text = p.read_text(encoding="utf-8-sig")
    if not module_text:
        return {"ok": False, "reason": "нужен module_text или module_path"}
    return _write_form_module(CFG, _resolve(epf_path), module_text, form_name=form_name,
                              ib_connection=ib_connection, allow_type_loss=allow_type_loss)


@mcp.tool()
def patch_epf_form_module(replacements: list, epf_path: str = "", form_name: str = "Форма",
                          ib_connection: str = "", allow_type_loss: bool = False) -> dict:
    """Точечная правка модуля формы: replacements — [{old, new}], каждый old ровно 1 раз в модуле, иначе отказ целиком; пустой new удаляет. Гейты как у write_epf_form_module.
    ib_connection — родная база обработки; иначе ссылочные типы реквизитов молча схлопываются в строку. Пустой = compiler_db, годится только для раннера агента."""
    return _patch_form_module(CFG, _resolve(epf_path), replacements, form_name=form_name,
                              ib_connection=ib_connection, allow_type_loss=allow_type_loss)


@mcp.tool()
def dump_external_processing(epf_path: str, out_dir: str, ib_connection: str = "") -> dict:
    """Чтение. .epf → плоская выгрузка в out_dir (пересоздаётся) → {ok, root_xml, files, types}; перед сборкой проверять types.degraded.
    ib_connection — родная база обработки; иначе ссылочные типы реквизитов молча схлопываются в строку. Пустой = compiler_db, годится только для раннера агента."""
    return _dump_epf(CFG, epf_path, out_dir, ib_connection=ib_connection)


@mcp.tool()
def build_external_processing(root_xml: str, target_epf: str, ib_connection: str = "") -> dict:
    """Собрать .epf из плоской выгрузки. root_xml — путь к корневому Имя.xml (файл, не каталог).
    ib_connection — родная база обработки; иначе ссылочные типы реквизитов молча схлопываются в строку. Пустой = compiler_db, годится только для раннера агента."""
    return _build_epf(CFG, root_xml, target_epf, ib_connection=ib_connection)
