#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#16: развёртывание ОБЩЕГО МОДУЛЯ (не заимствованного) внутрь расширения через
файлы — без EDT, без ручного DumpConfigToFiles/правки XML/LoadConfigFromFiles
из чата. Закрывает боль #7: там та же операция руками заняла ~15 минут (искать
формат XML, чинить API YaXUnit, ловить баг с чейнингом команд). Теперь — один
вызов deploy_common_module()/MCP-инструмент deploy_module.

Годится и для тестовых модулей (Док_Имя, см. get_guide("yaxunit_tests")), и для
обычной бизнес-логики внутри расширения (ОМ_Имя) — разницы в механике нет,
разница только в содержимом bsl_code.

Пайплайн (все шаги ПОСЛЕДОВАТЕЛЬНЫМИ subprocess.run, НЕ чейнить через ";" в
одной команде — см. HANDOFF.md "Ключевые уроки": чейн двух DESIGNER-вызовов в
одной строке PowerShell один раз реально закатал старое содержимое модуля):
    1. DumpConfigToFiles -Extension <ext_name>   — свежий снимок (источник истины БД,
       не полагаемся на локальный кэш от прошлого вызова).
    2. Если CommonModules/<module_name>.xml ещё нет — создать его + прописать
       <CommonModule>Имя</CommonModule> в ChildObjects Configuration.xml.
       Если уже есть — просто перезаписать Ext/Module.bsl (дешевле, без правки XML).
    3. kill_sessions (монопольный доступ для файловой базы).
    4. LoadConfigFromFiles -Extension <ext_name>
    5. UpdateDBCfg -Extension <ext_name>
"""
import subprocess
import uuid
from pathlib import Path

from src.core.ib_connection import cli_connection_str
from src.onec.sessions import kill_matching_processes
from src.onec.designer_run import run_watched, watched_error
from src.core.dump_lock import dump_lock
from src.core.xml_validate import validate_xml_files
from src.core.designer_log import read_designer_log
from src.onec.metadata_deploy import _safe_db_key

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

_MODULE_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<MetaDataObject {ns}>\n'
    '\t<CommonModule uuid="{uid}">\n'
    '\t\t<Properties>\n'
    '\t\t\t<Name>{name}</Name>\n'
    '\t\t\t<Synonym>\n'
    '\t\t\t\t<v8:item>\n'
    '\t\t\t\t\t<v8:lang>ru</v8:lang>\n'
    '\t\t\t\t\t<v8:content>{synonym}</v8:content>\n'
    '\t\t\t\t</v8:item>\n'
    '\t\t\t</Synonym>\n'
    '\t\t\t<Comment/>\n'
    '\t\t\t<Global>false</Global>\n'
    '\t\t\t<ClientManagedApplication>{client}</ClientManagedApplication>\n'
    '\t\t\t<Server>{server}</Server>\n'
    '\t\t\t<ExternalConnection>false</ExternalConnection>\n'
    '\t\t\t<ClientOrdinaryApplication>{client}</ClientOrdinaryApplication>\n'
    '\t\t\t<ServerCall>false</ServerCall>\n'
    '\t\t\t<Privileged>false</Privileged>\n'
    '\t\t\t<ReturnValuesReuse>DontUse</ReturnValuesReuse>\n'
    '\t\t</Properties>\n'
    '\t</CommonModule>\n'
    '</MetaDataObject>\n'
)


def _run(cmd: str, timeout: int, cfg: dict, ib_connection: str, step: str) -> tuple:
    """#45: обёртка над designer_run.run_watched — см. metadata_deploy.py для полного объяснения."""
    watched = run_watched(cmd, timeout, cfg, ib_connection)
    return watched["returncode"], watched_error(step, watched, timeout)


