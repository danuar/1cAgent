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
    """
    ТОЛЬКО ЧТЕНИЕ, синхронно (Dump не эксклюзивен — секунды-минуты, раннер не
    трогает). Свежий DumpConfigToFiles ОСНОВНОЙ конфигурации (не расширения,
    БЕЗ -Extension) -> возвращает локальный путь (runtime/main_src/<db_key>).

    Нужен, когда нужно просто ПОСМОТРЕТЬ текущее состояние основной
    конфигурации (Read/Grep по файлам), не дожидаясь, что пользователь уже
    держит дамп на диске. Тот же managed-каталог, что используют
    deploy_catalog/deploy_document/deploy_accumulation_register/
    deploy_information_register/deploy_subsystem — можно сразу продолжить
    туда же без повторного дампа.
    """
    return _dump_main_config(CFG, ib_connection)

_ATTR_SPEC_DOC = (
    'Реквизит — {"name": "Имя", "type": "string"|"decimal"|"boolean"|"date"|"ref"|"enum_ref", ...}: '
    'string: {"length": 100}; decimal: {"digits": 15, "frac": 2}; boolean: {}; '
    'date: {"fractions": "Date"|"Time"|"DateTime"} (НЕ подтверждено вживую); '
    'ref: {"catalog": "ИмяСправочника"}; enum_ref: {"enum": "ИмяПеречисления"}.'
)


