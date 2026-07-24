#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#билет15: развёртывание объектов ОСНОВНОЙ конфигурации (Справочники/Документы/
Регистры накопления/Регистры сведений) через файлы — по аналогии с
module_deploy.py (тот покрывает только общие модули внутри РАСШИРЕНИЯ). Формат
основной конфигурации сложнее: объекты, порождающие ссылочные/наборные типы,
требуют блок <InternalInfo> со СЛУЧАЙНЫМИ (не платформенными) TypeId/ValueId —
см. get_guide("main_config_overview") для индекса узких тем (InternalInfo по
видам, форматы <Type>, грабли с QuickChoice, ПередЗаписью vs ОбработкаПроведения,
экранирование "&" в DCS-запросах) — берите ТОЛЬКО нужную под-тему, не всё разом.

ГРАНИЦА ОХВАТА (сознательно, как и module_deploy.py начинал только с НОВЫХ
общих модулей): этот инструмент закрывает Справочники/Документы/Регистры
накопления/Регистры сведений — самые частые объекты для задач вида "добавить
документы/справочники/регистры под отчёт". НЕ закрывает: Планы счетов,
Регистры бухгалтерии, Отчёты+СКД, Формы, Перечисления, Обработки, Регламентные
задания — для них формат тоже разобран и задокументирован в guide, но
руками собирать XML пока быстрее, чем обобщать в тул (риск не окупается
частотой use-case). Если такой объект понадобится ещё раз — тогда обобщать.

ДОПОЛНИТЕЛЬНО НЕ ЗАКРЫТО (найдено при разборе транскрипта отдельной сессии
тестирования vkr_, где это оказалось ЦЕНТРАЛЬНЫМ, а не периферийным):
    - HTTPServices — вообще нигде не обобщено (ни здесь, ни в module_deploy.py).
    - Общий модуль ПРЯМО в ОСНОВНОЙ конфигурации (не внутри расширения) — НЕ то
      же самое, что deploy_module/module_deploy.py: тот всегда требует ext_name
      и работает ТОЛЬКО внутри расширения (-Extension в LoadConfigFromFiles).
      Создать/поправить общий модуль основной конфигурации сейчас нечем ни в
      этом файле, ни в module_deploy.py — реальный пробел, не устаревшая заметка.