def deploy_common_module(cfg: dict, ib_connection: str, ext_name: str, module_name: str,
                          bsl_code: str, synonym: str = "", server: bool = True, client: bool = False,
                          kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    Создаёт (если нет) или обновляет (если есть) общий модуль module_name внутри
    расширения ext_name, с текстом bsl_code, в базе ib_connection. Возвращает
    {"ok": bool, "created": bool, "step": "...", ...}.
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    ext_src_root = Path(cfg["runtime_dir"]) / "ext_src"
    dump_dir = ext_src_root / ext_name
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        # 1. свежий снимок — источник истины БД, не локальный кэш от прошлого вызова
        dump_log = log_dir / f"{ext_name}_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1000)}

        module_xml = dump_dir / "CommonModules" / f"{module_name}.xml"
        module_bsl = dump_dir / "CommonModules" / module_name / "Ext" / "Module.bsl"
        created = not module_xml.exists()

        # Best-effort проверка дублей: то же имя общего модуля уже задеплоено в ДРУГОЕ
        # расширение (по уже закэшированным дампам runtime/ext_src/*, не исчерпывающе —
        # не сканирует расширения, которые ни разу не дампились в этой сессии/машине).
        # См. HANDOFF.md #25, п.7 — так однажды получился дубль CommonModule.Имя в двух
        # расширениях и БД отказалась инициализировать модуль.
        duplicate_warning = None
        if created and ext_src_root.exists():
            for sibling in ext_src_root.iterdir():
                if sibling.name == ext_name or not sibling.is_dir():
                    continue
                if (sibling / "CommonModules" / f"{module_name}.xml").exists():
                    duplicate_warning = (
                        f"модуль {module_name!r} уже существует в закэшированном дампе "
                        f"расширения {sibling.name!r} — если это не намеренное совпадение, "
                        f"удалите старую копию через sync_extension_files(ext_name={sibling.name!r}, "
                        f"deletes=[\"CommonModules/{module_name}.xml\", \"CommonModules/{module_name}\"]) "
                        f"ПЕРЕД тем, как продолжать — иначе конфигурация не инициализируется "
                        f"(\"Уже существует объект с именем...\")."
                    )
                    break

        module_bsl.parent.mkdir(parents=True, exist_ok=True)
        # encoding="utf-8-sig" ниже сам допишет BOM — если bsl_code уже начинается
        # с явного BOM-символа, срезаем его здесь, иначе на диске окажется задвоенный
        # BOM (найдено при код-ревью, не воспроизведено вживую, но не безопасно оставлять).
        code = bsl_code.lstrip("﻿")
        module_bsl.write_text(code, encoding="utf-8-sig")

        if created:
            xml_text = _MODULE_XML_TEMPLATE.format(
                ns=_NS, uid=str(uuid.uuid4()), name=module_name,
                synonym=synonym or module_name,
                server="true" if server else "false",
                client="true" if client else "false",
            )
            module_xml.write_text(xml_text, encoding="utf-8-sig")

            config_xml = dump_dir / "Configuration.xml"
            text = config_xml.read_text(encoding="utf-8-sig")
            tag = f"\t\t\t<CommonModule>{module_name}</CommonModule>\n"
            if tag not in text:
                # ВАЖНО: якорь "\n\t\t</ChildObjects>" (с ведущим \n), НЕ голое
                # "\t\t</ChildObjects>" — если это же расширение содержит объект с
                # ВЛОЖЕННЫМ ChildObjects на большей глубине (например DataProcessor
                # с табличной частью), голая 2-табная строка окажется СУФФИКСОМ
                # более глубокой закрывающей строки — .replace() без anchor патчит
                # ПЕРВОЕ (вложенное) вхождение, а не корневой ChildObjects
                # расширения (тот же класс бага, что нашёлся и исправлен для
                # основной конфигурации — см. metadata_deploy.py, HANDOFF #40).
                target = "\n\t\t</ChildObjects>"
                if target not in text:
                    return {"ok": False, "step": "patch_childobjects", "created": created,
                            "reason": "не найден ожидаемый </ChildObjects> расширения верхнего уровня — "
                                      "структура дампа неожиданная, правьте руками"}
                text = text.replace(target, "\n" + tag + "\t\t</ChildObjects>", 1)
                config_xml.write_text(text, encoding="utf-8-sig")

            # XML-валидация ДО похода в DESIGNER — невалидный XML иначе не падает
            # быстро с понятной ошибкой, а вешает DESIGNER на минуты с пустым логом
            # (найдено вживую, #билет15, см. src/core/xml_validate.py).
            problems = validate_xml_files([module_xml, config_xml])
            if problems:
                return {"ok": False, "step": "xml_validate", "created": created, "problems": problems}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        # 2. загрузить обратно и обновить БД — ДВА РАЗДЕЛЬНЫХ вызова, не чейнить
        load_log = log_dir / f"{ext_name}_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'-Extension {ext_name} /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc, "created": created,
                    "log": read_designer_log(load_log, tail=1000),
                    "kill_report": kill_report}

        update_log = log_dir / f"{ext_name}_update.log"
        cmd_update = f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg -Extension {ext_name} /Out "{update_log}"'
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc, "created": created,
                    "log": read_designer_log(update_log, tail=1000),
                    "kill_report": kill_report}

        result = {"ok": True, "created": created, "module": module_name, "extension": ext_name,
                  "kill_report": kill_report}
        if duplicate_warning:
            result["duplicate_warning"] = duplicate_warning
        return result


