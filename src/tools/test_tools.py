#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон тестов YAxUnit: run_tests."""
from src.tools.core import mcp, CFG, _spawn
from src.onec.yaxunit_runner import run_tests as _run_tests


@mcp.tool()
def run_tests(ib_connection: str, extensions: list = None, modules: list = None,
              suites: list = None, tags: list = None) -> dict:
    """
    АСИНХРОННО — см. deploy_module про job_id/job_status и почему (на тяжёлых
    конфигурациях запуск ENTERPRISE + прогон тестов может занять несколько минут).

    Запускает тесты YAxUnit через ENTERPRISE /C RunUnitTests в УКАЗАННОЙ базе.
    Результат (через job_status): status: "ok" | "test_failed" | "error".
    "test_failed" -> эскалация к Клоду (не к 7B-фиксеру): провал бизнес-логики
    нужно осмыслить, а не синтаксически починить. Без фильтров гоняет ВСЕ тесты
    всех расширений — обычно нужнее extensions=["YAXUNIT"] или modules=[...].
    """
    jid = _spawn(_run_tests, CFG, ib_connection, extensions=extensions, modules=modules,
                 suites=suites, tags=tags)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-300с в зависимости от объёма тестов"}