Пайплайн (как у module_deploy.py, ВСЕ шаги ПОСЛЕДОВАТЕЛЬНЫМИ subprocess.run,
НЕ чейнить через ";"):
    1. DumpConfigToFiles БЕЗ -Extension — свежий снимок ВСЕЙ основной конфигурации.
    2. Написать XML нового объекта (+ подпапки табличных частей для документов).
    3. Дописать тег регистрации в <ChildObjects> корневого Configuration.xml.
    4. XML-ВАЛИДАЦИЯ каждого созданного/изменённого .xml через
       xml.etree.ElementTree.parse() — ловит невалидный XML (например
       неэкранированный "&" в текстах DCS-запросов) МГНОВЕННО, а не через
       10-минутный зависший DESIGNER-процесс с пустым логом (найдено вживую,
       #билет15 — узкое место, которое стоило реальных 10+ минут).
    5. kill_sessions (монопольный доступ для файловой базы).
    6. LoadConfigFromFiles БЕЗ -Extension.
    7. UpdateDBCfg БЕЗ -Extension.
"""
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from src.core.ib_connection import cli_connection_str
from src.onec.sessions import kill_matching_processes
from src.core.dump_lock import dump_lock
from src.core.xml_validate import validate_xml_files
from src.core.designer_log import read_designer_log
from src.onec.designer_run import run_watched, watched_error

_NS = (
    'xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" '
    'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" '
    'xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" '
    'xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" '
    'xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" '
    'xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" '
    'xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" '
    'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.19"'
)

# Namespace-блок ФАЙЛА ФОРМЫ (Ext/Form.xml) — ДРУГОЙ набор, чем _NS (MetaDataObject):
# добавляет dcscor/dcssch/dcsset (СКД в форме), убирает xen/xpr (перечисления/
# предопределённые — не нужны внутри самой формы). Раньше был захардкожен только
# внутри build_document_form_xml — вынесен в константу, т.к. понадобился ВТОРОЙ
# раз для заимствованной формы (extension_deploy.build_borrowed_form_xml, #52).
_FORM_NS = (
    'xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" '
    'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" '
    'xmlns:dcssch="http://v8.1c.ru/8.1/data-composition-system/schema" xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings" '
    'xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" '
    'xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" '
    'xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" '
    'xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" '
    'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.19"'
)

# Категории <xr:GeneratedType> по видам метаданных — подтверждено вживую
# (см. get_guide("main_config_internal_info") для полного списка всех видов,
# включая те, что этот тул не обобщает).
# #38: ChartOfAccounts/AccountingRegister/Report — категории НЕ угаданы, взяты из
# реальных подтверждённых дампов на диске (не строились по памяти/аналогии,
# следуя правилу эскалации из get_guide("main_config_overview")):
#   runtime/config_src/MetaTemplates/ChartsOfAccounts/Тест_ПланСчетов.xml
#   runtime/config_src/MetaTemplates/AccountingRegisters/Тест_РегистрБухгалтерии.xml
#   runtime/config_src/TestDB15/Reports/ВедомостьПродаж.xml
CATEGORIES = {
    "Catalog": [("Object", "CatalogObject"), ("Ref", "CatalogRef"), ("Selection", "CatalogSelection"),
                ("List", "CatalogList"), ("Manager", "CatalogManager")],
    "Document": [("Object", "DocumentObject"), ("Ref", "DocumentRef"), ("Selection", "DocumentSelection"),
                 ("List", "DocumentList"), ("Manager", "DocumentManager")],
    "AccumulationRegister": [("Record", "AccumulationRegisterRecord"), ("Manager", "AccumulationRegisterManager"),
                              ("Selection", "AccumulationRegisterSelection"), ("List", "AccumulationRegisterList"),
                              ("RecordSet", "AccumulationRegisterRecordSet"), ("RecordKey", "AccumulationRegisterRecordKey")],
    "InformationRegister": [("Record", "InformationRegisterRecord"), ("Manager", "InformationRegisterManager"),
                             ("Selection", "InformationRegisterSelection"), ("List", "InformationRegisterList"),
                             ("RecordSet", "InformationRegisterRecordSet"), ("RecordKey", "InformationRegisterRecordKey"),
                             ("RecordManager", "InformationRegisterRecordManager")],
    "ChartOfAccounts": [("Object", "ChartOfAccountsObject"), ("Ref", "ChartOfAccountsRef"),
                         ("Selection", "ChartOfAccountsSelection"), ("List", "ChartOfAccountsList"),
                         ("Manager", "ChartOfAccountsManager"),
                         ("ExtDimensionTypes", "ChartOfAccountsExtDimensionTypes"),
                         ("ExtDimensionTypesRow", "ChartOfAccountsExtDimensionTypesRow")],
    "AccountingRegister": [("Record", "AccountingRegisterRecord"), ("ExtDimensions", "AccountingRegisterExtDimensions"),
                            ("RecordSet", "AccountingRegisterRecordSet"), ("RecordKey", "AccountingRegisterRecordKey"),
                            ("Selection", "AccountingRegisterSelection"), ("List", "AccountingRegisterList"),
                            ("Manager", "AccountingRegisterManager")],
    "Report": [("Object", "ReportObject"), ("Manager", "ReportManager")],
}

_TAG_BY_KIND = {
    "Catalog": "Catalog", "Document": "Document",
    "AccumulationRegister": "AccumulationRegister", "InformationRegister": "InformationRegister",
    "Subsystem": "Subsystem",
    "ChartOfAccounts": "ChartOfAccounts", "AccountingRegister": "AccountingRegister", "Report": "Report",
}
_FOLDER_BY_KIND = {
    "Catalog": "Catalogs", "Document": "Documents",
    "AccumulationRegister": "AccumulationRegisters", "InformationRegister": "InformationRegisters",
    "Subsystem": "Subsystems",
    # ВНИМАНИЕ: папка "ChartsOfAccounts" (plural "Charts"), НЕ "ChartOfAccounts" —
    # подтверждено реальным путём дампа, не соответствует наивному ожиданию по
    # аналогии с именем тега/класса.
    "ChartOfAccounts": "ChartsOfAccounts", "AccountingRegister": "AccountingRegisters", "Report": "Reports",
}
# Subsystem (как Role/CommonModule/ScheduledJob) — InternalInfo НЕ нужен, единственный
# файл без Ext-подпапки. См. get_guide("main_config_subsystem").
_NO_INTERNAL_INFO_KINDS = {"Subsystem"}


def _run(cmd: str, timeout: int, cfg: dict, ib_connection: str, step: str) -> tuple:
    """
    #45: обёртка над designer_run.run_watched — сохраняет привычную сигнатуру
    места вызова (rc, watch_err), где watch_err — готовый error-dict для
    возврата НАРУЖУ, если процесс убит из-за диалога/таймаута (см.
    designer_run.py про то, зачем это нужно), иначе None (обычный путь
    проверки rc != 0 не меняется).
    """
    watched = run_watched(cmd, timeout, cfg, ib_connection)
    return watched["returncode"], watched_error(step, watched, timeout)


def _safe_db_key(ib_connection: str) -> str:
    """Строка подключения -> безопасное имя папки под runtime/main_src/."""
    import re
    from src.core.ib_connection import parse_connection_string
    p = parse_connection_string(ib_connection)
    raw = p.get("File") or f"{p.get('Srvr', '')}_{p.get('Ref', '')}"
    name = Path(raw).name if p.get("File") else raw
    return re.sub(r"[^\w\-]", "_", name) or "db"


def gen_internal_info(kind: str, name: str, indent: str = "\t\t") -> str:
    cats = CATEGORIES[kind]
    parts = [f"{indent}<InternalInfo>"]
    for cat, prefix in cats:
        parts.append(f'{indent}\t<xr:GeneratedType name="{prefix}.{name}" category="{cat}">')
        parts.append(f'{indent}\t\t<xr:TypeId>{uuid.uuid4()}</xr:TypeId>')
        parts.append(f'{indent}\t\t<xr:ValueId>{uuid.uuid4()}</xr:ValueId>')
        parts.append(f'{indent}\t</xr:GeneratedType>')
    parts.append(f"{indent}</InternalInfo>")
    return "\n".join(parts)


# ---------- Type builders: (kind, params) -> <Type>...</Type> ----------

def type_string(length: int = 100) -> str:
    return (f'<Type><v8:Type>xs:string</v8:Type>'
            f'<v8:StringQualifiers><v8:Length>{length}</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength>'
            f'</v8:StringQualifiers></Type>')


def type_decimal(digits: int = 15, frac: int = 2) -> str:
    return (f'<Type><v8:Type>xs:decimal</v8:Type>'
            f'<v8:NumberQualifiers><v8:Digits>{digits}</v8:Digits><v8:FractionDigits>{frac}</v8:FractionDigits>'
            f'<v8:AllowedSign>Any</v8:AllowedSign></v8:NumberQualifiers></Type>')


def type_boolean() -> str:
    return '<Type><v8:Type>xs:boolean</v8:Type></Type>'


def type_date(fractions: str = "DateTime") -> str:
    """fractions: Date | Time | DateTime. НЕ подтверждено вживую (см. guide) — при
    ошибке XDTO сверьтесь с реальным примером через describe_metadata/DumpConfigToFiles."""
    return f'<Type><v8:Type>xs:dateTime</v8:Type><v8:DateQualifiers><v8:DateFractions>{fractions}</v8:DateFractions></v8:DateQualifiers></Type>'


def type_ref(catalog: str) -> str:
    return f'<Type><v8:Type>cfg:CatalogRef.{catalog}</v8:Type></Type>'


def type_enum_ref(enum: str) -> str:
    return f'<Type><v8:Type>cfg:EnumRef.{enum}</v8:Type></Type>'


def _attribute_xml(tag: str, name: str, type_block: str, indent: str = "\t\t\t", extra: str = "") -> str:
    """tag: Attribute | Dimension | Resource. Минимальный рабочий набор свойств,
    подтверждено вживую (см. guide) — extra добавляет специфичные для tag поля
    (например <Balance>true</Balance> для Resource регистра бухгалтерии — но
    ChartOfAccounts/AccountingRegister этот тул не создаёт, оставлено для ручной
    правки сгенерированного XML при необходимости)."""
    return (
        f'{indent}<{tag} uuid="{uuid.uuid4()}">\n'
        f'{indent}\t<Properties>\n'
        f'{indent}\t\t<Name>{name}</Name>\n'
        f'{indent}\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{name}</v8:content></v8:item></Synonym>\n'
        f'{indent}\t\t<Comment/>\n'
        f'{indent}\t\t{type_block}\n'
        f'{indent}\t\t<PasswordMode>false</PasswordMode><Format/><EditFormat/><ToolTip/>\n'
        f'{indent}\t\t<MarkNegatives>false</MarkNegatives><Mask/><MultiLine>false</MultiLine>\n'
        f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>\n'
        f'{indent}\t\t<MinValue xsi:nil="true"/><MaxValue xsi:nil="true"/>\n'
        f'{indent}\t\t<FillChecking>DontCheck</FillChecking>\n'
        f'{indent}\t\t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>\n'
        f'{indent}\t\t<ChoiceParameterLinks/><ChoiceParameters/>\n'
        f'{indent}\t\t<QuickChoice>Auto</QuickChoice><CreateOnInput>Auto</CreateOnInput>\n'
        f'{indent}\t\t<ChoiceForm/><LinkByType/><ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>\n'
        f'{extra}'
        f'{indent}\t\t<Indexing>DontIndex</Indexing><FullTextSearch>Use</FullTextSearch>\n'
        f'{indent}\t</Properties>\n'
        f'{indent}</{tag}>'
    )


def _attr_list(attrs, tag="Attribute", indent="\t\t\t"):
    """attrs: list[(name, type_block)] -> склеенный XML."""
    return "\n".join(_attribute_xml(tag, n, t, indent=indent) for n, t in attrs)


def _type_block_from_spec(spec: dict) -> str:
    """
    JSON-дружелюбный спек типа (для MCP-инструментов, которые не могут принять
    сырой Python-вызов) -> XML <Type>. spec["type"] один из:
      string  {"length": 100}
      decimal {"digits": 15, "frac": 2}
      boolean {}
      date    {"fractions": "Date"|"Time"|"DateTime"}
      ref     {"catalog": "ИмяСправочника"}
      enum_ref {"enum": "ИмяПеречисления"}
    """
    t = spec.get("type")
    if t == "string":
        return type_string(spec.get("length", 100))
    if t == "decimal":
        return type_decimal(spec.get("digits", 15), spec.get("frac", 2))
    if t == "boolean":
        return type_boolean()
    if t == "date":
        return type_date(spec.get("fractions", "DateTime"))
    if t == "ref":
        return type_ref(spec["catalog"])
    if t == "enum_ref":
        return type_enum_ref(spec["enum"])
    raise ValueError(f"неизвестный type в спеке реквизита: {spec!r}")


def attrs_from_specs(specs) -> list:
    """[{"name": "Имя", "type": "string", "length": 100}, ...] -> [(name, type_block), ...]
    для build_*_xml. specs может быть None/[] -> []."""
    return [(s["name"], _type_block_from_spec(s)) for s in (specs or [])]


# ---------- Object XML builders ----------

def build_catalog_xml(name: str, synonym: str, attributes) -> str:
    internal = gen_internal_info("Catalog", name)
    attrs_xml = _attr_list(attributes or [])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Catalog uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<Hierarchical>false</Hierarchical>\n'
        '\t\t\t<HierarchyType>HierarchyFoldersAndItems</HierarchyType>\n'
        '\t\t\t<LimitLevelCount>false</LimitLevelCount>\n'
        '\t\t\t<LevelCount>2</LevelCount>\n'
        '\t\t\t<FoldersOnTop>true</FoldersOnTop>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<Owners/>\n'
        '\t\t\t<SubordinationUse>ToItems</SubordinationUse>\n'
        '\t\t\t<CodeLength>9</CodeLength>\n'
        '\t\t\t<DescriptionLength>100</DescriptionLength>\n'
        '\t\t\t<CodeType>String</CodeType>\n'
        '\t\t\t<CodeAllowedLength>Variable</CodeAllowedLength>\n'
        '\t\t\t<CodeSeries>WholeCatalog</CodeSeries>\n'
        '\t\t\t<CheckUnique>true</CheckUnique>\n'
        '\t\t\t<Autonumbering>true</Autonumbering>\n'
        '\t\t\t<DefaultPresentation>AsDescription</DefaultPresentation>\n'
        '\t\t\t<Characteristics/>\n'
        '\t\t\t<PredefinedDataUpdate>Auto</PredefinedDataUpdate>\n'
        '\t\t\t<EditType>InDialog</EditType>\n'
        '\t\t\t<QuickChoice>false</QuickChoice>\n'
        '\t\t\t<ChoiceMode>BothWays</ChoiceMode>\n'
        '\t\t\t<InputByString>\n'
        f'\t\t\t\t<xr:Field>Catalog.{name}.StandardAttribute.Description</xr:Field>\n'
        f'\t\t\t\t<xr:Field>Catalog.{name}.StandardAttribute.Code</xr:Field>\n'
        '\t\t\t</InputByString>\n'
        '\t\t\t<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>\n'
        '\t\t\t<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>\n'
        '\t\t\t<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>\n'
        '\t\t\t<DefaultObjectForm/><DefaultFolderForm/><DefaultListForm/><DefaultChoiceForm/><DefaultFolderChoiceForm/>\n'
        '\t\t\t<AuxiliaryObjectForm/><AuxiliaryFolderForm/><AuxiliaryListForm/><AuxiliaryChoiceForm/><AuxiliaryFolderChoiceForm/>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<BasedOn/>\n'
        '\t\t\t<DataLockFields/>\n'
        '\t\t\t<DataLockControlMode>Managed</DataLockControlMode>\n'
        '\t\t\t<FullTextSearch>Use</FullTextSearch>\n'
        '\t\t\t<ObjectPresentation/><ExtendedObjectPresentation/><ListPresentation/><ExtendedListPresentation/><Explanation/>\n'
        '\t\t\t<CreateOnInput>Use</CreateOnInput>\n'
        '\t\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>\n'
        '\t\t\t<DataHistory>DontUse</DataHistory>\n'
        '\t\t\t<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>\n'
        '\t\t\t<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'{attrs_xml}\n'
        '\t\t</ChildObjects>\n'
        '\t</Catalog>\n'
        '</MetaDataObject>\n'
    )


def _tabular_section_xml(doc_name: str, ts_name: str, columns) -> str:
    ts_cats = [("TabularSection", "DocumentTabularSection"), ("TabularSectionRow", "DocumentTabularSectionRow")]
    parts = ["\t\t\t\t<InternalInfo>"]
    for cat, prefix in ts_cats:
        parts.append(f'\t\t\t\t\t<xr:GeneratedType name="{prefix}.{doc_name}.{ts_name}" category="{cat}">')
        parts.append(f'\t\t\t\t\t\t<xr:TypeId>{uuid.uuid4()}</xr:TypeId>')
        parts.append(f'\t\t\t\t\t\t<xr:ValueId>{uuid.uuid4()}</xr:ValueId>')
        parts.append('\t\t\t\t\t</xr:GeneratedType>')
    parts.append("\t\t\t\t</InternalInfo>")
    internal = "\n".join(parts)
    cols_xml = _attr_list(columns, indent="\t\t\t\t\t")
    return (
        f'\t\t\t<TabularSection uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        f'\t\t\t\t<Properties>\n'
        f'\t\t\t\t\t<Name>{ts_name}</Name>\n'
        f'\t\t\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{ts_name}</v8:content></v8:item></Synonym>\n'
        f'\t\t\t\t\t<Comment/>\n'
        f'\t\t\t\t\t<ToolTip/>\n'
        f'\t\t\t\t\t<FillChecking>DontCheck</FillChecking>\n'
        f'\t\t\t\t</Properties>\n'
        f'\t\t\t\t<ChildObjects>\n'
        f'{cols_xml}\n'
        f'\t\t\t\t</ChildObjects>\n'
        f'\t\t\t</TabularSection>'
    )


def build_document_xml(name: str, synonym: str, header_attrs, tabular_sections, posting_registers=None) -> str:
    """
    tabular_sections: list[(ts_name, list[(col_name, type_block)])]
    posting_registers: None -> Posting=Deny (документ без движений).
                        list["AccumulationRegister.Имя", "AccountingRegister.Имя", ...] -> Posting=Allow
                        + RegisterRecords на эти регистры (регистры ДОЛЖНЫ уже существовать
                        в конфигурации на момент LoadConfigFromFiles — иначе
                        "Ни один из документов не является регистратором для регистра").
    """
    internal = gen_internal_info("Document", name)
    header_xml = _attr_list(header_attrs or [])
    ts_xml = "\n".join(_tabular_section_xml(name, tsn, cols) for tsn, cols in (tabular_sections or []))

    if posting_registers:
        items = "\n".join(f'\t\t\t\t<xr:Item xsi:type="xr:MDObjectRef">{r}</xr:Item>' for r in posting_registers)
        posting_block = (
            '\t\t\t<Posting>Allow</Posting>\n'
            '\t\t\t<RealTimePosting>Allow</RealTimePosting>\n'
            '\t\t\t<RegisterRecordsDeletion>AutoDeleteOnUnpost</RegisterRecordsDeletion>\n'
            '\t\t\t<RegisterRecordsWritingOnPost>WriteSelected</RegisterRecordsWritingOnPost>\n'
            '\t\t\t<SequenceFilling>AutoFill</SequenceFilling>\n'
            '\t\t\t<RegisterRecords>\n'
            f'{items}\n'
            '\t\t\t</RegisterRecords>\n'
            '\t\t\t<PostInPrivilegedMode>true</PostInPrivilegedMode>\n'
            '\t\t\t<UnpostInPrivilegedMode>true</UnpostInPrivilegedMode>\n'
        )
    else:
        posting_block = (
            '\t\t\t<Posting>Deny</Posting>\n'
            '\t\t\t<RealTimePosting>Deny</RealTimePosting>\n'
            '\t\t\t<RegisterRecordsDeletion>AutoDeleteOnUnpost</RegisterRecordsDeletion>\n'
            '\t\t\t<RegisterRecordsWritingOnPost>WriteSelected</RegisterRecordsWritingOnPost>\n'
            '\t\t\t<SequenceFilling>AutoFill</SequenceFilling>\n'
            '\t\t\t<PostInPrivilegedMode>false</PostInPrivilegedMode>\n'
            '\t\t\t<UnpostInPrivilegedMode>false</UnpostInPrivilegedMode>\n'
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Document uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<Numerator/>\n'
        '\t\t\t<NumberType>String</NumberType>\n'
        '\t\t\t<NumberLength>9</NumberLength>\n'
        '\t\t\t<NumberAllowedLength>Variable</NumberAllowedLength>\n'
        '\t\t\t<NumberPeriodicity>Nonperiodical</NumberPeriodicity>\n'
        '\t\t\t<CheckUnique>true</CheckUnique>\n'
        '\t\t\t<Autonumbering>true</Autonumbering>\n'
        '\t\t\t<Characteristics/>\n'
        '\t\t\t<BasedOn/>\n'
        '\t\t\t<InputByString>\n'
        f'\t\t\t\t<xr:Field>Document.{name}.StandardAttribute.Number</xr:Field>\n'
        '\t\t\t</InputByString>\n'
        '\t\t\t<CreateOnInput>Use</CreateOnInput>\n'
        '\t\t\t<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>\n'
        '\t\t\t<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>\n'
        '\t\t\t<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>\n'
        '\t\t\t<DefaultObjectForm/><DefaultListForm/><DefaultChoiceForm/>\n'
        '\t\t\t<AuxiliaryObjectForm/><AuxiliaryListForm/><AuxiliaryChoiceForm/>\n'
        f'{posting_block}'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<DataLockFields/>\n'
        '\t\t\t<DataLockControlMode>Managed</DataLockControlMode>\n'
        '\t\t\t<FullTextSearch>Use</FullTextSearch>\n'
        '\t\t\t<ObjectPresentation/><ExtendedObjectPresentation/><ListPresentation/><ExtendedListPresentation/><Explanation/>\n'
        '\t\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>\n'
        '\t\t\t<DataHistory>DontUse</DataHistory>\n'
        '\t\t\t<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>\n'
        '\t\t\t<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'{header_xml}\n'
        f'{ts_xml}\n'
        '\t\t</ChildObjects>\n'
        '\t</Document>\n'
        '</MetaDataObject>\n'
    )


def build_accumulation_register_xml(name: str, synonym: str, dimensions, resources, register_type: str = "Balance") -> str:
    """dimensions/resources: list[(name, type_block)]."""
    internal = gen_internal_info("AccumulationRegister", name)
    res_xml = _attr_list(resources or [], tag="Resource")
    dim_xml = _attr_list(dimensions or [], tag="Dimension")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<AccumulationRegister uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<DefaultListForm/><AuxiliaryListForm/>\n'
        f'\t\t\t<RegisterType>{register_type}</RegisterType>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<DataLockControlMode>Managed</DataLockControlMode>\n'
        '\t\t\t<FullTextSearch>DontUse</FullTextSearch>\n'
        '\t\t\t<EnableTotalsSplitting>true</EnableTotalsSplitting>\n'
        '\t\t\t<ListPresentation/><ExtendedListPresentation/><Explanation/>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'{res_xml}\n'
        f'{dim_xml}\n'
        '\t\t</ChildObjects>\n'
        '\t</AccumulationRegister>\n'
        '</MetaDataObject>\n'
    )


def build_information_register_xml(name: str, synonym: str, dimensions, resources, attributes=None,
                                    periodicity: str = "Nonperiodical") -> str:
    internal = gen_internal_info("InformationRegister", name)
    res_xml = _attr_list(resources or [], tag="Resource")
    dim_xml = _attr_list(dimensions or [], tag="Dimension")
    attr_xml = _attr_list(attributes or [], tag="Attribute")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<InformationRegister uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<EditType>InDialog</EditType>\n'
        '\t\t\t<DefaultRecordForm/><DefaultListForm/><AuxiliaryRecordForm/><AuxiliaryListForm/>\n'
        f'\t\t\t<InformationRegisterPeriodicity>{periodicity}</InformationRegisterPeriodicity>\n'
        '\t\t\t<WriteMode>Independent</WriteMode>\n'
        '\t\t\t<MainFilterOnPeriod>false</MainFilterOnPeriod>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<DataLockControlMode>Managed</DataLockControlMode>\n'
        '\t\t\t<FullTextSearch>DontUse</FullTextSearch>\n'
        '\t\t\t<EnableTotalsSliceFirst>false</EnableTotalsSliceFirst>\n'
        '\t\t\t<EnableTotalsSliceLast>false</EnableTotalsSliceLast>\n'
        '\t\t\t<RecordPresentation/><ExtendedRecordPresentation/><ListPresentation/><ExtendedListPresentation/><Explanation/>\n'
        '\t\t\t<DataHistory>DontUse</DataHistory>\n'
        '\t\t\t<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>\n'
        '\t\t\t<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'{res_xml}\n'
        f'{attr_xml}\n'
        f'{dim_xml}\n'
        '\t\t</ChildObjects>\n'
        '\t</InformationRegister>\n'
        '</MetaDataObject>\n'
    )


def build_subsystem_xml(name: str, synonym: str, content_refs, include_in_command_interface: bool = True) -> str:
    """
    content_refs: list["Catalog.Имя", "Document.Имя", "Report.Имя", ...] — полные
    имена объектов основной конфигурации. НЕТ InternalInfo (как у Role/CommonModule).
    КРИТИЧНО (см. get_guide("main_config_subsystem")): <Content> лежит ВНУТРИ
    <Properties>, ПОСЛЕДНИМ элементом — не рядом с ChildObjects снаружи (два
    неверных варианта порядка проверены вживую, оба дают ошибку формата документа,
    которая уходит ТОЛЬКО во всплывающий диалог Конфигуратора, не в /Out-лог).
    """
    items = "\n".join(f'\t\t\t\t<xr:Item xsi:type="xr:MDObjectRef">{ref}</xr:Item>' for ref in (content_refs or []))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Subsystem uuid="{uuid.uuid4()}">\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        f'\t\t\t<IncludeInCommandInterface>{"true" if include_in_command_interface else "false"}</IncludeInCommandInterface>\n'
        '\t\t\t<UseOneCommand>false</UseOneCommand>\n'
        '\t\t\t<Explanation/>\n'
        '\t\t\t<Picture/>\n'
        '\t\t\t<Content>\n'
        f'{items}\n'
        '\t\t\t</Content>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects/>\n'
        '\t</Subsystem>\n'
        '</MetaDataObject>\n'
    )


# ---------- ChartOfAccounts / AccountingRegister / Report+DCS (#38) ----------
# Форматы НЕ угаданы — построены по реальным подтверждённым дампам на диске
# (см. комментарий над CATEGORIES выше). Report+СКД — единственный подтверждённый
# случай: 1 dataSet-запрос, группировка по ОДНОМУ полю + детальные строки,
# параметр Период (StandardPeriod) + производные date-параметры с expression
# (TestDB15/Reports/ВедомостьПродаж, ПОСЛЕ фикса перепутанных
# НачалоПериода/КонецПериода из #33). Более сложные схемы СКД (несколько
# dataSet, вычисляемые поля, ресурсы-итоги, условное оформление, "быстрые"
# параметры) НЕ подтверждены этим тулом — собирайте руками,
# см. get_guide("main_config_report_dcs").

def build_chart_of_accounts_xml(name: str, synonym: str, code_length: int = 9,
                                 description_length: int = 25, extra_attrs=None) -> str:
    """
    ПОДТВЕРЖДЕНО реальным дампом (runtime/config_src/MetaTemplates/ChartsOfAccounts/
    Тест_ПланСчетов.xml). MaxExtDimensionCount ЗАФИКСИРОВАН на 0 (доп. измерения
    счетов этот тул не создаёт) — категории ExtDimensionTypes/ExtDimensionTypesRow
    в InternalInfo нужны ВСЕГДА независимо от этого (подтверждено, см.
    get_guide("main_config_internal_info")). extra_attrs — доп. реквизиты (см.
    _ATTR_SPEC_DOC) — у подтверждённого примера ChildObjects были пустыми.
    Предопределённые счета — ОТДЕЛЬНЫЙ файл, см. build_predefined_accounts_xml.
    """
    internal = gen_internal_info("ChartOfAccounts", name)
    attrs_xml = _attr_list(extra_attrs or [])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<ChartOfAccounts uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<BasedOn/>\n'
        '\t\t\t<ExtDimensionTypes/>\n'
        '\t\t\t<MaxExtDimensionCount>0</MaxExtDimensionCount>\n'
        '\t\t\t<CodeMask/>\n'
        f'\t\t\t<CodeLength>{code_length}</CodeLength>\n'
        f'\t\t\t<DescriptionLength>{description_length}</DescriptionLength>\n'
        '\t\t\t<CodeSeries>WholeChartOfAccounts</CodeSeries>\n'
        '\t\t\t<CheckUnique>true</CheckUnique>\n'
        '\t\t\t<DefaultPresentation>AsCode</DefaultPresentation>\n'
        '\t\t\t<Characteristics/>\n'
        '\t\t\t<PredefinedDataUpdate>Auto</PredefinedDataUpdate>\n'
        '\t\t\t<EditType>InDialog</EditType>\n'
        '\t\t\t<QuickChoice>false</QuickChoice>\n'
        '\t\t\t<ChoiceMode>BothWays</ChoiceMode>\n'
        '\t\t\t<InputByString>\n'
        f'\t\t\t\t<xr:Field>ChartOfAccounts.{name}.StandardAttribute.Description</xr:Field>\n'
        f'\t\t\t\t<xr:Field>ChartOfAccounts.{name}.StandardAttribute.Code</xr:Field>\n'
        '\t\t\t</InputByString>\n'
        '\t\t\t<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>\n'
        '\t\t\t<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>\n'
        '\t\t\t<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>\n'
        '\t\t\t<CreateOnInput>DontUse</CreateOnInput>\n'
        '\t\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>\n'
        '\t\t\t<DefaultObjectForm/><DefaultListForm/><DefaultChoiceForm/>\n'
        '\t\t\t<AuxiliaryObjectForm/><AuxiliaryListForm/><AuxiliaryChoiceForm/>\n'
        '\t\t\t<AutoOrderByCode>false</AutoOrderByCode>\n'
        '\t\t\t<OrderLength>0</OrderLength>\n'
        '\t\t\t<DataLockFields/>\n'
        '\t\t\t<DataLockControlMode>Managed</DataLockControlMode>\n'
        '\t\t\t<FullTextSearch>Use</FullTextSearch>\n'
        '\t\t\t<DataHistory>DontUse</DataHistory>\n'
        '\t\t\t<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>\n'
        '\t\t\t<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>\n'
        '\t\t\t<ObjectPresentation/><ExtendedObjectPresentation/><ListPresentation/><ExtendedListPresentation/><Explanation/>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'{attrs_xml}\n'
        '\t\t</ChildObjects>\n'
        '\t</ChartOfAccounts>\n'
        '</MetaDataObject>\n'
    )


def _predefined_account_item_xml(spec: dict, indent: str = "\t\t") -> str:
    children = spec.get("children") or []
    if children:
        children_xml = (f'{indent}\t<ChildItems>\n' +
                         "\n".join(_predefined_account_item_xml(c, indent + "\t\t") for c in children) +
                         f'\n{indent}\t</ChildItems>\n')
    else:
        children_xml = f'{indent}\t<ChildItems/>\n'
    return (
        f'{indent}<Item id="{uuid.uuid4()}">\n'
        f'{indent}\t<Name>{spec["name"]}</Name>\n'
        f'{indent}\t<Code>{spec["code"]}</Code>\n'
        f'{indent}\t<Description>{spec.get("description", spec["name"])}</Description>\n'
        f'{indent}\t<AccountType>{spec.get("account_type", "ActivePassive")}</AccountType>\n'
        f'{indent}\t<OffBalance>{"true" if spec.get("off_balance") else "false"}</OffBalance>\n'
        f'{indent}\t<Order/>\n'
        f'{indent}\t<AccountingFlags/>\n'
        f'{children_xml}'
        f'{indent}</Item>'
    )


def build_predefined_accounts_xml(items: list) -> str:
    """
    ПОДТВЕРЖДЕНО реальным дампом (MetaTemplates/ChartsOfAccounts/Тест_ПланСчетов/
    Ext/Predefined.xml). items: [{"name","code","description",
    "account_type":"Active"|"Passive"|"ActivePassive","off_balance":bool,
    "children":[...]}, ...] — children рекурсивно, тот же формат.
    """
    body = "\n".join(_predefined_account_item_xml(it) for it in items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef" xmlns:v8="http://v8.1c.ru/8.1/data/core" '
        'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="ChartOfAccountsPredefinedItems" version="2.19">\n'
        f'{body}\n'
        '</PredefinedData>\n'
    )


def _accounting_resource_xml(name: str, indent: str = "\t\t\t") -> str:
    """ПОДТВЕРЖДЕНО реальным дампом — формат Resource у AccountingRegister
    ОТЛИЧАЕТСЯ от обычного _attribute_xml (НЕТ тега <Indexing>, есть
    Balance/AccountingFlag/ExtDimensionAccountingFlag перед FullTextSearch) —
    намеренно НЕ переиспользует generic-шаблон, чтобы не тащить туда
    неподтверждённый для этого вида объекта тег."""
    return (
        f'{indent}<Resource uuid="{uuid.uuid4()}">\n'
        f'{indent}\t<Properties>\n'
        f'{indent}\t\t<Name>{name}</Name>\n'
        f'{indent}\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{name}</v8:content></v8:item></Synonym>\n'
        f'{indent}\t\t<Comment/>\n'
        f'{indent}\t\t{type_decimal()}\n'
        f'{indent}\t\t<PasswordMode>false</PasswordMode><Format/><EditFormat/><ToolTip/>\n'
        f'{indent}\t\t<MarkNegatives>false</MarkNegatives><Mask/><MultiLine>false</MultiLine>\n'
        f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>\n'
        f'{indent}\t\t<MinValue xsi:nil="true"/><MaxValue xsi:nil="true"/>\n'
        f'{indent}\t\t<FillChecking>DontCheck</FillChecking>\n'
        f'{indent}\t\t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>\n'
        f'{indent}\t\t<ChoiceParameterLinks/><ChoiceParameters/>\n'
        f'{indent}\t\t<QuickChoice>Auto</QuickChoice><CreateOnInput>Auto</CreateOnInput>\n'
        f'{indent}\t\t<ChoiceForm/><LinkByType/><ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>\n'
        f'{indent}\t\t<Balance>true</Balance><AccountingFlag/><ExtDimensionAccountingFlag/>\n'
        f'{indent}\t\t<FullTextSearch>Use</FullTextSearch>\n'
        f'{indent}\t</Properties>\n'
        f'{indent}</Resource>'
    )


def build_accounting_register_xml(name: str, synonym: str, chart_of_accounts: str,
                                   resources, correspondence: bool = True) -> str:
    """
    ПОДТВЕРЖДЕНО реальным дампом (MetaTemplates/AccountingRegisters/
    Тест_РегистрБухгалтерии.xml). resources — список ИМЁН (не спеков — Resource
    регистра бухгалтерии всегда decimal(10,0)+Balance=true, единственный
    подтверждённый вариант, см. _accounting_resource_xml). chart_of_accounts —
    ИМЯ уже существующего ПланСчетов (должен существовать в конфигурации на
    момент LoadConfigFromFiles). correspondence=True (по умолчанию) — БЕЗ
    корреспонденции (false) движения используют одиночный Счет+ВидДвижения
    вместо пары СчетДт/СчетКт (см. get_guide("main_config_accounting"), грабля
    "Поле объекта не обнаружено (СчетДт)").
    """
    internal = gen_internal_info("AccountingRegister", name)
    res_xml = "\n".join(_accounting_resource_xml(r) for r in (resources or ["Сумма"]))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<AccountingRegister uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        f'\t\t\t<ChartOfAccounts>ChartOfAccounts.{chart_of_accounts}</ChartOfAccounts>\n'
        f'\t\t\t<Correspondence>{"true" if correspondence else "false"}</Correspondence>\n'
        '\t\t\t<PeriodAdjustmentLength>0</PeriodAdjustmentLength>\n'
        '\t\t\t<DefaultListForm/><AuxiliaryListForm/>\n'
        '\t\t\t<DataLockControlMode>Managed</DataLockControlMode>\n'
        '\t\t\t<EnableTotalsSplitting>true</EnableTotalsSplitting>\n'
        '\t\t\t<FullTextSearch>DontUse</FullTextSearch>\n'
        '\t\t\t<ListPresentation/><ExtendedListPresentation/><Explanation/>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'{res_xml}\n'
        '\t\t</ChildObjects>\n'
        '\t</AccountingRegister>\n'
        '</MetaDataObject>\n'
    )


def _report_field_xml(field_name: str) -> str:
    return (f'\t\t<field xsi:type="DataSetFieldField">\n'
            f'\t\t\t<dataPath>{field_name}</dataPath>\n'
            f'\t\t\t<field>{field_name}</field>\n'
            f'\t\t</field>')


def _report_period_parameter_xml() -> str:
    """ПОДТВЕРЖДЕНО (TestDB15/ВедомостьПродаж) — параметр "Период" (v8:StandardPeriod),
    рекомендуемый способ дать пользователю пикер периода одним полем."""
    return (
        '\t<parameter>\n'
        '\t\t<name>Период</name>\n'
        '\t\t<title xsi:type="v8:LocalStringType"><v8:item><v8:lang>ru</v8:lang>'
        '<v8:content>Период</v8:content></v8:item></title>\n'
        '\t\t<valueType><v8:Type>v8:StandardPeriod</v8:Type></valueType>\n'
        '\t\t<value xsi:type="v8:StandardPeriod">\n'
        '\t\t\t<v8:variant xsi:type="v8:StandardPeriodVariant">Custom</v8:variant>\n'
        '\t\t\t<v8:startDate>0001-01-01T00:00:00</v8:startDate>\n'
        '\t\t\t<v8:endDate>0001-01-01T00:00:00</v8:endDate>\n'
        '\t\t</value>\n'
        '\t\t<useRestriction>false</useRestriction>\n'
        '\t</parameter>'
    )


def _report_date_expr_parameter_xml(name: str, title: str, expression: str) -> str:
    """ПОДТВЕРЖДЕНО — производный параметр даты через <expression> (например
    &Период.ДатаНачала/&Период.ДатаОкончания) — "&" экранируется автоматически
    здесь, передавайте expression БЕЗ ручного &amp;. ГРАБЛЯ (см. #33): не
    перепутайте местами — expression для "НачалоПериода" должен ссылаться на
    ДатаНачала, для "КонецПериода" — на ДатаОкончания (перепутанные местами
    дают отчёт, который молча возвращает 0 строк без единой ошибки)."""
    from xml.sax.saxutils import escape
    return (
        '\t<parameter>\n'
        f'\t\t<name>{name}</name>\n'
        f'\t\t<title xsi:type="v8:LocalStringType"><v8:item><v8:lang>ru</v8:lang>'
        f'<v8:content>{title}</v8:content></v8:item></title>\n'
        '\t\t<valueType><v8:Type>xs:dateTime</v8:Type><v8:DateQualifiers>'
        '<v8:DateFractions>DateTime</v8:DateFractions></v8:DateQualifiers></valueType>\n'
        '\t\t<value xsi:type="xs:dateTime">0001-01-01T00:00:00</value>\n'
        '\t\t<useRestriction>true</useRestriction>\n'
        f'\t\t<expression>{escape(expression)}</expression>\n'
        '\t\t<availableAsField>false</availableAsField>\n'
        '\t</parameter>'
    )


def _grouping_xml(fields: list, depth: int = 0) -> str:
    """
    Рекурсивно строит вложенные dcsset:item StructureItemGroup — ПОДТВЕРЖДЕНО
    (ВедомостьПродаж: группировка по Складу с детальными строками внутри).
    fields[0] — поле текущего уровня группировки, fields[1:] — вложенные уровни;
    fields=[] на любой глубине -> детальные строки (groupItems отсутствует).
    """
    indent = "\t" * (depth + 3)
    if not fields:
        return (
            f'{indent}<dcsset:item xsi:type="dcsset:StructureItemGroup">\n'
            f'{indent}\t<dcsset:order><dcsset:item xsi:type="dcsset:OrderItemAuto"/></dcsset:order>\n'
            f'{indent}\t<dcsset:selection><dcsset:item xsi:type="dcsset:SelectedItemAuto"/></dcsset:selection>\n'
            f'{indent}</dcsset:item>'
        )
    field, rest = fields[0], fields[1:]
    inner = _grouping_xml(rest, depth + 1)
    return (
        f'{indent}<dcsset:item xsi:type="dcsset:StructureItemGroup">\n'
        f'{indent}\t<dcsset:groupItems>\n'
        f'{indent}\t\t<dcsset:item xsi:type="dcsset:GroupItemField">\n'
        f'{indent}\t\t\t<dcsset:field>{field}</dcsset:field>\n'
        f'{indent}\t\t\t<dcsset:groupType>Items</dcsset:groupType>\n'
        f'{indent}\t\t\t<dcsset:periodAdditionType>None</dcsset:periodAdditionType>\n'
        f'{indent}\t\t\t<dcsset:periodAdditionBegin xsi:type="xs:dateTime">0001-01-01T00:00:00</dcsset:periodAdditionBegin>\n'
        f'{indent}\t\t\t<dcsset:periodAdditionEnd xsi:type="xs:dateTime">0001-01-01T00:00:00</dcsset:periodAdditionEnd>\n'
        f'{indent}\t\t</dcsset:item>\n'
        f'{indent}\t</dcsset:groupItems>\n'
        f'{indent}\t<dcsset:order><dcsset:item xsi:type="dcsset:OrderItemAuto"/></dcsset:order>\n'
        f'{indent}\t<dcsset:selection><dcsset:item xsi:type="dcsset:SelectedItemAuto"/></dcsset:selection>\n'
        f'{inner}\n'
        f'{indent}</dcsset:item>'
    )


def build_report_dcs_schema_xml(query_text: str, query_fields: list, display_fields: list = None,
                                 groupings: list = None, order_fields: list = None,
                                 period_parameter: bool = False, date_expr_parameters: list = None) -> str:
    """
    Собирает САМУ схему СКД (Reports/Имя/Templates/Схема/Ext/Template.xml).
    ПОДТВЕРЖДЕНО только для описанной здесь формы — см. докстринг секции выше.

    query_text — ТЕКСТ ЗАПРОСА КАК ЕСТЬ (с &Параметр), БЕЗ ручного экранирования
    "&" — экранируется здесь автоматически (см. грабля "10 минут зависшего
    процесса" — HANDOFF_ARCHIVE.md #31 п.7).
    query_fields — SELECT-список запроса (для декларации dataSet, включая поля,
    которые не показываются в отчёте, но нужны для группировки/связей).
    display_fields — что показывать в таблице отчёта (по умолчанию = query_fields).
    groupings — [ПолеГруппировки, ...], один уровень вложенности на элемент
    списка, ПОСЛЕДНИЙ уровень — всегда детальные строки (см. _grouping_xml).
    order_fields — сортировка (по умолчанию = groupings).
    period_parameter — добавить параметр "Период" (v8:StandardPeriod, пикер).
    date_expr_parameters — [{"name","title","expression"}, ...] — производные
    параметры (например NachaloPerioda/KonecPerioda из &Период.ДатаНачала/
    ДатаОкончания) — см. _report_date_expr_parameter_xml про граблю с перепутыванием.
    "Быстрые параметры" (dcsset:dataParameters) НЕ реализованы — не подтверждено
    для генерализованного случая, добавляйте руками при необходимости.
    """
    from xml.sax.saxutils import escape
    display_fields = display_fields if display_fields is not None else query_fields
    order_fields = order_fields if order_fields is not None else (groupings or [])

    fields_xml = "\n".join(_report_field_xml(f) for f in query_fields)
    selection_xml = "\n".join(
        f'\t\t\t\t<dcsset:item xsi:type="dcsset:SelectedItemField"><dcsset:field>{f}</dcsset:field></dcsset:item>'
        for f in display_fields
    )
    order_xml = "\n".join(
        f'\t\t\t\t<dcsset:item xsi:type="dcsset:OrderItemField"><dcsset:field>{f}</dcsset:field>'
        f'<dcsset:orderType>Asc</dcsset:orderType></dcsset:item>'
        for f in order_fields
    )

    params = []
    if period_parameter:
        params.append(_report_period_parameter_xml())
    for p in (date_expr_parameters or []):
        params.append(_report_date_expr_parameter_xml(p["name"], p.get("title", p["name"]), p["expression"]))
    params_xml = ("\n" + "\n".join(params)) if params else ""

    grouping_xml = _grouping_xml(groupings or [])

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<DataCompositionSchema xmlns="http://v8.1c.ru/8.1/data-composition-system/schema" '
        'xmlns:dcscom="http://v8.1c.ru/8.1/data-composition-system/common" '
        'xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" '
        'xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings" '
        'xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        '\t<dataSource>\n\t\t<name>ИсточникДанных1</name>\n\t\t<dataSourceType>Local</dataSourceType>\n\t</dataSource>\n'
        '\t<dataSet xsi:type="DataSetQuery">\n'
        '\t\t<name>НаборДанных1</name>\n'
        f'{fields_xml}\n'
        '\t\t<dataSource>ИсточникДанных1</dataSource>\n'
        f'\t\t<query>{escape(query_text)}</query>\n'
        '\t</dataSet>'
        f'{params_xml}\n'
        '\t<settingsVariant>\n'
        '\t\t<dcsset:name>Основной</dcsset:name>\n'
        '\t\t<dcsset:presentation xsi:type="xs:string">Основной</dcsset:presentation>\n'
        '\t\t<dcsset:settings xmlns:style="http://v8.1c.ru/8.1/data/ui/style" '
        'xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" '
        'xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows">\n'
        '\t\t\t<dcsset:selection>\n'
        f'{selection_xml}\n'
        '\t\t\t</dcsset:selection>\n'
        '\t\t\t<dcsset:order>\n'
        f'{order_xml}\n'
        '\t\t\t</dcsset:order>\n'
        f'{grouping_xml}\n'
        '\t\t</dcsset:settings>\n'
        '\t</settingsVariant>\n'
        '</DataCompositionSchema>\n'
    )


def build_report_xml(name: str, synonym: str, schema_name: str = "ОсновнаяСхемаКомпоновкиДанных") -> str:
    """ПОДТВЕРЖДЕНО реальным дампом (TestDB15/Reports/ВедомостьПродаж.xml)."""
    internal = gen_internal_info("Report", name)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Report uuid="{uuid.uuid4()}">\n'
        f'{internal}\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<UseStandardCommands>true</UseStandardCommands>\n'
        '\t\t\t<DefaultForm/><AuxiliaryForm/>\n'
        f'\t\t\t<MainDataCompositionSchema>Report.{name}.Template.{schema_name}</MainDataCompositionSchema>\n'
        '\t\t\t<DefaultSettingsForm/><AuxiliarySettingsForm/><DefaultVariantForm/>\n'
        '\t\t\t<VariantsStorage/><SettingsStorage/>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<ExtendedPresentation/><Explanation/>\n'
        '\t\t</Properties>\n'
        '\t\t<ChildObjects>\n'
        f'\t\t\t<Template>{schema_name}</Template>\n'
        '\t\t</ChildObjects>\n'
        '\t</Report>\n'
        '</MetaDataObject>\n'
    )


def build_report_template_descriptor_xml(schema_name: str) -> str:
    """ПОДТВЕРЖДЕНО — дескриптор макета (НЕ сама схема, см. build_report_dcs_schema_xml)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Template uuid="{uuid.uuid4()}">\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{schema_name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{schema_name}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<TemplateType>DataCompositionSchema</TemplateType>\n'
        '\t\t</Properties>\n'
        '\t</Template>\n'
        '</MetaDataObject>\n'
    )


# ---------- Формы документов (#38/#40) ----------
# Формат ПОДТВЕРЖДЁН реальными дампами (ПОСЛЕ фикса #34):
#   runtime/config_src/TestDB15/Documents/ПриходнаяНакладная/Forms/ФормаДокумента
#   runtime/config_src/TestDB15/Documents/РасходнаяНакладная/Forms/ФормаДокумента
#   runtime/config_src/TestDB15/Documents/ПриходнаяНакладная.xml (регистрация
#   формы в ChildObjects документа + DefaultObjectForm)
# Только формы ДОКУМЕНТОВ (не справочников/отчётов — для тех AutoTime/
# UsePostingMode/RepostOnWrite не подтверждены, возможно не нужны вовсе).

class _IdGen:
    """Счётчик уникальных id атрибутов внутри ОДНОГО файла формы. В реальных
    дампах номера НЕ строго top-down (у Table её "вспомогательные" элементы
    вроде SearchStringAddition получают id ПОСЛЕ всех полей формы, хотя стоят
    в файле раньше — платформе важна ТОЛЬКО уникальность в пределах файла, не
    порядок/непрерывность) — не пытаемся воспроизвести точный порядок
    Конфигуратора, просто гарантируем уникальность в порядке генерации."""
    def __init__(self):
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n


def _form_field_xml(ids: "_IdGen", name: str, data_path: str, on_change: str = None,
                     read_only: bool = False, name_prefix: str = "", indent: str = "\t\t\t") -> str:
    """
    ПОДТВЕРЖДЕНО. on_change — ИМЯ BSL-процедуры-обработчика. ГРАБЛЯ (см. #34):
    событие на платформенном уровне ВСЕГДА "OnChange" (английский внутренний
    идентификатор), НЕ русское "ПриИзменении" из палитры свойств — старый
    вариант проходит LoadConfigFromFiles/UpdateDBCfg БЕЗ ОШИБКИ, но в реальном
    клиенте не срабатывает. read_only — <ReadOnly>true</ReadOnly> СРАЗУ ПОСЛЕ
    <DataPath> (порядок подтверждён реальным дампом).
    """
    full_name = f"{name_prefix}{name}"
    field_id, ctx_id, tip_id = ids.next(), ids.next(), ids.next()
    read_only_tag = f'\n{indent}\t<ReadOnly>true</ReadOnly>' if read_only else ""
    events = (f'\n{indent}\t<Events>\n{indent}\t\t<Event name="OnChange">{on_change}</Event>\n{indent}\t</Events>'
              if on_change else "")
    return (
        f'{indent}<InputField name="{full_name}" id="{field_id}">\n'
        f'{indent}\t<DataPath>{data_path}</DataPath>'
        f'{read_only_tag}\n'
        f'{indent}\t<EditMode>EnterOnInput</EditMode>\n'
        f'{indent}\t<ExtendedEditMultipleValues>true</ExtendedEditMultipleValues>\n'
        f'{indent}\t<ContextMenu name="{full_name}КонтекстноеМеню" id="{ctx_id}"/>\n'
        f'{indent}\t<ExtendedTooltip name="{full_name}РасширеннаяПодсказка" id="{tip_id}"/>'
        f'{events}\n'
        f'{indent}</InputField>'
    )


def _form_group_xml(ids: "_IdGen", fields: list, group_name: str = None) -> str:
    """ПОДТВЕРЖДЕНО — горизонтальная группа полей в один ряд (например Номер+Дата)."""
    group_name = group_name or ("Группа" + "".join(f["name"] for f in fields))
    group_id, tip_id = ids.next(), ids.next()
    fields_xml = "\n".join(
        _form_field_xml(ids, f["name"], f["data_path"], on_change=f.get("on_change"),
                         read_only=f.get("read_only", False), indent="\t\t\t\t")
        for f in fields
    )
    return (
        f'\t\t\t<UsualGroup name="{group_name}" id="{group_id}">\n'
        f'\t\t\t\t<Group>Horizontal</Group>\n'
        f'\t\t\t\t<ExtendedTooltip name="{group_name}РасширеннаяПодсказка" id="{tip_id}"/>\n'
        f'\t\t\t\t<ChildItems>\n'
        f'{fields_xml}\n'
        f'\t\t\t\t</ChildItems>\n'
        f'\t\t\t</UsualGroup>'
    )


def _form_table_addition_xml(ids: "_IdGen", table_name: str, kind_name: str, addition_type: str) -> str:
    """ПОДТВЕРЖДЕНО — SearchStringAddition/ViewStatusAddition/SearchControlAddition,
    ОБЯЗАТЕЛЬНЫЙ boilerplate для КАЖДОЙ табличной части (идентичен в обоих
    подтверждённых примерах, во ВСЕХ трёх реальных таблицах) — не варьировать."""
    add_id, ctx_id, tip_id = ids.next(), ids.next(), ids.next()
    return (
        f'\t\t\t\t<{kind_name} name="{table_name}{kind_name}" id="{add_id}">\n'
        f'\t\t\t\t\t<AdditionSource>\n'
        f'\t\t\t\t\t\t<Item>{table_name}</Item>\n'
        f'\t\t\t\t\t\t<Type>{addition_type}</Type>\n'
        f'\t\t\t\t\t</AdditionSource>\n'
        f'\t\t\t\t\t<ContextMenu name="{table_name}{kind_name}КонтекстноеМеню" id="{ctx_id}"/>\n'
        f'\t\t\t\t\t<ExtendedTooltip name="{table_name}{kind_name}РасширеннаяПодсказка" id="{tip_id}"/>\n'
        f'\t\t\t\t</{kind_name}>'
    )


def _form_table_xml(ids: "_IdGen", table_name: str, data_path: str, columns: list) -> str:
    """ПОДТВЕРЖДЕНО — табличная часть формы. columns: [{"name","data_path",
    "on_change"?,"read_only"?}, ...] (см. _form_field_xml)."""
    table_id, ctx_id, cmdbar_id, tip_id = ids.next(), ids.next(), ids.next(), ids.next()
    cols_xml = "\n".join(
        _form_field_xml(ids, c["name"], c["data_path"], on_change=c.get("on_change"),
                         read_only=c.get("read_only", False), name_prefix=table_name, indent="\t\t\t\t")
        for c in columns
    )
    additions = "\n".join([
        _form_table_addition_xml(ids, table_name, "SearchStringAddition", "SearchStringRepresentation"),
        _form_table_addition_xml(ids, table_name, "ViewStatusAddition", "ViewStatusRepresentation"),
        _form_table_addition_xml(ids, table_name, "SearchControlAddition", "SearchControl"),
    ])
    return (
        f'\t\t\t<Table name="{table_name}" id="{table_id}">\n'
        f'\t\t\t\t<Representation>List</Representation>\n'
        f'\t\t\t\t<AutoInsertNewRow>true</AutoInsertNewRow>\n'
        f'\t\t\t\t<EnableStartDrag>true</EnableStartDrag>\n'
        f'\t\t\t\t<EnableDrag>true</EnableDrag>\n'
        f'\t\t\t\t<DataPath>{data_path}</DataPath>\n'
        f'\t\t\t\t<RowFilter xsi:nil="true"/>\n'
        f'\t\t\t\t<ContextMenu name="{table_name}КонтекстноеМеню" id="{ctx_id}"/>\n'
        f'\t\t\t\t<AutoCommandBar name="{table_name}КоманднаяПанель" id="{cmdbar_id}"/>\n'
        f'\t\t\t\t<ExtendedTooltip name="{table_name}РасширеннаяПодсказка" id="{tip_id}"/>\n'
        f'{additions}\n'
        f'\t\t\t\t<ChildItems>\n'
        f'{cols_xml}\n'
        f'\t\t\t\t</ChildItems>\n'
        f'\t\t\t</Table>'
    )


def build_document_form_xml(doc_name: str, header_fields: list, tables: list,
                             commands: list = None) -> str:
    """
    ПОДТВЕРЖДЕНО реальным дампом (см. комментарий секции выше). Только формы
    ДОКУМЕНТОВ с проведением.

    header_fields — список элементов шапки; каждый элемент ЛИБО одиночное
    поле {"name","data_path","on_change"?,"read_only"?}, ЛИБО СПИСОК из
    нескольких таких словарей — тогда они кладутся В ОДНУ ГОРИЗОНТАЛЬНУЮ
    ГРУППУ (UsualGroup), как Номер+Дата в подтверждённом примере.
    tables — [{"name","data_path","columns":[<спек поля>, ...]}, ...] — 0 или
    больше табличных частей (ОБЕИХ подтверждённых форм — 1 и 2 таблицы).
    commands — [{"name","title"?,"action"?}] — action по умолчанию = name
    (подтверждённый паттерн: имя клиентской BSL-процедуры = Action).
    """
    ids = _IdGen()
    header_parts = []
    for item in (header_fields or []):
        if isinstance(item, list):
            header_parts.append(_form_group_xml(ids, item))
        else:
            header_parts.append(_form_field_xml(ids, item["name"], item["data_path"],
                                                  on_change=item.get("on_change"),
                                                  read_only=item.get("read_only", False)))
    table_parts = [_form_table_xml(ids, t["name"], t["data_path"], t["columns"]) for t in (tables or [])]
    all_children = "\n".join(header_parts + table_parts)

    commands_xml = ""
    if commands:
        cmd_items = []
        for c in commands:
            cid = ids.next()
            action = c.get("action", c["name"])
            title = c.get("title", c["name"])
            cmd_items.append(
                f'\t\t<Command name="{c["name"]}" id="{cid}">\n'
                f'\t\t\t<Title><v8:item><v8:lang>ru</v8:lang><v8:content>{title}</v8:content></v8:item></Title>\n'
                f'\t\t\t<Action>{action}</Action>\n'
                f'\t\t</Command>'
            )
        commands_xml = '\t<Commands>\n' + "\n".join(cmd_items) + '\n\t</Commands>\n'

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Form {_FORM_NS}>\n'
        '\t<AutoTime>CurrentOrLast</AutoTime>\n'
        '\t<UsePostingMode>Auto</UsePostingMode>\n'
        '\t<RepostOnWrite>true</RepostOnWrite>\n'
        '\t<AutoCommandBar name="ФормаКоманднаяПанель" id="-1"/>\n'
        '\t<ChildItems>\n'
        f'{all_children}\n'
        '\t</ChildItems>\n'
        '\t<Attributes>\n'
        '\t\t<Attribute name="Объект" id="1">\n'
        '\t\t\t<Type>\n'
        f'\t\t\t\t<v8:Type>cfg:DocumentObject.{doc_name}</v8:Type>\n'
        '\t\t\t</Type>\n'
        '\t\t\t<MainAttribute>true</MainAttribute>\n'
        '\t\t\t<SavedData>true</SavedData>\n'
        '\t\t\t<UseAlways>\n'
        '\t\t\t\t<Field>Объект.RegisterRecords</Field>\n'
        '\t\t\t</UseAlways>\n'
        '\t\t</Attribute>\n'
        '\t</Attributes>\n'
        f'{commands_xml}'
        '</Form>\n'
    )


def build_form_descriptor_xml(form_name: str, synonym: str = None) -> str:
    """ПОДТВЕРЖДЕНО (TestDB15 Documents/*/Forms/ФормаДокумента.xml)."""
    synonym = synonym or form_name
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<MetaDataObject {_NS}>\n'
        f'\t<Form uuid="{uuid.uuid4()}">\n'
        '\t\t<Properties>\n'
        f'\t\t\t<Name>{form_name}</Name>\n'
        f'\t\t\t<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{synonym}</v8:content></v8:item></Synonym>\n'
        '\t\t\t<Comment/>\n'
        '\t\t\t<FormType>Managed</FormType>\n'
        '\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>\n'
        '\t\t\t<UsePurposes>\n'
        '\t\t\t\t<v8:Value xsi:type="app:ApplicationUsePurpose">PlatformApplication</v8:Value>\n'
        '\t\t\t\t<v8:Value xsi:type="app:ApplicationUsePurpose">MobilePlatformApplication</v8:Value>\n'
        '\t\t\t</UsePurposes>\n'
        '\t\t</Properties>\n'
        '\t</Form>\n'
        '</MetaDataObject>\n'
    )


def deploy_document_form(cfg: dict, ib_connection: str, doc_name: str, form_name: str,
                          form_xml: str, descriptor_xml: str, module_bsl: str = None,
                          set_as_default: bool = True, kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    Доставляет ОДНУ форму документа (ДОКУМЕНТ ДОЛЖЕН УЖЕ СУЩЕСТВОВАТЬ — создайте
    его сначала deploy_document): пишет дескриптор+саму форму(+Module.bsl),
    регистрирует `<Form>Имя</Form>` в ChildObjects документа (если ещё не
    зарегистрирована — идемпотентно) и, если set_as_default=True И
    `<DefaultObjectForm/>` у документа ещё ПУСТ (не трогает, если там уже что-то
    стоит — не переписываем существующий выбор пользователя), проставляет
    ссылку на новую форму (подтверждено реальным дампом — см. секцию выше).
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "main_src" / _safe_db_key(ib_connection)
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{dump_dir.name}_form_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1000)}

        doc_xml_path = dump_dir / "Documents" / f"{doc_name}.xml"
        if not doc_xml_path.exists():
            return {"ok": False, "step": "precheck",
                     "reason": f"документ {doc_name!r} не найден в дампе — создайте его сначала deploy_document"}

        descriptor_path = dump_dir / "Documents" / doc_name / "Forms" / f"{form_name}.xml"
        form_xml_path = dump_dir / "Documents" / doc_name / "Forms" / form_name / "Ext" / "Form.xml"
        descriptor_path.parent.mkdir(parents=True, exist_ok=True)
        form_xml_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor_path.write_text(descriptor_xml, encoding="utf-8-sig")
        form_xml_path.write_text(form_xml, encoding="utf-8-sig")
        written_paths = [descriptor_path, form_xml_path]

        if module_bsl:
            module_path = dump_dir / "Documents" / doc_name / "Forms" / form_name / "Ext" / "Form" / "Module.bsl"
            module_path.parent.mkdir(parents=True, exist_ok=True)
            module_path.write_text(module_bsl.lstrip("﻿"), encoding="utf-8-sig")

        doc_text = doc_xml_path.read_text(encoding="utf-8-sig")
        form_tag = f"\t\t\t<Form>{form_name}</Form>\n"
        already_registered = form_tag.strip() in doc_text
        if not already_registered:
            # ВАЖНО: искать "\n\t\t</ChildObjects>" (с ведущим \n), НЕ голое
            # "\t\t</ChildObjects>" — документ содержит ВЛОЖЕННЫЙ ChildObjects
            # внутри каждой TabularSection на БОЛЬШЕЙ глубине отступа (4 таба),
            # и голая 2-табная строка оказывается СУФФИКСОМ этой 4-табной
            # строки ("\t\t\t\t</ChildObjects>" содержит "\t\t</ChildObjects>"
            # как подстроку) — .replace(..., 1) находит и патчит ПЕРВОЕ
            # вхождение, которым оказывается ВЛОЖЕННЫЙ ChildObjects табличной
            # части, а не корневой ChildObjects документа (поймано тестом на
            # реальном дампе ПЕРЕД релизом, не в проде).
            target = "\n\t\t</ChildObjects>"
            if target not in doc_text:
                return {"ok": False, "step": "patch_childobjects",
                        "reason": "не найден ожидаемый </ChildObjects> документа верхнего уровня — "
                                  "структура дампа неожиданная, правьте руками"}
            doc_text = doc_text.replace(target, "\n" + form_tag + "\t\t</ChildObjects>", 1)

        default_form_set = False
        if set_as_default and "<DefaultObjectForm/>" in doc_text:
            doc_text = doc_text.replace(
                "<DefaultObjectForm/>",
                f"<DefaultObjectForm>Document.{doc_name}.Form.{form_name}</DefaultObjectForm>", 1)
            default_form_set = True

        doc_xml_path.write_text(doc_text, encoding="utf-8-sig")
        written_paths.append(doc_xml_path)

        problems = validate_xml_files(written_paths)
        if problems:
            return {"ok": False, "step": "xml_validate", "problems": problems}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{dump_dir.name}_form_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc,
                    "log": read_designer_log(load_log, tail=1500), "kill_report": kill_report}

        update_log = log_dir / f"{dump_dir.name}_form_update.log"
        cmd_update = (f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg '
                      f'/DisableStartupMessages /Out "{update_log}"')
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc,
                    "log": read_designer_log(update_log, tail=1500), "kill_report": kill_report}

        return {"ok": True, "form_registered_now": not already_registered,
                "default_form_set": default_form_set, "kill_report": kill_report}


