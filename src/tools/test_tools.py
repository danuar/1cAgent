#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прогон тестов YAxUnit: run_tests."""
from src.tools.core import mcp, CFG, _spawn
from src.onec.yaxunit_runner import run_tests as _run_tests


@mcp.tool()
def run_tests(ib_connection: str, extensions: list = None, modules: list = None,
              suites: list = None, tags: list = None) -> dict:
    """Async. YaXUnit через ENTERPRISE /C RunUnitTests. Фильтры: extensions (обычно ['YAXUNIT']), modules, suites, tags; без них — все. → status ok|test_failed|error + разбор jUnit. test_failed — разбирать самому, не фиксеру."""
    jid = _spawn(_run_tests, CFG, ib_connection, extensions=extensions, modules=modules,
                 suites=suites, tags=tags)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id) через ~10-300с в зависимости от объёма тестов"}
