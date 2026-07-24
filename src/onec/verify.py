#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Составной инструмент: то, что за всю сессию тестирования vkr_ агент вручную
склеивал сам, шаг за шагом, каждый раз заново решая "готов ли раннер",
"а если ошибка — что дальше". verify_extension(...) делает всё одним вызовом:

    1. lint  — статически проверяет КАЖДЫЙ *.bsl-файл из writes ДО того, как
       что-либо трогать в живой базе (дёшево, ~1-3с/модуль). Реальная
       Error-диагностика (см. tools/bsl-language-server.json — там уже
       понижены заведомо-неблокирующие находки типа MissingCodeTryCatchEx)
       останавливает пайплайн ДО деплоя — не тратим время на заведомо
       нерабочий код.
    2. deploy — sync_extension_files(writes, deletes), если что-то передано.
       Если ничего не передано — пропускается (режим "просто проверить
       текущее состояние живой базы", ничего не меняя).
    3. runner — поднимает форму-раннер, ЕСЛИ она ещё не поднята для этой базы
       (проверка по CommandLine, см. sessions.py) — нужна для шага 5.
    4. tests — run_tests по extensions/modules.
    5. event_log — check_event_log за event_log_minutes, если раннер удалось
       поднять; иначе шаг помечается skipped, остальной отчёт всё равно есть.

Возвращает ОДИН словарь {"stages": {...}, "verdict": "ok"|"lint_failed"|
"deploy_failed"|"test_failed"|"needs_review"} — не нужно вручную гонять 4
инструмента и решать, что делать при ошибке на полпути.
"""
from pathlib import Path

from src.onec.bsl_ls import lint as bsl_lint
from src.onec.extension_deploy import sync_extension_files as _sync_extension_files
from src.onec.metadata_deploy import sync_main_config_files as _sync_main_config_files
from src.onec.runner_launch import launch_runner
from src.onec.sessions import find_matching_processes
from src.onec.glue import Real1CRunner
from src.onec.yaxunit_runner import run_tests as _run_tests
from src.onec.event_log import build_export_bsl, parse_export
from src.core.ib_connection import parse_connection_string

_TRIVIAL_BSL = ('Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт\n'
                '\tЛогВыполнения = "ГОТОВО";\n'
                'КонецПроцедуры\n')


def _runner_already_up(ib_connection: str) -> bool:
    """Наш раннер узнаётся по маркеру /Execute в командной строке (см. sessions._is_automation_process)."""
    return any("/execute" in (p.get("CommandLine", "") or "").lower()
               for p in find_matching_processes(ib_connection))


def verify_extension(cfg: dict, ib_connection: str, ext_name: str,
                      writes: dict = None, deletes: list = None,
                      test_extensions: list = None, test_modules: list = None,
                      event_log_minutes: int = 15, event_log_user: str = "auto",
                      kill_sessions: bool = True) -> dict:
    """
    event_log_user: "auto" (по умолчанию) — берём Usr= из ib_connection (шум от
    других пользователей/фоновых заданий отсекается); "" — явно без фильтра
    (все пользователи); любая другая строка — конкретный логин.

    ПОРЯДОК ШАГОВ ВАЖЕН: tests ПЕРЕД runner+event_log, не наоборот. run_tests
    поднимает СВОЙ ENTERPRISE-сеанс независимо от нашей формы-раннера — если
    сначала поднять раннер (для event_log), а потом запускать тесты, на базу
    ОДНОВРЕМЕННО откроются ДВЕ сессии ENTERPRISE. На лицензиях с малым лимитом
    одновременных сеансов (например community/демо) это может не влезть —
    поэтому раннер поднимается ПОСЛЕ того, как тесты уже закрыли свою сессию.
    """
    writes = writes or {}
    deletes = deletes or []
    stages = {}

    # 1. lint — только *.bsl из writes, ДО деплоя
    lint_results = {}
    lint_blocked = False
    for path, content in writes.items():
        if path.endswith(".bsl"):
            r = bsl_lint(content, cfg.get("bsl_ls_jar", ""), java_exe=cfg.get("java_exe", "java"))
            lint_results[path] = r
            if r.get("ok") is False:  # None = гейт недоступен (нет jar/java) — не блокирует
                lint_blocked = True
    stages["lint"] = lint_results
    if lint_blocked:
        return {"stages": stages, "verdict": "lint_failed"}

    # 2. deploy — только если реально есть что деплоить
    if writes or deletes:
        deploy_result = _sync_extension_files(cfg, ib_connection, ext_name,
                                               writes=writes, deletes=deletes,
                                               kill_sessions=kill_sessions)
        stages["deploy"] = deploy_result
        if not deploy_result.get("ok"):
            return {"stages": stages, "verdict": "deploy_failed"}

    # 3. tests — СВОЙ отдельный ENTERPRISE-сеанс, закрывается сам по завершении
    test_result = _run_tests(cfg, ib_connection,
                              extensions=test_extensions or [ext_name],
                              modules=test_modules)
    stages["tests"] = test_result

    # 4. runner — поднять ТОЛЬКО ТЕПЕРЬ (после теста, не параллельно с ним),
    #    и только если ещё не поднят (не плодить параллельные сессии)
    runner_ready = _runner_already_up(ib_connection)
    if not runner_ready:
        launch_runner(cfg, ib_connection)
        for _ in range(3):  # каждая попытка сама ждёт до 50с внутри Real1CRunner._wait
            status, _errors, _output = Real1CRunner(cfg)(_TRIVIAL_BSL)
            if status == "ok":
                runner_ready = True
                break
    stages["runner_ready"] = runner_ready

    # 5. event_log — нужен живой раннер (шаг 4)
    if runner_ready:
        user = event_log_user
        if user == "auto":
            user = parse_connection_string(ib_connection).get("Usr") or None
        elif user == "":
            user = None
        export_path = str(Path(cfg["runtime_dir"]) / "logs" / "verify_eventlog_export.xml")
        status, errors, _output = Real1CRunner(cfg)(build_export_bsl(export_path, event_log_minutes, user=user))
        if status == "ok" and not errors:
            events = parse_export(export_path, limit=20)
            stages["event_log"] = {"status": "ok", "count": len(events), "events": events,
                                    "filtered_by_user": user}
        else:
            stages["event_log"] = {"status": status, "errors": errors[:5]}
    else:
        stages["event_log"] = {"status": "skipped", "reason": "раннер не поднялся за 3 попытки"}

    test_status = test_result.get("status")
    if test_status == "ok":
        verdict = "ok"
    elif test_status == "test_failed":
        verdict = "test_failed"
    else:
        verdict = "needs_review"

    return {"stages": stages, "verdict": verdict}


def verify_main_config(cfg: dict, ib_connection: str,
                        writes: dict = None, deletes: list = None, ensure_registered: list = None,
                        test_extensions: list = None, test_modules: list = None,
                        event_log_minutes: int = 15, event_log_user: str = "auto",
                        kill_sessions: bool = True) -> dict:
    """
    #50 (задача 7): составной пайплайн ДЛЯ ОСНОВНОЙ КОНФИГУРАЦИИ — аналог
    verify_extension (см. его docstring за полным объяснением порядка шагов и
    event_log_user), ЕДИНСТВЕННОЕ отличие: deploy-шаг через
    sync_main_config_files вместо sync_extension_files (БЕЗ -Extension, с
    ensure_registered — см. sync_main_config_files/metadata_deploy.py) и нет
    ext_name (основная конфигурация одна на базу, в отличие от расширений).

    test_extensions/test_modules передаются в run_tests НАПРЯМУЮ без изменений
    (в отличие от verify_extension, где test_extensions по умолчанию = [ext_name])
    — оба None означает "все подключённые тесты"; сузьте сами при необходимости,
    например test_modules=["Тест_ОбщегоМодуля"] для общего модуля, созданного
    через deploy_main_common_module.
    """
    writes = writes or {}
    deletes = deletes or []
    stages = {}

    # 1. lint — только *.bsl из writes, ДО деплоя
    lint_results = {}
    lint_blocked = False
    for path, content in writes.items():
        if path.endswith(".bsl"):
            r = bsl_lint(content, cfg.get("bsl_ls_jar", ""), java_exe=cfg.get("java_exe", "java"))
            lint_results[path] = r
            if r.get("ok") is False:
                lint_blocked = True
    stages["lint"] = lint_results
    if lint_blocked:
        return {"stages": stages, "verdict": "lint_failed"}

    # 2. deploy — только если реально есть что деплоить
    if writes or deletes or ensure_registered:
        deploy_result = _sync_main_config_files(cfg, ib_connection, writes=writes, deletes=deletes,
                                                 ensure_registered=ensure_registered,
                                                 kill_sessions=kill_sessions)
        stages["deploy"] = deploy_result
        if not deploy_result.get("ok"):
            return {"stages": stages, "verdict": "deploy_failed"}

    # 3. tests — СВОЙ отдельный ENTERPRISE-сеанс, закрывается сам по завершении
    test_result = _run_tests(cfg, ib_connection, extensions=test_extensions, modules=test_modules)
    stages["tests"] = test_result

    # 4. runner — поднять ТОЛЬКО ТЕПЕРЬ (после теста, не параллельно с ним),
    #    и только если ещё не поднят (не плодить параллельные сессии)
    runner_ready = _runner_already_up(ib_connection)
    if not runner_ready:
        launch_runner(cfg, ib_connection)
        for _ in range(3):
            status, _errors, _output = Real1CRunner(cfg)(_TRIVIAL_BSL)
            if status == "ok":
                runner_ready = True
                break
    stages["runner_ready"] = runner_ready

    # 5. event_log — нужен живой раннер (шаг 4)
    if runner_ready:
        user = event_log_user
        if user == "auto":
            user = parse_connection_string(ib_connection).get("Usr") or None
        elif user == "":
            user = None
        export_path = str(Path(cfg["runtime_dir"]) / "logs" / "verify_main_eventlog_export.xml")
        status, errors, _output = Real1CRunner(cfg)(build_export_bsl(export_path, event_log_minutes, user=user))
        if status == "ok" and not errors:
            events = parse_export(export_path, limit=20)
            stages["event_log"] = {"status": "ok", "count": len(events), "events": events,
                                    "filtered_by_user": user}
        else:
            stages["event_log"] = {"status": status, "errors": errors[:5]}
    else:
        stages["event_log"] = {"status": "skipped", "reason": "раннер не поднялся за 3 попытки"}

    test_status = test_result.get("status")
    if test_status == "ok":
        verdict = "ok"
    elif test_status == "test_failed":
        verdict = "test_failed"
    else:
        verdict = "needs_review"

    return {"stages": stages, "verdict": verdict}