def sync_main_config_files(cfg: dict, ib_connection: str, writes: dict = None, deletes: list = None,
                            ensure_registered: list = None, kill_sessions: bool = True,
                            timeout: int = 600) -> dict:
    """
    #45/#46: точечная синхронизация ПРОИЗВОЛЬНЫХ файлов ОСНОВНОЙ конфигурации
    (аналог sync_extension_files, но БЕЗ -Extension) — патчит МНОЖЕСТВО
    существующих файлов ОДНИМ dump→load→update циклом, вместо N независимых
    deploy_*-вызовов, каждый из которых делает свой отдельный dump→load→update.

    Появился напрямую из-за живой находки (#44): регистр и документ-
    регистратор нельзя чинить/создавать РАЗДЕЛЬНЫМИ deploy_*-вызовами — при
    отсутствии хотя бы одного документа с этим регистром в RegisterRecords
    В ТОТ ЖЕ МОМЕНТ загрузки платформа отказывает ("Ни один из документов не
    является регистратором для регистра"). sync_main_config_files решает это,
    патча ОБА документа И новый регистр И его регистрацию в Configuration.xml
    за ОДИН проход.

    writes — {относительный_путь_в_дампе: содержимое}, например:
        "Documents/ПриходнаяНакладная.xml": "<полный XML документа>"
        "AccountingRegisters/Проводки.xml": "<XML нового регистра>"
        "AccountingRegisters/Проводки/Ext/Predefined.xml": "..."
    ВНИМАНИЕ: для XML-объектов это ПОЛНАЯ замена файла — используйте
    build_*_xml-функции этого же модуля, чтобы собрать корректный XML
    (с InternalInfo/uuid для новых объектов), а не пишите вручную с нуля.
    deletes — [относительный_путь, ...] — файл или папка удаляются.
    ensure_registered — [{"kind": "AccountingRegister", "name": "Проводки"}, ...] —
    добавляет `<Kind>Имя</Kind>` в ChildObjects КОРНЕВОГО Configuration.xml,
    ЕСЛИ там ещё нет (идемпотентно, безопасный якорь на переводе строки —
    см. _preserve_existing_ids/#43 про грабли с суффиксным совпадением).
    kind может быть любым известным тегом (Document/Catalog/AccountingRegister/
    CommonModule/...), не обязательно из CATEGORIES.

    НЕ регенерирует uuid/TypeId/ValueId существующих объектов (в отличие от
    deploy_metadata_object/_preserve_existing_ids) — вы сами пишете ПОЛНЫЙ
    XML в writes, включая то, что должно остаться неизменным (скопируйте
    существующий uuid из текущего дампа, если патчите уже существующий
    объект — см. dump_main_config/read_reference_snippet).
    """
    writes = writes or {}
    deletes = deletes or []
    ensure_registered = ensure_registered or []
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "main_src" / _safe_db_key(ib_connection)
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{dump_dir.name}_sync_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1500)}

        applied_writes, applied_deletes = [], []
        for rel_path, content in writes.items():
            target = dump_dir / Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix.lower() == ".xml":
                target.write_text(content, encoding="utf-8-sig")
            else:
                target.write_text(content.lstrip("﻿"), encoding="utf-8-sig")
            applied_writes.append(rel_path)

        for rel_path in deletes:
            target = dump_dir / Path(rel_path)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            applied_deletes.append(rel_path)

        config_xml_path = dump_dir / "Configuration.xml"
        registered_now = []
        if ensure_registered:
            config_text = config_xml_path.read_text(encoding="utf-8-sig")
            anchor = "\n\t\t</ChildObjects>"
            if anchor not in config_text:
                return {"ok": False, "step": "ensure_registered",
                        "reason": "не найден ожидаемый </ChildObjects> в корневом Configuration.xml"}
            for item in ensure_registered:
                tag_name = _TAG_BY_KIND.get(item["kind"], item["kind"])
                child_tag = f"\t\t\t<{tag_name}>{item['name']}</{tag_name}>\n"
                if child_tag.strip() not in config_text:
                    config_text = config_text.replace(anchor, "\n" + child_tag + "\t\t</ChildObjects>", 1)
                    registered_now.append(item)
            config_xml_path.write_text(config_text, encoding="utf-8-sig")

        touched_xml = [dump_dir / Path(p) for p in applied_writes if Path(p).suffix.lower() == ".xml"]
        if ensure_registered:
            touched_xml.append(config_xml_path)
        problems = validate_xml_files(touched_xml)
        if problems:
            return {"ok": False, "step": "xml_validate", "problems": problems,
                    "applied_writes": applied_writes, "applied_deletes": applied_deletes}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{dump_dir.name}_sync_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return {**watch_err, "kill_report": kill_report}
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc,
                    "log": read_designer_log(load_log, tail=1500),
                    "applied_writes": applied_writes, "applied_deletes": applied_deletes,
                    "kill_report": kill_report}

        update_log = log_dir / f"{dump_dir.name}_sync_update.log"
        cmd_update = (f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg '
                      f'/DisableStartupMessages /Out "{update_log}"')
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return {**watch_err, "kill_report": kill_report}
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc,
                    "log": read_designer_log(update_log, tail=1500),
                    "applied_writes": applied_writes, "applied_deletes": applied_deletes,
                    "kill_report": kill_report}

        return {"ok": True, "applied_writes": applied_writes, "applied_deletes": applied_deletes,
                "registered_now": registered_now, "kill_report": kill_report}


