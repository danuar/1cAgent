#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РЕЖИМ B — доставка объектов ОСНОВНОЙ конфигурации (не расширения):
Справочники/Документы/Регистры накопления/Регистры сведений/Подсистемы. См.
get_guide("main_config_overview") перед использованием — индекс узких тем
(InternalInfo по видам, типы реквизитов, грабли ПередЗаписью vs
ОбработкаПроведения, экранирование "&" в DCS-запросах). Границу охвата (что
НЕ обобщено — ПланСчетов/РегистрБухгалтерии/Отчёты/Формы/Перечисления) см. в
докстринге src/onec/metadata_deploy.py."""
from src.tools.core import mcp, CFG, _spawn
from src.onec.metadata_deploy import (
    dump_main_config as _dump_main_config,
    deploy_catalog as _deploy_catalog,
    deploy_document as _deploy_document,
    deploy_accumulation_register as _deploy_accumulation_register,
    deploy_information_register as _deploy_information_register,
    deploy_subsystem as _deploy_subsystem,
    deploy_chart_of_accounts as _deploy_chart_of_accounts,
    deploy_accounting_register as _deploy_accounting_register,
    deploy_report as _deploy_report,
    deploy_form as _deploy_form,
    sync_main_config_files as _sync_main_config_files,
)


@mcp.tool()
def dump_main_config(ib_connection: str) -> dict:
    """Чтение, синхронно. Свежий DumpConfigToFiles основной конфигурации → локальный путь (runtime/main_src/<db>) для Read/Grep."""
    return _dump_main_config(CFG, ib_connection)

@mcp.tool()
def deploy_catalog(ib_connection: str, name: str, synonym: str = "", attributes: list = None,
                    kill_sessions: bool = True) -> dict:
    """Async. Создать/обновить Справочник основной конфигурации. attributes — реквизиты ; None — только Код/Наименование.
    Спек реквизита: {"name", "type": "string"|"decimal"|"boolean"|"date"|"ref"|"enum_ref", ...}; string: {"length": 100}; decimal: {"digits": 15, "frac": 2}; date: {"fractions": "Date"|"Time"|"DateTime"} (не подтверждено); ref: {"catalog": "ИмяСправочника"}; enum_ref: {"enum": "ИмяПеречисления"}."""
    jid = _spawn(_deploy_catalog, CFG, ib_connection, name, synonym=synonym,
                 attributes=attributes, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_document(ib_connection: str, name: str, synonym: str = "", header_attrs: list = None,
                     tabular_sections: list = None, posting_registers: list = None,
                     object_module_bsl: str = None, kill_sessions: bool = True) -> dict:
    """Async. Создать/обновить Документ. header_attrs — реквизиты шапки; tabular_sections — [{name, columns:[спек]}]; posting_registers — ['AccumulationRegister.Имя', ...] (регистры должны уже существовать; регистр без регистратора не загрузится — вместе через sync_main_config_files); object_module_bsl — Ext/ObjectModule.bsl. Вычисляемые поля ТЧ — в ПередЗаписью, не в ОбработкаПроведения (иначе не сохранятся). Спек реквизита — как в deploy_catalog."""
    jid = _spawn(_deploy_document, CFG, ib_connection, name, synonym=synonym,
                 header_attrs=header_attrs, tabular_sections=tabular_sections,
                 posting_registers=posting_registers, object_module_bsl=object_module_bsl,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_accumulation_register(ib_connection: str, name: str, synonym: str = "",
                                  dimensions: list = None, resources: list = None,
                                  register_type: str = "Balance", kill_sessions: bool = True) -> dict:
    """Async. Регистр накопления. dimensions/resources — спек реквизитов; register_type 'Balance'|'Turnovers'. Без документа-регистратора не загрузится — документ первым или вместе через sync_main_config_files. Спек реквизита — как в deploy_catalog."""
    jid = _spawn(_deploy_accumulation_register, CFG, ib_connection, name, synonym=synonym,
                 dimensions=dimensions, resources=resources, register_type=register_type,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_information_register(ib_connection: str, name: str, synonym: str = "",
                                 dimensions: list = None, resources: list = None,
                                 attributes: list = None, periodicity: str = "Nonperiodical",
                                 kill_sessions: bool = True) -> dict:
    """Async. Регистр сведений. dimensions/resources/attributes — спек; periodicity подтверждён только 'Nonperiodical'. Спек реквизита — как в deploy_catalog."""
    jid = _spawn(_deploy_information_register, CFG, ib_connection, name, synonym=synonym,
                 dimensions=dimensions, resources=resources, attributes=attributes,
                 periodicity=periodicity, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_subsystem(ib_connection: str, name: str, synonym: str = "", content: list = None,
                      include_in_command_interface: bool = True, kill_sessions: bool = True) -> dict:
    """Async. Подсистема (без неё объекты не видны в интерфейсе). content — ['Catalog.X','Document.Y','Report.Z'] — уже существующие объекты."""
    jid = _spawn(_deploy_subsystem, CFG, ib_connection, name, synonym=synonym,
                 content=content, include_in_command_interface=include_in_command_interface,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_chart_of_accounts(ib_connection: str, name: str, synonym: str = "",
                              code_length: int = 9, description_length: int = 25,
                              attributes: list = None, predefined_accounts: list = None,
                              kill_sessions: bool = True) -> dict:
    """Async. План счетов. attributes — спек; predefined_accounts — [{name, code, description, account_type:'Active'|'Passive'|'ActivePassive', off_balance, children:[...]}]. Спек реквизита — как в deploy_catalog."""
    jid = _spawn(_deploy_chart_of_accounts, CFG, ib_connection, name, synonym=synonym,
                 code_length=code_length, description_length=description_length,
                 attributes=attributes, predefined_accounts=predefined_accounts,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_accounting_register(ib_connection: str, name: str, chart_of_accounts: str,
                                synonym: str = "", resources: list = None,
                                correspondence: bool = True, kill_sessions: bool = True) -> dict:
    """Async. Регистр бухгалтерии. chart_of_accounts — имя СУЩЕСТВУЮЩЕГО плана счетов; resources — список имён (decimal(10,0), Balance); correspondence=False → одиночный Счет+ВидДвижения вместо СчетДт/СчетКт."""
    jid = _spawn(_deploy_accounting_register, CFG, ib_connection, name, chart_of_accounts,
                 synonym=synonym, resources=resources, correspondence=correspondence,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_report(ib_connection: str, name: str, query_text: str, query_fields: list,
                   synonym: str = "", display_fields: list = None, groupings: list = None,
                   order_fields: list = None, period_parameter: bool = False,
                   date_expr_parameters: list = None, kill_sessions: bool = True) -> dict:
    """Async. Отчёт с СКД (1 dataSet, группировки + детальные строки, период); сложнее — руками, get_guide('main_config_report_dcs').
    query_text — текст запроса как есть ('&' экранируется само); query_fields — поля SELECT; display_fields (=query_fields); groupings — [поле,...] уровни, последний — детали; order_fields (=groupings); period_parameter — параметр Период; date_expr_parameters — [{name,title,expression}] напр. '&Период.ДатаНачала' (перепутать начало/конец = молча 0 строк)."""
    jid = _spawn(_deploy_report, CFG, ib_connection, name, query_text, query_fields,
                 synonym=synonym, display_fields=display_fields, groupings=groupings,
                 order_fields=order_fields, period_parameter=period_parameter,
                 date_expr_parameters=date_expr_parameters, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_form(ib_connection: str, doc_name: str, header_fields: list = None, tables: list = None,
                 commands: list = None, module_bsl: str = None, form_name: str = "ФормаДокумента",
                 set_as_default: bool = True, kill_sessions: bool = True) -> dict:
    """Async. Форма документа (документ должен существовать). header_fields — [{name, data_path:'Объект.Поле', on_change?, read_only?}], вложенный список = горизонтальная группа; tables — [{name, data_path, columns:[...]}]; commands — [{name, title?, action?}]; module_bsl — Ext/Form/Module.bsl (проводку событий в XML тул делает сам); form_name ('ФормаДокумента'); set_as_default."""
    jid = _spawn(_deploy_form, CFG, ib_connection, doc_name, header_fields=header_fields,
                 tables=tables, commands=commands, module_bsl=module_bsl, form_name=form_name,
                 set_as_default=set_as_default, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def sync_main_config_files(ib_connection: str, writes: dict = None, deletes: list = None,
                            ensure_registered: list = None, kill_sessions: bool = True) -> dict:
    """Async. Точечная синка файлов ОСНОВНОЙ конфигурации одним dump→load→update (как sync_extension_files, без -Extension). Единственный способ создать регистр и документ-регистратор вместе.
    writes — {путь: содержимое} (XML — полная замена файла; за основу брать существующий/reference); deletes — [путь]; ensure_registered — [{kind, name}] → <Kind>Имя</Kind> в ChildObjects Configuration.xml."""
    jid = _spawn(_sync_main_config_files, CFG, ib_connection, writes=writes, deletes=deletes,
                 ensure_registered=ensure_registered, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}
