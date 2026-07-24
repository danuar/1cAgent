#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#9 в миниатюре: подключение ОДНОГО готового расширения (.cfe) к УКАЗАННОЙ базе
через чистый DESIGNER CLI — без EDT, без OneScript. Нужно для установки YAxUnit
(см. HANDOFF.md #6). Тот же примитив (LoadCfg/UpdateDBCfg с -Extension) позже
переиспользует полный #9 (apply_config) для правки боевых модулей документов —
но здесь объём безопаснее: чужой готовый .cfe тестового движка, не наши правки.

ВАЖНО (набито вживую): база передаётся ЯВНО строкой подключения (ib_connection,
см. ib_connection.py) на каждый вызов, а НЕ берётся из CFG. Изначально код брал
CFG["compiler_db"] — это оказалась ПУСТАЯ база, которая используется только для
сборки .epf (см. glue.Real1CRunner._build), а не тестовая/рабочая база с реальными
Документами/Справочниками, где живёт сессия формы-раннера. Расширение, подключенное
не туда, просто не видно в run_module/describe_metadata — база другая физически.

Синтаксис (два шага, как обновление обычной конфигурации, но с -Extension):
    1cv8.exe DESIGNER <connection> /LoadCfg <file.cfe> -Extension <Имя> /Out <log>
    1cv8.exe DESIGNER <connection> /UpdateDBCfg -Extension <Имя> /Out <log>
Если расширения с таким именем ещё нет — LoadCfg создаёт его сам.

ВАЖНО: после загрузки расширения YAxUnit требует руками (или отдельным вызовом,
TODO) снять "Безопасный режим" и "Защита от опасных действий" — иначе тесты не
смогут делать активные действия в базе. См. доки YAxUnit, раздел "Установка".

ВАЖНО: изменение конфигурации через DESIGNER, пока сессия 1С:Предприятия уже
открыта (форма-раннер), не подхватывается этой сессией автоматически — нужен
её перезапуск, чтобы новое расширение стало видно через run_module/list_extensions.
"""
import subprocess
from pathlib import Path

from src.core.ib_connection import cli_connection_str
from src.onec.sessions import kill_matching_processes
from src.core.designer_log import read_designer_log


def attach_extension(cfg: dict, ib_connection: str, cfe_path: str, ext_name: str,
                      timeout: int = 120, kill_sessions: bool = True) -> dict:
    """
    Подключает/обновляет расширение из .cfe-файла в БАЗЕ ib_connection. Режим B.
    kill_sessions=True (по умолчанию) — перед UpdateDBCfg точечно завершает
    процессы 1cv8*.exe, подключённые именно к этой базе (см. sessions.py): для
    файловой базы UpdateDBCfg требует монопольный доступ, а штатный платформенный
    «ЗавершитьРаботуПользователей» зависит от подсистемы БСП в самой конфигурации,
    которой в лёгких/учебных базах обычно нет.
    """
    if not Path(cfe_path).exists():
        return {"ok": False, "step": "precheck",
                "reason": f"файл не найден: {cfe_path} — скачайте releases/latest"}
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "step": "connection", "reason": str(e)}

    kill_report = None
    if kill_sessions:
        kill_report = kill_matching_processes(ib_connection)

    log_dir = Path(cfg["runtime_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_load = log_dir / f"ext_{ext_name}_load.log"
    log_update = log_dir / f"ext_{ext_name}_update.log"

    cmd_load = (f'"{cfg["path_1c"]}" DESIGNER {conn} '
                f'/LoadCfg "{cfe_path}" -Extension {ext_name} /Out "{log_load}"')
    cmd_update = (f'"{cfg["path_1c"]}" DESIGNER {conn} '
                  f'/UpdateDBCfg -Extension {ext_name} /Out "{log_update}"')

    r1 = subprocess.run(cmd_load, shell=True, timeout=timeout)
    out1 = read_designer_log(log_load)
    if r1.returncode != 0:
        return {"ok": False, "step": "LoadCfg", "returncode": r1.returncode, "log": out1[-1000:],
                "kill_report": kill_report}

    r2 = subprocess.run(cmd_update, shell=True, timeout=timeout)
    out2 = read_designer_log(log_update)
    if r2.returncode != 0:
        return {"ok": False, "step": "UpdateDBCfg", "returncode": r2.returncode, "log": out2[-1000:],
                "kill_report": kill_report}

    return {"ok": True, "load_log": out1[-500:], "update_log": out2[-500:], "kill_report": kill_report}


# BSL-снипет для проверки подключённых расширений через run_module (проверено вживую).
LIST_EXTENSIONS_BSL = (
    "Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт\n"
    "\tРасширения = РасширенияКонфигурации.Получить();\n"
    '\tЛогВыполнения = ЛогВыполнения + "Кол-во расширений: " + Строка(Расширения.Количество()) + Символы.ПС;\n'
    "\tДля Каждого Р Из Расширения Цикл\n"
    '\t\tЛогВыполнения = ЛогВыполнения + Р.Имя + ": актив=" + Строка(Р.Активно)'
    ' + " безопасн=" + Строка(Р.БезопасныйРежим) + Символы.ПС;\n'
    "\tКонецЦикла;\n"
    '\tЛогВыполнения = ЛогВыполнения + "ГОТОВО";\n'
    "КонецПроцедуры\n"
)
