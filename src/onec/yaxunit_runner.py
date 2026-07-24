#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#6 (часть 2): запуск тестов YAxUnit через ENTERPRISE /C RunUnitTests — БЕЗ
OneScript/vanessa-runner, чистый CLI (тот же subprocess-подход, что и остальной
раннер в этом проекте).

Код собран строго по официальной документации bia-technologies/yaxunit
(страницы getting-started/run и run/configuration).

ВАЖНО: база передаётся ЯВНО строкой подключения (ib_connection, см.
ib_connection.py) на каждый вызов, а НЕ берётся из CFG — см. пояснение в
extensions.py (CFG["compiler_db"] — это отдельная пустая база для сборки .epf,
а не тестовая/рабочая база с подключенным YAxUnit).

Командная строка (см. доки):
    "<1cv8.exe>" ENTERPRISE <connection> /C"RunUnitTests=<путь_к_config.json>"
config.json — основные поля (см. доки run/configuration):
    reportFormat: "jUnit" (значение по умолчанию) — стандартный XML, парсим stdlib.
    reportPath, closeAfterTests, showReport, exitCode, filter{extensions/modules/suites/tags}
"""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from src.core.ib_connection import cli_connection_str
from src.core.designer_log import read_designer_log


def _build_run_config(cfg: dict, extensions=None, modules=None, suites=None, tags=None) -> dict:
    filt = {}
    if extensions:
        filt["extensions"] = extensions
    if modules:
        filt["modules"] = modules
    if suites:
        filt["suites"] = suites
    if tags:
        filt["tags"] = tags
    run_cfg = {
        "reportFormat": "jUnit",
        "reportPath": str(Path(cfg["tests_report"]).with_suffix(".xml")),
        "closeAfterTests": True,
        "showReport": False,
        "exitCode": cfg["tests_exit"],
    }
    if filt:
        run_cfg["filter"] = filt
    return run_cfg


def run_tests(cfg: dict, ib_connection: str, extensions=None, modules=None, suites=None,
              tags=None, timeout: int = 600) -> dict:
    """
    Запускает YAxUnit в базе ib_connection, возвращает
    {"status": "ok"|"test_failed"|"error", "total", "failures", "errors", "cases": [...]}.
    Без фильтров гоняет ВСЕ тесты всех подключённых расширений — сузьте через
    extensions=["YAXUNIT"] / modules=[...] для скорости и целевого прогона.
    status="test_failed" — сигнал глушить к Клоду (см. glue.heal()), а НЕ к 7B-фиксеру:
    провал бизнес-логики требует рассуждения, а не синтаксического патча.
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"status": "error", "reason": str(e)}

    run_cfg = _build_run_config(cfg, extensions, modules, suites, tags)
    config_path = Path(cfg["tests_report"]).with_suffix(".config.json")
    config_path.write_text(json.dumps(run_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = Path(run_cfg["reportPath"])
    exit_path = Path(cfg["tests_exit"])
    for p in (report_path, exit_path):
        p.unlink(missing_ok=True)

    cmd = f'"{cfg["path_1c"]}" ENTERPRISE {conn} /C"RunUnitTests={config_path}"'
    try:
        subprocess.run(cmd, shell=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": f"таймаут {timeout}с (проверьте closeAfterTests)"}

    if not report_path.exists():
        hint = read_designer_log(exit_path).strip()
        return {"status": "error", "reason": f"нет jUnit-отчёта; exitCode-файл: {hint!r}"}

    return _parse_junit(report_path)


def _parse_junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = failures = errors = 0
    cases = []
    for suite in suites:
        total += int(suite.get("tests", 0) or 0)
        failures += int(suite.get("failures", 0) or 0)
        errors += int(suite.get("errors", 0) or 0)
        for tc in suite.findall("testcase"):
            entry = {"name": tc.get("name"), "classname": tc.get("classname"), "status": "passed"}
            fail, err = tc.find("failure"), tc.find("error")
            if fail is not None:
                entry["status"] = "failed"
                entry["message"] = fail.get("message") or (fail.text or "").strip()[:500]
            elif err is not None:
                entry["status"] = "error"
                entry["message"] = err.get("message") or (err.text or "").strip()[:500]
            cases.append(entry)
    status = "ok" if (failures == 0 and errors == 0) else "test_failed"
    failed_cases = [c for c in cases if c["status"] != "passed"]
    return {"status": status, "total": total, "failures": failures, "errors": errors,
            "cases": failed_cases if failed_cases else cases[:5]}
