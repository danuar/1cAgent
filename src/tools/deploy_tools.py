#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РЕЖИМ B — доставка правок в живую базу: deploy_module/dump_extension/deploy_extension_from_files/sync_extension_files."""
from src.tools.core import mcp, CFG, _spawn
from src.onec.module_deploy import (deploy_common_module as _deploy_module,
                                     deploy_main_common_module as _deploy_main_common_module)
from src.onec.extension_deploy import (deploy_extension_from_files as _deploy_extension_from_files,
                               sync_extension_files as _sync_extension_files,
                               dump_extension as _dump_extension,
                               adopt_object as _adopt_object,
                               deploy_http_service as _deploy_http_service,
                               adopt_form as _adopt_form)


@mcp.tool()
def deploy_module(ib_connection: str, ext_name: str, module_name: str, bsl_code: str,
                   synonym: str = "", client: bool = False, kill_sessions: bool = True) -> dict:
    """Async. Создать/обновить ОБЩИЙ модуль в расширении ext_name (логика или тесты YaXUnit). По умолчанию чисто серверный; client=True только если нужен клиентский контекст (клиент+сервер одновременно ломает вызовы серверных модулей). В результате возможен duplicate_warning (то же имя в другом расширении). Перед тестовым модулем — get_guide('yaxunit_tests')."""
    jid = _spawn(_deploy_module, CFG, ib_connection, ext_name, module_name, bsl_code,
                 synonym=synonym, client=client, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}


@mcp.tool()
def deploy_main_common_module(ib_connection: str, module_name: str, bsl_code: str,
                               synonym: str = "", server: bool = True, client: bool = False,
                               kill_sessions: bool = True) -> dict:
    """Async. Общий модуль ПРЯМО в основной конфигурации (не в расширении). По умолчанию чисто серверный."""
    jid = _spawn(_deploy_main_common_module, CFG, ib_connection, module_name, bsl_code,
                 synonym=synonym, server=server, client=client, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}


@mcp.tool()
def dump_extension(ib_connection: str, ext_name: str) -> dict:
    """Чтение, синхронно. Свежий DumpConfigToFiles расширения → локальный путь (runtime/ext_src/<ext>) для Read/Grep. Тот же каталог использует sync_extension_files."""
    return _dump_extension(CFG, ib_connection, ext_name)


@mcp.tool()
def deploy_extension_from_files(ib_connection: str, ext_root: str, ext_name: str,
                                 kill_sessions: bool = True) -> dict:
    """Async. Залить ЦЕЛЫЙ дамп расширения с диска (ext_root — корень с Configuration.xml). Может упасть на рассинхроне формата нетронутых файлов; для точечных правок — sync_extension_files."""
    jid = _spawn(_deploy_extension_from_files, CFG, ib_connection, ext_root, ext_name,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~30-180с (весь дамп расширения — небыстро)"}


@mcp.tool()
def sync_extension_files(ib_connection: str, ext_name: str, writes: dict = None,
                          deletes: list = None, ensure_registered: list = None,
                          kill_sessions: bool = True) -> dict:
    """Async. Точечная синка файлов в существующем расширении: dump → правки → load → update.
    writes — {путь_в_дампе: содержимое}, напр. 'DataProcessors/X/Ext/ObjectModule.bsl'. XML-регистрацию нового общего модуля не создаёт (→ deploy_module).
    deletes — [путь,...]; для 'CommonModules/Имя' также убирает тег из Configuration.xml, для других видов — tag_warnings.
    ensure_registered — [{kind, name}] — идемпотентно добавить <Kind>Имя</Kind> в ChildObjects (нужно для нового top-level объекта)."""
    jid = _spawn(_sync_extension_files, CFG, ib_connection, ext_name, writes=writes,
                 deletes=deletes, ensure_registered=ensure_registered, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}


@mcp.tool()
def adopt_object(ib_connection: str, ext_name: str, kind: str, name: str,
                  extended_configuration_object: str, kill_sessions: bool = True) -> dict:
    """Async. «Пустое» заимствование объекта базовой конфигурации расширением (Adopted, без кода). kind только 'Document'|'Catalog'. name — имя в базовой конфигурации; extended_configuration_object — её uuid объекта (dump_main_config → атрибут uuid корневого тега <Имя>.xml). Расширяющий код в модуль объекта не поддержан."""
    jid = _spawn(_adopt_object, CFG, ib_connection, ext_name, kind, name,
                 extended_configuration_object, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с"}


@mcp.tool()
def adopt_form(ib_connection: str, ext_name: str, kind: str, doc_name: str,
                doc_extended_configuration_object: str, form_name: str,
                form_extended_configuration_object: str, base_form_body: str, bsl_code: str,
                command_overrides: list = None, kill_sessions: bool = True) -> dict:
    """Async. Заимствовать ФОРМУ объекта базовой конфигурации с перехватом методов: помечает объект Adopted (если ещё нет), пишет дескриптор формы, Ext/Form.xml и Ext/Form/Module.bsl.
    kind 'Document'|'Catalog'; doc_name/form_name — как в базовой конфигурации; *_extended_configuration_object — uuid документа и формы там.
    base_form_body — сырое содержимое базовой Form.xml между <Form> и </Form> (из dump_main_config); явные <DataPath> убрать, иначе диалог «Неверный путь к данным».
    command_overrides — [{name, call_type:'Before'|'After', handler}] — Action СУЩЕСТВУЮЩЕЙ команды; новую не добавляет.
    bsl_code — полный Module.bsl с &Перед/&После/&Вместо/&ИзменениеИКонтроль("Имя"); в &Вместо оригинал — ПродолжитьВызов(...)."""
    jid = _spawn(_adopt_form, CFG, ib_connection, ext_name, kind, doc_name,
                 doc_extended_configuration_object, form_name, form_extended_configuration_object,
                 base_form_body, bsl_code, command_overrides=command_overrides,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с"}


@mcp.tool()
def deploy_http_service(ib_connection: str, ext_name: str, name: str, synonym: str,
                         root_url: str, url_templates: list, bsl_code: str,
                         reuse_sessions: str = "AutoUse", session_max_age: int = 20,
                         kill_sessions: bool = True) -> dict:
    """Async. Создать/ЦЕЛИКОМ перезаписать HTTPService в расширении (/hs/{root_url}/...).
    url_templates — [{name, template:'/путь', methods:[{name, http_method, handler}]}] — полная замена: при обновлении передавать весь список.
    bsl_code — полный Ext/Module.bsl: «Функция <handler>(Запрос) Экспорт»."""
    jid = _spawn(_deploy_http_service, CFG, ib_connection, ext_name, name, synonym,
                 root_url, url_templates, bsl_code, reuse_sessions=reuse_sessions,
                 session_max_age=session_max_age, kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-90с (тяжёлая конфигурация — дольше)"}