# ---------- Read-only ----------

def dump_main_config(cfg: dict, ib_connection: str, timeout: int = 600) -> dict:
    """
    ТОЛЬКО ЧТЕНИЕ: свежий DumpConfigToFiles ОСНОВНОЙ конфигурации (БЕЗ
    -Extension) в runtime/main_src/<db_key> -> возвращает локальный путь.
    Прямой аналог dump_extension (extension_deploy.py), но для основной
    конфигурации целиком — раньше собиралось руками через subprocess на
    каждый "просто посмотреть" (см. ретроотчёт по билету №15, TL;DR).

    Тот же managed-каталог (_safe_db_key), что использует
    deploy_catalog/deploy_document/... — после dump_main_config можно сразу
    Read/Grep по runtime/main_src/<db_key>, а следующий deploy_* просто
    освежит ту же папку, повторный дамп не нужен. Dump не эксклюзивен —
    kill_sessions не требуется, раннер (если поднят) не трогается.
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "main_src" / _safe_db_key(ib_connection)
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{dump_dir.name}_readonly_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1500)}

        return {"ok": True, "path": str(dump_dir)}


# ---------- Deploy pipeline ----------

def _preserve_existing_ids(new_xml: str, old_xml: str) -> str:
    """
    #41 (найдено ЖИВЫМ тестом, не угадано): при ОБНОВЛЕНИИ уже существующего
    объекта build_*_xml генерирует НОВЫЙ случайный корневой uuid объекта и
    новые TypeId/ValueId для каждого InternalInfo/GeneratedType — платформа
    отслеживает объекты метаданных ПО UUID, а не по имени, поэтому новый
    случайный uuid у объекта, который она уже знает под СТАРЫМ uuid (то же
    имя), трактуется как "старый объект удалён, создан новый с тем же
    именем". Проверено вживую: `UpdateDBCfg` отклонил такое изменение
    ("Недопустимое изменение регистра, в котором существуют записи") —
    для объекта БЕЗ зависимых регистров/данных это могло бы пройти МОЛЧА,
    но фактически уничтожив связь существующих данных со "старым" объектом.

    Решение: если объект уже существует (передан old_xml — содержимое СТАРОГО
    файла до перезаписи), сохранить его корневой uuid и TypeId/ValueId каждого
    GeneratedType (сматченного по name+category — они детерминированы от имени
    объекта, не меняются между вызовами) в НОВОМ тексте, вместо только что
    сгенерированных случайных значений. Для НОВОГО объекта (created=True) эта
    функция не вызывается — свежие uuid для по-настоящему новых объектов нужны.
    """
    m_old_root = re.search(r'uuid="([0-9a-fA-F-]{36})"', old_xml)
    if m_old_root:
        new_xml = re.sub(r'uuid="[0-9a-fA-F-]{36}"', f'uuid="{m_old_root.group(1)}"', new_xml, count=1)

    old_blocks = {}
    block_re = re.compile(
        r'<xr:GeneratedType name="([^"]+)" category="([^"]+)">.*?'
        r'<xr:TypeId>([0-9a-fA-F-]{36})</xr:TypeId>.*?'
        r'<xr:ValueId>([0-9a-fA-F-]{36})</xr:ValueId>.*?</xr:GeneratedType>',
        re.DOTALL)
    for m in block_re.finditer(old_xml):
        old_blocks[(m.group(1), m.group(2))] = (m.group(3), m.group(4))

    def _sub(m):
        key = (m.group(1), m.group(2))
        block_text = m.group(0)
        if key in old_blocks:
            old_type_id, old_value_id = old_blocks[key]
            block_text = re.sub(r'<xr:TypeId>[0-9a-fA-F-]{36}</xr:TypeId>',
                                 f'<xr:TypeId>{old_type_id}</xr:TypeId>', block_text, count=1)
            block_text = re.sub(r'<xr:ValueId>[0-9a-fA-F-]{36}</xr:ValueId>',
                                 f'<xr:ValueId>{old_value_id}</xr:ValueId>', block_text, count=1)
        return block_text

    return block_re.sub(_sub, new_xml)


def deploy_metadata_object(cfg: dict, ib_connection: str, kind: str, name: str, xml_content: str,
                            extra_files: dict = None, kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    kind: "Catalog" | "Document" | "AccumulationRegister" | "InformationRegister"
    xml_content: готовый XML объекта (см. build_*_xml выше).
    extra_files: {относительный_путь: содержимое} — доп. файлы (например
    Documents/<Имя>/Ext/ObjectModule.bsl для документа с БСЛ-логикой) —
    ВНИМАНИЕ: .bsl НЕ проходят XML-валидацию (это не XML), пишутся как есть
    (encoding utf-8-sig, с BOM — конвенция проекта).

    ОБНОВЛЕНИЕ существующего объекта (created=False) СОХРАНЯЕТ его текущий
    uuid/TypeId/ValueId (см. _preserve_existing_ids, #41) — не генерирует
    новые. Это единственная защита от того, чтобы платформа не восприняла
    правку существующего объекта как "удалить+создать заново".
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    if kind not in CATEGORIES and kind not in _NO_INTERNAL_INFO_KINDS:
        supported = list(CATEGORIES) + list(_NO_INTERNAL_INFO_KINDS)
        return {"ok": False, "step": "kind", "reason": f"неизвестный/необобщённый вид: {kind!r} — "
                                                          f"поддерживается: {supported}"}

    main_src_root = Path(cfg["runtime_dir"]) / "main_src"
    dump_dir = main_src_root / _safe_db_key(ib_connection)
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{dump_dir.name}_metadata_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1000)}

        tag = _TAG_BY_KIND[kind]
        folder = _FOLDER_BY_KIND[kind]
        obj_xml_path = dump_dir / folder / f"{name}.xml"
        child_tag = f"\t\t\t<{tag}>{name}</{tag}>\n"

        config_xml = dump_dir / "Configuration.xml"
        config_text = config_xml.read_text(encoding="utf-8-sig")
        is_registered = child_tag.strip() in config_text

        # #43 (найдено вживую): "существует" = файл ЕСТЬ И зарегистрирован в
        # Configuration.xml — НЕ только файл на диске. Однажды дамп содержал
        # ОСИРОТЕВШИЙ файл объекта, который пользователь уже удалил из
        # конфигурации в Конфигураторе, но файл почему-то остался в выгрузке —
        # created по одному только File.exists() ошибочно получался False,
        # из-за чего (а) _preserve_existing_ids сохранял uuid объекта,
        # которого больше нет ни в конфигурации, ни в реальной базе (может
        # создать НОВУЮ путаницу идентичности), и (б) тег регистрации в
        # Configuration.xml никогда не добавлялся заново — LoadConfigFromFiles/
        # UpdateDBCfg отчитывались успехом, но по факту это был no-op над
        # объектом, которого конфигурация не знает.
        created = not (obj_xml_path.exists() and is_registered)

        if not created:
            xml_content = _preserve_existing_ids(xml_content, obj_xml_path.read_text(encoding="utf-8-sig"))

        obj_xml_path.parent.mkdir(parents=True, exist_ok=True)
        obj_xml_path.write_text(xml_content, encoding="utf-8-sig")

        written_paths = [obj_xml_path]
        for rel_path, content in (extra_files or {}).items():
            fp = dump_dir / rel_path
            fp.parent.mkdir(parents=True, exist_ok=True)
            if fp.suffix.lower() == ".xml":
                fp.write_text(content, encoding="utf-8-sig")
            else:
                fp.write_text(content.lstrip("﻿"), encoding="utf-8-sig")
            written_paths.append(fp)

        if not is_registered:
            config_text = config_text.replace("\t\t</ChildObjects>", child_tag + "\t\t</ChildObjects>", 1)
            config_xml.write_text(config_text, encoding="utf-8-sig")
            written_paths.append(config_xml)

        # XML-валидация ДО похода в DESIGNER — ловит невалидный XML мгновенно
        # (см. докстринг модуля — реальный инцидент с "&" в DCS-запросе).
        problems = validate_xml_files(written_paths)
        if problems:
            return {"ok": False, "step": "xml_validate", "created": created, "problems": problems}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{dump_dir.name}_metadata_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc, "created": created,
                    "log": read_designer_log(load_log, tail=1500),
                    "kill_report": kill_report}

        update_log = log_dir / f"{dump_dir.name}_metadata_update.log"
        cmd_update = (f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg '
                      f'/DisableStartupMessages /Out "{update_log}"')
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc, "created": created,
                    "log": read_designer_log(update_log, tail=1500),
                    "kill_report": kill_report}

        return {"ok": True, "created": created, "kind": kind, "name": name, "kill_report": kill_report}


# ---------- High-level, JSON-friendly wrappers (для MCP-инструментов) ----------

def deploy_catalog(cfg: dict, ib_connection: str, name: str, synonym: str = "", attributes=None,
                    kill_sessions: bool = True, timeout: int = 600) -> dict:
    """attributes: [{"name":..,"type":"string"|"decimal"|"boolean"|"date"|"ref"|"enum_ref", ...}]."""
    xml = build_catalog_xml(name, synonym or name, attrs_from_specs(attributes))
    return deploy_metadata_object(cfg, ib_connection, "Catalog", name, xml,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_document(cfg: dict, ib_connection: str, name: str, synonym: str = "", header_attrs=None,
                     tabular_sections=None, posting_registers=None, object_module_bsl: str = None,
                     kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    tabular_sections: [{"name": "Строки", "columns": [<спек реквизита>, ...]}, ...]
    posting_registers: None (документ без движений) или
        ["AccumulationRegister.Имя", "AccountingRegister.Имя", ...] — регистры ДОЛЖНЫ
        уже существовать в конфигурации на момент вызова.
    object_module_bsl: код Documents/<Имя>/Ext/ObjectModule.bsl (например
        ОбработкаПроведения/ПередЗаписью) — см. get_guide("main_config_document"),
        ГРАБЛЯ: вычисляемые поля ТЧ пишите в ПередЗаписью, не в ОбработкаПроведения
        (иначе не сохранятся в саму запись документа, хотя корректно посчитаются
        и используются для движений в этом же прогоне).
    """
    ts = [(t["name"], attrs_from_specs(t.get("columns"))) for t in (tabular_sections or [])]
    xml = build_document_xml(name, synonym or name, attrs_from_specs(header_attrs), ts, posting_registers)
    extra = {}
    if object_module_bsl:
        extra[f"Documents/{name}/Ext/ObjectModule.bsl"] = object_module_bsl
    return deploy_metadata_object(cfg, ib_connection, "Document", name, xml, extra_files=extra,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_accumulation_register(cfg: dict, ib_connection: str, name: str, synonym: str = "",
                                  dimensions=None, resources=None, register_type: str = "Balance",
                                  kill_sessions: bool = True, timeout: int = 600) -> dict:
    xml = build_accumulation_register_xml(name, synonym or name, attrs_from_specs(dimensions),
                                           attrs_from_specs(resources), register_type)
    return deploy_metadata_object(cfg, ib_connection, "AccumulationRegister", name, xml,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_information_register(cfg: dict, ib_connection: str, name: str, synonym: str = "",
                                 dimensions=None, resources=None, attributes=None,
                                 periodicity: str = "Nonperiodical",
                                 kill_sessions: bool = True, timeout: int = 600) -> dict:
    xml = build_information_register_xml(name, synonym or name, attrs_from_specs(dimensions),
                                          attrs_from_specs(resources), attrs_from_specs(attributes), periodicity)
    return deploy_metadata_object(cfg, ib_connection, "InformationRegister", name, xml,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_subsystem(cfg: dict, ib_connection: str, name: str, synonym: str = "", content=None,
                      include_in_command_interface: bool = True,
                      kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    content: ["Catalog.Имя", "Document.Имя", "Report.Имя", ...] — полные имена
    объектов ОСНОВНОЙ конфигурации (уже существующих). Без подсистемы объекты
    существуют в метаданных, но НЕ появляются в интерфейсе клиента 1С —
    единственный способ сделать их видимыми пользователю.
    """
    xml = build_subsystem_xml(name, synonym or name, content, include_in_command_interface)
    return deploy_metadata_object(cfg, ib_connection, "Subsystem", name, xml,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_chart_of_accounts(cfg: dict, ib_connection: str, name: str, synonym: str = "",
                              code_length: int = 9, description_length: int = 25, attributes=None,
                              predefined_accounts: list = None,
                              kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    predefined_accounts — [{"name","code","description",
    "account_type":"Active"|"Passive"|"ActivePassive","off_balance":bool,
    "children":[...]}] -> отдельный файл Ext/Predefined.xml (см.
    build_predefined_accounts_xml). None/[] — план счетов без предопределённых счетов.
    """
    xml = build_chart_of_accounts_xml(name, synonym or name, code_length, description_length,
                                       attrs_from_specs(attributes))
    extra = {}
    if predefined_accounts:
        extra[f"ChartsOfAccounts/{name}/Ext/Predefined.xml"] = build_predefined_accounts_xml(predefined_accounts)
    return deploy_metadata_object(cfg, ib_connection, "ChartOfAccounts", name, xml, extra_files=extra,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_accounting_register(cfg: dict, ib_connection: str, name: str, chart_of_accounts: str,
                                synonym: str = "", resources: list = None, correspondence: bool = True,
                                kill_sessions: bool = True, timeout: int = 600) -> dict:
    """chart_of_accounts — имя УЖЕ существующего ПланСчетов (должен существовать
    в конфигурации на момент вызова). resources — список ИМЁН ресурсов (каждый
    decimal(10,0)+Balance=true, см. build_accounting_register_xml)."""
    xml = build_accounting_register_xml(name, synonym or name, chart_of_accounts, resources, correspondence)
    return deploy_metadata_object(cfg, ib_connection, "AccountingRegister", name, xml,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_report(cfg: dict, ib_connection: str, name: str, query_text: str, query_fields: list,
                   synonym: str = "", display_fields: list = None, groupings: list = None,
                   order_fields: list = None, period_parameter: bool = False,
                   date_expr_parameters: list = None, schema_name: str = "ОсновнаяСхемаКомпоновкиДанных",
                   kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    Report+СКД — см. build_report_dcs_schema_xml докстринг про подтверждённые/
    НЕподтверждённые части (только 1 dataSet, группировка по одному полю +
    детальные строки, период+производные параметры — остальное руками).
    "&" в query_text экранируется АВТОМАТИЧЕСКИ — пишите запрос как обычно
    (МЕЖДУ &НачалоПериода И &КонецПериода), без ручного &amp;.
    """
    obj_xml = build_report_xml(name, synonym or name, schema_name)
    template_descriptor = build_report_template_descriptor_xml(schema_name)
    schema_xml = build_report_dcs_schema_xml(
        query_text, query_fields, display_fields=display_fields, groupings=groupings,
        order_fields=order_fields, period_parameter=period_parameter,
        date_expr_parameters=date_expr_parameters,
    )
    extra = {
        f"Reports/{name}/Templates/{schema_name}.xml": template_descriptor,
        f"Reports/{name}/Templates/{schema_name}/Ext/Template.xml": schema_xml,
    }
    return deploy_metadata_object(cfg, ib_connection, "Report", name, obj_xml, extra_files=extra,
                                   kill_sessions=kill_sessions, timeout=timeout)


def deploy_form(cfg: dict, ib_connection: str, doc_name: str, header_fields: list = None,
                 tables: list = None, commands: list = None, module_bsl: str = None,
                 form_name: str = "ФормаДокумента", set_as_default: bool = True,
                 kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    Форма ДОКУМЕНТА (документ ДОЛЖЕН уже существовать). См. докстринг
    build_document_form_xml про подтверждённый охват header_fields/tables/
    commands. module_bsl — код Ext/Form/Module.bsl (клиентские процедуры,
    имена которых указаны в on_change/action полей и команд) — БИЗНЕС-ЛОГИКУ
    (например пересчёт Суммы) пишете сами, тул отвечает только за правильную
    XML-проводку событие->процедура (см. ГРАБЛЯ #34 в _form_field_xml).
    """
    form_xml = build_document_form_xml(doc_name, header_fields or [], tables or [], commands)
    descriptor_xml = build_form_descriptor_xml(form_name)
    return deploy_document_form(cfg, ib_connection, doc_name, form_name, form_xml, descriptor_xml,
                                 module_bsl=module_bsl, set_as_default=set_as_default,
                                 kill_sessions=kill_sessions, timeout=timeout)