def deploy_main_common_module(cfg: dict, ib_connection: str, module_name: str, bsl_code: str,
                               synonym: str = "", server: bool = True, client: bool = False,
                               kill_sessions: bool = True, timeout: int = 600) -> dict:
    """
    #47 (задача 4): общий модуль ПРЯМО в ОСНОВНОЙ конфигурации (НЕ внутри
    расширения — для этого используйте deploy_module/deploy_common_module).
    Формат CommonModule.xml подтверждён реальным дампом ERP АПК
    (CommonModules/ZipАрхивы.xml, C:\\Users\\danua\\Desktop\\vkr\\Конфигурация) —
    структура ПОЛНОСТЬЮ совпадает с уже используемым здесь _MODULE_XML_TEMPLATE
    (MetaDataObject/CommonModule/Properties, тот же набор полей); отличаются
    только конкретные значения (Global/Server/...), не форма тега — то есть тот
    же шаблон годится БЕЗ изменений.

    Пайплайн ПОЛНОСТЬЮ аналогичен deploy_common_module (это НЕ обёртка над
    sync_main_config_files: та функция не регенерирует uuid существующих
    объектов сама — ответственность на вызывающем, а нам как раз нужно решить
    create-vs-update ДО того, как решать, писать ли новый uuid, — тот же
    порядок действий, что уже отработан для расширений ниже) — ЕДИНСТВЕННОЕ
    отличие: DumpConfigToFiles/LoadConfigFromFiles/UpdateDBCfg БЕЗ -Extension,
    дамп лежит в runtime/main_src/<db_key> (тот же ключ, что sync_main_config_files/
    dump_main_config — можно переиспользовать один и тот же локальный кэш).
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    dump_dir = Path(cfg["runtime_dir"]) / "main_src" / _safe_db_key(ib_connection)
    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with dump_lock(dump_dir):
        dump_log = log_dir / f"{dump_dir.name}_cm_dump.log"
        cmd_dump = (f'"{cfg["path_1c"]}" DESIGNER {conn} /DumpConfigToFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{dump_log}"')
        rc, watch_err = _run(cmd_dump, timeout, cfg, ib_connection, "DumpConfigToFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "DumpConfigToFiles", "returncode": rc,
                    "log": read_designer_log(dump_log, tail=1000)}

        module_xml = dump_dir / "CommonModules" / f"{module_name}.xml"
        module_bsl = dump_dir / "CommonModules" / module_name / "Ext" / "Module.bsl"
        created = not module_xml.exists()

        module_bsl.parent.mkdir(parents=True, exist_ok=True)
        code = bsl_code.lstrip("﻿")
        module_bsl.write_text(code, encoding="utf-8-sig")

        if created:
            xml_text = _MODULE_XML_TEMPLATE.format(
                ns=_NS, uid=str(uuid.uuid4()), name=module_name,
                synonym=synonym or module_name,
                server="true" if server else "false",
                client="true" if client else "false",
            )
            module_xml.write_text(xml_text, encoding="utf-8-sig")

            config_xml = dump_dir / "Configuration.xml"
            text = config_xml.read_text(encoding="utf-8-sig")
            tag = f"\t\t\t<CommonModule>{module_name}</CommonModule>\n"
            if tag not in text:
                # см. #47/#40 — якорь ОБЯЗАТЕЛЬНО с ведущим \n, иначе суффиксное
                # совпадение с более глубоко вложенным </ChildObjects> патчит не тот узел.
                target = "\n\t\t</ChildObjects>"
                if target not in text:
                    return {"ok": False, "step": "patch_childobjects", "created": created,
                            "reason": "не найден ожидаемый </ChildObjects> корневого Configuration.xml — "
                                      "структура дампа неожиданная, правьте руками"}
                text = text.replace(target, "\n" + tag + "\t\t</ChildObjects>", 1)
                config_xml.write_text(text, encoding="utf-8-sig")

            problems = validate_xml_files([module_xml, config_xml])
            if problems:
                return {"ok": False, "step": "xml_validate", "created": created, "problems": problems}

        kill_report = None
        if kill_sessions:
            kill_report = kill_matching_processes(ib_connection)

        load_log = log_dir / f"{dump_dir.name}_cm_load.log"
        cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} /LoadConfigFromFiles "{dump_dir}" '
                    f'/DisableStartupMessages /Out "{load_log}"')
        rc, watch_err = _run(cmd_load, timeout, cfg, ib_connection, "LoadConfigFromFiles")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "LoadConfigFromFiles", "returncode": rc, "created": created,
                    "log": read_designer_log(load_log, tail=1000),
                    "kill_report": kill_report}

        update_log = log_dir / f"{dump_dir.name}_cm_update.log"
        cmd_update = f'"{cfg["path_1c"]}" DESIGNER {conn} /UpdateDBCfg /DisableStartupMessages /Out "{update_log}"'
        rc, watch_err = _run(cmd_update, timeout, cfg, ib_connection, "UpdateDBCfg")
        if watch_err:
            return watch_err
        if rc != 0:
            return {"ok": False, "step": "UpdateDBCfg", "returncode": rc, "created": created,
                    "log": read_designer_log(update_log, tail=1000),
                    "kill_report": kill_report}

        return {"ok": True, "created": created, "module": module_name, "kill_report": kill_report}
