#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Составной пайплайн: verify_extension/verify_main_config."""
from src.tools.core import mcp, CFG, _spawn
from src.onec.verify import verify_extension as _verify_extension, verify_main_config as _verify_main_config


@mcp.tool()
def verify_extension(ib_connection: str, ext_name: str, writes: dict = None, deletes: list = None,
                      test_extensions: list = None, test_modules: list = None,
                      event_log_minutes: int = 15, event_log_user: str = "auto",
                      kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status, #27) — составной пайплайн вместо ручной склейки
    lint_module -> sync_extension_files -> run_tests -> start_runner -> check_event_log
    (именно так агент проверял каждую правку всю сессию тестирования vkr_). Один
    вызов — один вердикт.

    Шаги (см. verify.py):
      1. lint — статически проверяет КАЖДЫЙ *.bsl из writes ДО деплоя (дёшево).
         Реальная Error-диагностика останавливает пайплайн -> verdict="lint_failed",
         деплой не запускается вовсе.
      2. deploy — sync_extension_files(writes, deletes), если что-то передано.
         Без writes/deletes шаг пропускается (режим "просто проверить текущее
         состояние живой базы", ничего не меняя). Ошибка -> verdict="deploy_failed".
      3. tests — run_tests(extensions=test_extensions или [ext_name], test_modules).
         СВОЙ отдельный ENTERPRISE-сеанс, закрывается сам по завершении.
      4. runner — поднимает форму-раннер ТОЛЬКО ТЕПЕРЬ (после тестов, НЕ параллельно
         с ними — иначе на базу одновременно откроются ДВЕ сессии ENTERPRISE, что
         может не влезть в лицензию с малым лимитом сеансов, см. #28), и только
         если для этой базы ещё нет живой (по /Execute в командной строке).
      5. event_log — check_event_log за event_log_minutes, отфильтрованный по
         event_log_user ("auto" по умолчанию — берёт Usr= из ib_connection, режет
         шум от фоновых заданий/других пользователей; "" — без фильтра, все;
         конкретная строка — свой логин). Нужен живой раннер из шага 4; если он
         так и не поднялся за 3 попытки — шаг помечен skipped, остальной отчёт
         всё равно есть.

    Результат (через job_status): {"stages": {lint, deploy?, tests, runner_ready,
    event_log}, "verdict": "ok"|"lint_failed"|"deploy_failed"|"test_failed"|"needs_review"}.
    "test_failed"/"needs_review" -> смотри stages.tests и stages.event_log вместе —
    иногда причина падения теста видна именно в журнале регистрации, а не в jUnit.
    """
    jid = _spawn(_verify_extension, CFG, ib_connection, ext_name, writes=writes, deletes=deletes,
                 test_extensions=test_extensions, test_modules=test_modules,
                 event_log_minutes=event_log_minutes, event_log_user=event_log_user,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running",
            "hint": "job_status(job_id, wait_seconds=55) — весь пайплайн может занять несколько минут"}


@mcp.tool()
def verify_main_config(ib_connection: str, writes: dict = None, deletes: list = None,
                        ensure_registered: list = None,
                        test_extensions: list = None, test_modules: list = None,
                        event_log_minutes: int = 15, event_log_user: str = "auto",
                        kill_sessions: bool = True) -> dict:
    """
    АСИНХРОННО (job_id/job_status) — составной пайплайн для ОСНОВНОЙ
    конфигурации, аналог verify_extension (см. его подробный docstring про
    порядок шагов lint -> deploy -> tests -> runner -> event_log и про
    event_log_user). ЕДИНСТВЕННОЕ отличие: деплой через sync_main_config_files
    (БЕЗ -Extension, с ensure_registered для регистрации НОВЫХ объектов) —
    нет ext_name, основная конфигурация одна на базу.

    writes/deletes/ensure_registered — см. sync_main_config_files. Без них шаг
    deploy пропускается (режим "просто проверить текущее состояние базы").
    test_extensions/test_modules — передаются в run_tests напрямую, оба None
    означает "все подключённые тесты".

    Результат (через job_status): {"stages": {lint, deploy?, tests,
    runner_ready, event_log}, "verdict": "ok"|"lint_failed"|"deploy_failed"|
    "test_failed"|"needs_review"}.
    """
    jid = _spawn(_verify_main_config, CFG, ib_connection, writes=writes, deletes=deletes,
                 ensure_registered=ensure_registered,
                 test_extensions=test_extensions, test_modules=test_modules,
                 event_log_minutes=event_log_minutes, event_log_user=event_log_user,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running",
            "hint": "job_status(job_id, wait_seconds=55) — весь пайплайн может занять несколько минут"}
