#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал регистрации 1С: check_event_log."""
from pathlib import Path

from src.tools.core import mcp, CFG, MAX_OUTPUT, _clip
from src.onec.glue import Real1CRunner
from src.onec.event_log import build_export_bsl as _build_event_log_bsl, parse_export as _parse_event_log


@mcp.tool()
def check_event_log(minutes_back: int = 30, limit: int = 30, user: str = "") -> dict:
    """
    Группа A (нужна живая форма-раннер, см. start_runner). Только чтение.
    Читает Журнал регистрации 1С — ошибки/предупреждения за последние
    minutes_back минут (что реально произошло в БД: критичные сообщения
    расширений типа "уже существует объект с именем...", ошибки инициализации
    модуля, ошибки фоновых заданий — то, что человек видит во всплывающих
    окнах 1С:Предприятия, а run_module/deploy_module в свой вывод НЕ кладут).
    Возвращает ПОСЛЕДНИЕ limit событий (самые свежие, обычно самые релевантные).

    user — логин ИБ (как в Usr= строки подключения, например "Администратор
    (ОрловАВ)") — отсекает шум от других пользователей/фоновых заданий (у тех
    UserName вообще пустой). Проверено вживую: без фильтра 4476 событий за час,
    с фильтром по одному логину — 972. Без user — события ВСЕХ пользователей.

    Технически: BSL-снипет только ПИШЕТ выгрузку через ВыгрузитьЖурналРегистрации
    в файл внутри runtime_dir проекта (сам run_module работает в вынужденном
    безопасном режиме — читать файл обратно из BSL нельзя, "Установлен безопасный
    режим"), а разбирает XML уже этот Python-код, вне песочницы 1С.
    """
    export_path = str(Path(CFG["runtime_dir"]) / "logs" / "eventlog_export.xml")
    status, errors, output = Real1CRunner(CFG)(_build_event_log_bsl(export_path, minutes_back, user=user or None))
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    events = _parse_event_log(export_path, limit=limit)
    return {"status": "ok", "count": len(events), "events": events}
