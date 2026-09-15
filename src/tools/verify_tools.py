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
    """Async. Пайплайн: lint(*.bsl из writes) → sync_extension_files(writes, deletes) → run_tests(test_extensions или [ext_name], test_modules) → start_runner → check_event_log(event_log_minutes, event_log_user: 'auto'=Usr из ib_connection, ''=все). Без writes/deletes — только проверка. → {stages{lint,deploy,tests,runner_ready,event_log}, verdict: ok|lint_failed|deploy_failed|test_failed|needs_review}."""
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
    """Async. То же для основной конфигурации: деплой через sync_main_config_files(writes, deletes, ensure_registered). Результат как у verify_extension."""
    jid = _spawn(_verify_main_config, CFG, ib_connection, writes=writes, deletes=deletes,
                 ensure_registered=ensure_registered,
                 test_extensions=test_extensions, test_modules=test_modules,
                 event_log_minutes=event_log_minutes, event_log_user=event_log_user,
                 kill_sessions=kill_sessions)
    return {"job_id": jid, "status": "running",
            "hint": "job_status(job_id, wait_seconds=55) — весь пайплайн может занять несколько минут"}