@mcp.tool()
def deploy_catalog(ib_connection: str, name: str, synonym: str = "", attributes: list = None,
                    kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, как deploy_module). РЕЖИМ B: создаёт/обновляет
    Справочник ОСНОВНОЙ конфигурации (не расширения). attributes — список
    реквизитов, см. _ATTR_SPEC_DOC ниже; None/[] — справочник только со
    стандартными Код/Наименование. После завершения форма-раннер на этой базе
    закрыта (kill_sessions) — для run_module/warmup поднимите заново start_runner.

    """ + _ATTR_SPEC_DOC
    jid = _spawn(_deploy_catalog, CFG, ib_connection, name, synonym=synonym,
                 attributes=attributes, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_document(ib_connection: str, name: str, synonym: str = "", header_attrs: list = None,
                     tabular_sections: list = None, posting_registers: list = None,
                     object_module_bsl: str = None, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status). РЕЖИМ B: создаёт/обновляет Документ основной
    конфигурации. header_attrs — реквизиты шапки (см. _ATTR_SPEC_DOC).
    tabular_sections — [{"name": "Строки", "columns": [<спек реквизита>, ...]}, ...].
    posting_registers — None (без проведения) или
    ["AccumulationRegister.Имя", "AccountingRegister.Имя", ...] — РЕГИСТРЫ ДОЛЖНЫ
    УЖЕ СУЩЕСТВОВАТЬ в конфигурации на момент вызова (иначе "Ни один из
    документов не является регистратором для регистра" — проверено вживую).
    object_module_bsl — код Ext/ObjectModule.bsl (ОбработкаПроведения и т.п.).
    ГРАБЛЯ (см. get_guide("main_config_document")): вычисляемые поля ТЧ пишите в
    ПередЗаписью(Отказ), НЕ в ОбработкаПроведения — иначе значение корректно
    используется для движений В ЭТОМ ЖЕ прогоне, но НЕ сохраняется в саму
    запись документа (проверено вживую, платформа физически пишет
    шапку+ТЧ ДО вызова ОбработкаПроведения).

    """ + _ATTR_SPEC_DOC
    jid = _spawn(_deploy_document, CFG, ib_connection, name, synonym=synonym,
                 header_attrs=header_attrs, tabular_sections=tabular_sections,
                 posting_registers=posting_registers, object_module_bsl=object_module_bsl,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_accumulation_register(ib_connection: str, name: str, synonym: str = "",
                                  dimensions: list = None, resources: list = None,
                                  register_type: str = "Balance", kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status). РЕЖИМ B: создаёт/обновляет Регистр накопления
    основной конфигурации. dimensions/resources — списки реквизитов (см.
    _ATTR_SPEC_DOC). register_type: "Balance" (остатки) | "Turnovers" (обороты).
    ВАЖНО: регистр без хотя бы одного документа-регистратора (см.
    deploy_document.posting_registers) НЕ загрузится — "Ни один из документов не
    является регистратором для регистра" (проверено вживую) — создавайте регистр
    и ссылающийся на него документ ОДНИМ пакетом правок либо документ первым.

    """ + _ATTR_SPEC_DOC
    jid = _spawn(_deploy_accumulation_register, CFG, ib_connection, name, synonym=synonym,
                 dimensions=dimensions, resources=resources, register_type=register_type,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_information_register(ib_connection: str, name: str, synonym: str = "",
                                 dimensions: list = None, resources: list = None,
                                 attributes: list = None, periodicity: str = "Nonperiodical",
                                 kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status). РЕЖИМ B: создаёт/обновляет Регистр сведений
    основной конфигурации. dimensions/resources/attributes — списки реквизитов
    (см. _ATTR_SPEC_DOC). periodicity: подтверждено вживую только "Nonperiodical"
    (непериодический) — для периодических вариантов точное написание enum-
    значения НЕ проверено, при ошибке XDTO сверьтесь через свежий
    DumpConfigToFiles реального периодического регистра.

    """ + _ATTR_SPEC_DOC
    jid = _spawn(_deploy_information_register, CFG, ib_connection, name, synonym=synonym,
                 dimensions=dimensions, resources=resources, attributes=attributes,
                 periodicity=periodicity, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_subsystem(ib_connection: str, name: str, synonym: str = "", content: list = None,
                      include_in_command_interface: bool = True, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status). РЕЖИМ B: создаёт/обновляет Подсистему основной
    конфигурации — БЕЗ неё объекты существуют в метаданных, но НЕ появляются в
    интерфейсе клиента 1С (единственный способ сделать их видимыми пользователю).
    content — список полных имён УЖЕ существующих объектов, например
    ["Catalog.Склады", "Document.ПриходнаяНакладная", "Report.ВедомостьПродаж"].
    ГРАБЛЯ (см. get_guide("main_config_subsystem")): порядок элементов внутри
    файла подсистемы строгий (Content — последний элемент ВНУТРИ Properties) —
    неверный порядок даёт ошибку формата документа, которая уходит ТОЛЬКО во
    всплывающий диалог Конфигуратора, НЕ в лог — этот тул уже собирает верный
    порядок, руками собирать XML для Subsystem не нужно.
    """
    jid = _spawn(_deploy_subsystem, CFG, ib_connection, name, synonym=synonym,
                 content=content, include_in_command_interface=include_in_command_interface,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_chart_of_accounts(ib_connection: str, name: str, synonym: str = "",
                              code_length: int = 9, description_length: int = 25,
                              attributes: list = None, predefined_accounts: list = None,
                              kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, #38). РЕЖИМ B: создаёт/обновляет План счетов
    основной конфигурации. Формат ПОДТВЕРЖДЁН реальным дампом (не угадан) —
    см. докстринг metadata_deploy.build_chart_of_accounts_xml. attributes —
    доп. реквизиты (см. _ATTR_SPEC_DOC). predefined_accounts — предопределённые
    счета, [{"name","code","description","account_type":"Active"|"Passive"|
    "ActivePassive","off_balance":bool,"children":[...]}] -> отдельный файл
    Ext/Predefined.xml, children — та же структура рекурсивно.

    """ + _ATTR_SPEC_DOC
    jid = _spawn(_deploy_chart_of_accounts, CFG, ib_connection, name, synonym=synonym,
                 code_length=code_length, description_length=description_length,
                 attributes=attributes, predefined_accounts=predefined_accounts,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_accounting_register(ib_connection: str, name: str, chart_of_accounts: str,
                                synonym: str = "", resources: list = None,
                                correspondence: bool = True, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, #38). РЕЖИМ B: создаёт/обновляет Регистр
    бухгалтерии основной конфигурации. Формат ПОДТВЕРЖДЁН реальным дампом.
    chart_of_accounts — имя УЖЕ существующего Плана счетов (создайте его
    ПЕРВЫМ через deploy_chart_of_accounts, ДОЛЖЕН существовать в конфигурации
    на момент вызова). resources — список ИМЁН ресурсов (каждый decimal(10,0)+
    Balance=true — единственный подтверждённый вариант). correspondence=True
    (по умолчанию) — БЕЗ корреспонденции (false) движения используют одиночный
    Счет+ВидДвижения вместо пары СчетДт/СчетКт (см.
    get_guide("main_config_accounting"), грабля "Поле объекта не обнаружено (СчетДт)").
    """
    jid = _spawn(_deploy_accounting_register, CFG, ib_connection, name, chart_of_accounts,
                 synonym=synonym, resources=resources, correspondence=correspondence,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_report(ib_connection: str, name: str, query_text: str, query_fields: list,
                   synonym: str = "", display_fields: list = None, groupings: list = None,
                   order_fields: list = None, period_parameter: bool = False,
                   date_expr_parameters: list = None, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, #38). РЕЖИМ B: создаёт/обновляет Отчёт с СКД
    основной конфигурации. Формат ПОДТВЕРЖДЁН реальным дампом — но ТОЛЬКО для
    описанного здесь случая (1 dataSet-запрос, группировка по цепочке полей +
    детальные строки в самом низу, период+производные параметры). Более
    сложные схемы СКД (несколько dataSet, вычисляемые поля, ресурсы-итоги,
    условное оформление, "быстрые параметры") НЕ подтверждены — собирайте
    руками, см. get_guide("main_config_report_dcs").

    query_text — ТЕКСТ ЗАПРОСА КАК ЕСТЬ (с &Параметр), "&" экранируется
    АВТОМАТИЧЕСКИ — НЕ экранируйте вручную (см. HANDOFF_ARCHIVE.md #31 п.7 про
    10-минутное зависание DESIGNER на неэкранированном "&").
    query_fields — SELECT-список запроса (для декларации dataSet).
    display_fields — что показывать в таблице отчёта (по умолчанию = query_fields).
    groupings — [ПолеГруппировки, ...], каждый элемент — уровень вложенности,
    ПОСЛЕДНИЙ уровень всегда детальные строки.
    order_fields — сортировка (по умолчанию = groupings).
    period_parameter — добавить параметр "Период" (v8:StandardPeriod, пикер периода).
    date_expr_parameters — [{"name","title","expression"}, ...] — производные
    параметры (например NachaloPerioda из "&Период.ДатаНачала") — ГРАБЛЯ (см.
    #33): не перепутайте местами начало/конец — молча даёт 0 строк без ошибки.
    """
    jid = _spawn(_deploy_report, CFG, ib_connection, name, query_text, query_fields,
                 synonym=synonym, display_fields=display_fields, groupings=groupings,
                 order_fields=order_fields, period_parameter=period_parameter,
                 date_expr_parameters=date_expr_parameters, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def deploy_form(ib_connection: str, doc_name: str, header_fields: list = None, tables: list = None,
                 commands: list = None, module_bsl: str = None, form_name: str = "ФормаДокумента",
                 set_as_default: bool = True, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, #38/#40). РЕЖИМ B: создаёт/обновляет форму
    документа. ДОКУМЕНТ ДОЛЖЕН УЖЕ СУЩЕСТВОВАТЬ (deploy_document сначала).
    Формат ПОДТВЕРЖДЁН реальным дампом ПОСЛЕ фикса #34 (не угадан).

    header_fields — список элементов шапки; каждый элемент ЛИБО одиночное
    поле {"name","data_path","on_change"?,"read_only"?}, ЛИБО СПИСОК из
    нескольких таких словарей — тогда они кладутся в ОДНУ ГОРИЗОНТАЛЬНУЮ
    группу (как Номер+Дата рядом). data_path — путь вида "Объект.Склад" (шапка)
    или "Объект.Товары.Количество" (колонка ТЧ).
    tables — [{"name","data_path","columns":[<спек поля выше>, ...]}, ...] —
    0 или больше табличных частей.
    commands — [{"name","title"?,"action"?}] — action по умолчанию = name.
    module_bsl — код Ext/Form/Module.bsl. БИЗНЕС-ЛОГИКУ обработчиков (что
    именно считает процедура при OnChange) пишете сами в module_bsl — тул
    отвечает только за правильную XML-проводку "поле -> событие -> имя
    процедуры" (см. ГРАБЛЯ #34: событие всегда "OnChange", НЕ "ПриИзменении",
    несмотря на то, что второй вариант чисто загружается).
    set_as_default=True — если у документа ещё НЕТ формы по умолчанию,
    проставляет её на новую (не трогает, если уже что-то стоит).
    form_name — по умолчанию "ФормаДокумента" (как в обоих подтверждённых примерах).
    """
    jid = _spawn(_deploy_form, CFG, ib_connection, doc_name, header_fields=header_fields,
                 tables=tables, commands=commands, module_bsl=module_bsl, form_name=form_name,
                 set_as_default=set_as_default, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}


@mcp.tool()
def sync_main_config_files(ib_connection: str, writes: dict = None, deletes: list = None,
                            ensure_registered: list = None, kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, #45/#46). РЕЖИМ B: точечная синхронизация
    ПРОИЗВОЛЬНЫХ файлов ОСНОВНОЙ конфигурации (аналог sync_extension_files,
    но без -Extension) — патчит МНОЖЕСТВО существующих файлов ОДНИМ
    dump→load→update циклом, вместо N независимых deploy_*-вызовов.

    Появился из-за живой находки (#44): регистр и документ-регистратор
    нельзя создать/починить РАЗДЕЛЬНЫМИ вызовами deploy_accounting_register/
    deploy_document — платформа отказывает ("Ни один из документов не
    является регистратором для регистра"), если на момент ЗАГРУЗКИ нет ХОТЯ
    БЫ ОДНОГО документа с этим регистром в RegisterRecords. Патчите ОБА
    документа И регистр И его регистрацию ОДНИМ вызовом здесь.

    writes — {относительный_путь_в_дампе: содержимое}, например:
        {"Documents/ПриходнаяНакладная.xml": "<полный XML документа>",
         "AccountingRegisters/Проводки.xml": "<XML нового регистра>"}
    ВНИМАНИЕ: для XML-объектов это ПОЛНАЯ замена файла целиком — соберите
    корректный XML через build_*_xml-функции/скопируйте+поправьте существующий
    (через dump_main_config/read_reference_snippet), не пишите с нуля руками.
    deletes — [относительный_путь, ...] — файл или папка удаляются.
    ensure_registered — [{"kind": "AccountingRegister", "name": "Проводки"}, ...] —
    добавляет `<Kind>Имя</Kind>` в ChildObjects корневого Configuration.xml,
    ЕСЛИ там ещё нет (идемпотентно). kind — любой известный тег метаданных
    (Document/Catalog/AccountingRegister/CommonModule/...).
    """
    jid = _spawn(_sync_main_config_files, CFG, ib_connection, writes=writes, deletes=deletes,
                 ensure_registered=ensure_registered, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-60с"}
