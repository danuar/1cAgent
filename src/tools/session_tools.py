#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сессии/процессы 1С и подключение расширений: list_sessions/kill_sessions/start_runner/list_extensions/list_ib_users/attach_extension."""
from mcp.server.fastmcp import Image

from src.tools.core import mcp, CFG, _clip, MAX_OUTPUT, _spawn
from src.onec.glue import Real1CRunner
from src.onec.extensions import attach_extension as _attach_extension, LIST_EXTENSIONS_BSL
from src.onec.extension_deploy import LIST_IB_USERS_BSL
from src.onec.sessions import (list_1c_processes as _list_processes,
                      find_matching_processes as _find_processes,
                      kill_matching_processes as _kill_processes)

from src.onec.runner_launch import launch_runner as _launch_runner, restart_runner as _restart_runner
from src.core.screenshot_1c import (find_1c_window as _find_1c_window, capture_window as _capture_window,
                                     ocr_text as _ocr_text)


@mcp.tool()
def list_sessions(ib_connection: str = "") -> dict:
    """Процессы 1cv8*.exe (PID/командная строка). С ib_connection — только этой базы; без — все."""
    if ib_connection:
        return {"processes": _find_processes(ib_connection)}
    return {"processes": _list_processes()}


@mcp.tool()
def kill_sessions(ib_connection: str) -> dict:
    """Force-kill сессий базы ib_connection (нужно перед UpdateDBCfg на файловой базе). Интерактивные сессии человека не трогает → skipped_interactive; зависшие свои DESIGNER-вызовы убивает."""
    return _kill_processes(ib_connection)


@mcp.tool()
def attach_extension(ib_connection: str, cfe_path: str = "", ext_name: str = "",
                      kill_sessions: bool = True) -> dict:
    """Подключить/обновить .cfe в базу (LoadCfg -Extension + UpdateDBCfg). По умолчанию YaXUnit. kill_sessions=True — сначала гасит сессии базы (раннер тоже). Безопасный режим/защиту от опасных действий снимать руками."""
    return _attach_extension(CFG, ib_connection, cfe_path or CFG["yaxunit_cfe"],
                              ext_name or CFG["yaxunit_ext"], kill_sessions=kill_sessions)


@mcp.tool()
def start_runner(ib_connection: str) -> dict:
    """Открыть форму-раннер в базе (ENTERPRISE /Execute), не ждёт. Нужен после kill_sessions/deploy_*. Проверка — warmup() через 5-15с. Обычно удобнее restart_runner."""
    return _launch_runner(CFG, ib_connection)


@mcp.tool()
def restart_runner(ib_connection: str, retries: int = 2) -> dict:
    """Async. kill_sessions + start_runner + ожидание готовности; retries — повторы. → {ok, attempts, kill_report, warmup}."""
    jid = _spawn(_restart_runner, CFG, ib_connection, retries=retries)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id, wait_seconds=30) — обычно ~10-30с, до ~100с при повторной попытке"}


@mcp.tool()
def screenshot_1c_window(ib_connection: str = "", force_image: bool = False):
    """Чтение. Видимое окно 1cv8.exe (модальные диалоги, которых нет в логах). → {found, pid, title, ocr_text?}; картинка только если OCR пуст или force_image=True. found=false ≠ падение."""
    procs = _find_processes(ib_connection) if ib_connection else _list_processes()
    pids = {p["ProcessId"] for p in procs if p.get("ProcessId")}
    if not pids:
        reason = ("нет процессов 1cv8.exe для этого ib_connection — list_sessions(ib_connection) пуст"
                   if ib_connection else "нет ни одного процесса 1cv8.exe — list_sessions() пуст")
        return {"found": False, "reason": reason}

    win = _find_1c_window(pids)
    if win is None:
        return {"found": False, "reason": "видимых окон не найдено (не отрисовалось ещё, headless-сессия без GUI, или уже закрылось)"}

    png = _capture_window(win["hwnd"])
    if png is None:
        return {"found": True, "pid": win["pid"], "title": win["title"],
                "reason": "окно найдено, но захват (PrintWindow) не удался — попробуйте ещё раз"}

    result = {"found": True, "pid": win["pid"], "title": win["title"]}
    text = _ocr_text(CFG, png)
    if text:
        result["ocr_text"] = text
        if not force_image:
            return result
    return [Image(data=png, format="png"), result]


@mcp.tool()
def list_extensions() -> dict:
    """Чтение (группа A). Подключённые расширения: имя/активно/безопасный режим."""
    status, errors, output = Real1CRunner(CFG)(LIST_EXTENSIONS_BSL)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", "output": output}


@mcp.tool()
def list_ib_users() -> dict:
    """Чтение (группа A). Логины ИБ (Имя/ПолноеИмя) — для точного Usr= в ib_connection."""
    status, errors, output = Real1CRunner(CFG)(LIST_IB_USERS_BSL)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", "output": output}
