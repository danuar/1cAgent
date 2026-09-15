#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал регистрации 1С: check_event_log."""
from pathlib import Path

from src.tools.core import mcp, CFG, MAX_OUTPUT, _clip
from src.onec.glue import Real1CRunner
from src.onec.event_log import build_export_bsl as _build_event_log_bsl, parse_export as _parse_event_log


@mcp.tool()
def check_event_log(minutes_back: int = 30, limit: int = 30, user: str = "") -> dict:
    """Чтение (группа A). Ошибки/предупреждения Журнала регистрации за minutes_back минут, последние limit. user — логин ИБ для отсечения шума (без него — все). Сюда попадает то, что 1С показывает всплывающими окнами, а run_module/deploy_* в вывод не кладут."""
    export_path = str(Path(CFG["runtime_dir"]) / "logs" / "eventlog_export.xml")
    status, errors, output = Real1CRunner(CFG)(_build_event_log_bsl(export_path, minutes_back, user=user or None))
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    events = _parse_event_log(export_path, limit=limit)
    return {"status": "ok", "count": len(events), "events": events}
