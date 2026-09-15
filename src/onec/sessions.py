#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Поиск/завершение процессов 1С:Предприятия, подключённых к КОНКРЕТНОЙ базе —
по командной строке процесса (Win32_Process.CommandLine содержит "/F<путь>"
или "/S<сервер>"+"<база>"), а НЕ вслепую по PID.

Почему не штатный платформенный «ЗавершитьРаботуПользователей»: этот механизм
завязан на подсистему БСП внутри САМОЙ конфигурации (см. документацию/статьи по
Effector Saver и подобным) — в лёгких/учебных конфигурациях без БСП её просто
нет. Поэтому для файловых баз единственный рабочий путь — ОС-уровень, но
ТОЧЕЧНО: сверяем командную строку процесса с разобранной ib_connection, вместо
того чтобы убивать все "1cv8*" подряд (что и предлагалось избежать).

#49 (задача 6, было ОГРАНИЧЕНИЕМ, теперь резолвится): если клиент запущен через
"Список информационных баз" (1С:Стартер) по сохранённому /IBName, в командной
строке может не быть сырого File=/Srvr= буквально — только "/IBName ИмяИзСписка".
Решение: /IBName резолвится через ibases.v8i (файл списка баз 1С:Стартер,
%APPDATA%\\1C\\<профиль>\\ibases.v8i — ПОДТВЕРЖДЕНО реальным файлом на машине
пользователя: UTF-8 с BOM, INI-подобный формат "[Имя]\\nConnect=File="...";\\n...").
Профилей может быть НЕСКОЛЬКО (найдено вживую — 1CEStart и 1CEStartt на одной
машине), читаются ВСЕ. См. _load_ibase_registry/_matches ниже.

Требует Windows (использует powershell + Win32_Process, taskkill).
"""
import json
import os
import re
import subprocess
from pathlib import Path

from src.core.ib_connection import parse_connection_string

_IBNAME_RE = re.compile(r'/IBName\s*"([^"]+)"|/IBName\s+(\S+)', re.IGNORECASE)


def _run_ps(cmd: str, timeout: int = 20) -> str:
    """
    #56 (найдено вживую): БЕЗ text=True — тот декодирует вывод через locale-
    кодировку Python (на этой машине это НЕ то, чем PowerShell реально пишет
    перенаправленный/захваченный stdout). PowerShell 5.1 пишет
    перенаправленный stdout в OEM-кодовой странице консоли (cp866 на этой
    машине), НЕ в ANSI (cp1251) и НЕ в UTF-8 — с text=True кириллица в
    CommandLine (например реальное имя базы после /IBName) превращалась в
    мусор, из-за чего _IBNAME_RE находил заведомо нерезолвящееся "имя".
    Захватываем СЫРЫЕ байты и декодируем ЯВНО как cp866 (подтверждено
    вживую: только этот вариант из cp1251/cp866/utf-8/utf-16 дал корректную
    строку "Информационная база" при сравнении, не визуально на глаз).
    """
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", cmd],
        capture_output=True, timeout=timeout,
    )
    return r.stdout.decode("cp866", errors="replace")


def list_1c_processes() -> list:
    """Все 1cv8*.exe процессы с PID/именем/командной строкой — для просмотра глазами."""
    out = _run_ps(
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '1cv8*' } "
        "| Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    ).strip()
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def _ibase_list_files() -> list:
    """Все ibases.v8i из профилей 1С:Стартер (%APPDATA%\\1C\\*\\ibases.v8i) —
    профилей может быть НЕСКОЛЬКО (см. модуль docstring), читаем ВСЕ."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    return list(Path(appdata, "1C").glob("*/ibases.v8i"))


def _load_ibase_registry() -> dict:
    """
    {имя_базы_из_квадратных_скобок (lower): [parsed_connection_dict, ...]},
    собранный из ВСЕХ найденных ibases.v8i. Значение — СПИСОК (не одиночный
    словарь) — найдено вживую (#56): на машине пользователя ДВА профиля
    1С:Стартер (1CEStart/1CEStartt), и в ОБОИХ может быть база с ОДИНАКОВЫМ
    отображаемым именем ("Информационная база"), но указывающая на РАЗНЫЕ
    реальные пути — если хранить одно значение на имя, второй профиль молча
    перезаписывает первый, и матчинг резолвит /IBName в СОВЕРШЕННО ДРУГУЮ
    базу, чем реально запущена (воспроизведено: имя резолвилось в InfoBase22,
    хотя пользователь открыл InfoBase24 — правильная запись была в первом
    прочитанном профиле, вторым перезаписана). Список позволяет проверять
    совпадение С ЛЮБЫМ из вариантов вместо одного произвольно "выигравшего".

    Секция без Connect= пропускается (не должно случаться, но не валим весь
    разбор из-за одной кривой записи). Best-effort — отсутствие/ошибка чтения
    файла молча даёт пустой словарь (деградация до старого поведения матчинга
    по сырой командной строке, не хуже).
    """
    registry = {}
    for path in _ibase_list_files():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        name = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                name = line[1:-1]
            elif line.startswith("Connect=") and name:
                registry.setdefault(name.lower(), []).append(parse_connection_string(line[len("Connect="):]))
    return registry


def _ws_url(parsed: dict) -> str:
    """ws-адрес из разобранного подключения (ключ ws/WS/Ws), в нижнем регистре."""
    return (parsed.get("ws") or parsed.get("WS") or parsed.get("Ws") or "").lower().rstrip("/")


def _connection_matches(parsed_a: dict, parsed_b: dict) -> bool:
    """Совпадают ли два разобранных connection dict по File ИЛИ Srvr+Ref (без учёта регистра)."""
    if parsed_a.get("File") and parsed_b.get("File"):
        return parsed_a["File"].lower() == parsed_b["File"].lower()
    if parsed_a.get("Srvr") and parsed_a.get("Ref") and parsed_b.get("Srvr") and parsed_b.get("Ref"):
        return (parsed_a["Srvr"].lower() == parsed_b["Srvr"].lower()
                and parsed_a["Ref"].lower() == parsed_b["Ref"].lower())
    if _ws_url(parsed_a) and _ws_url(parsed_b):
        return _ws_url(parsed_a) == _ws_url(parsed_b)
    return False


def _matches(cmdline: str, parsed: dict, ibase_registry: dict = None) -> bool:
    cmdline_low = (cmdline or "").lower()
    if parsed.get("File") and parsed["File"].lower() in cmdline_low:
        return True
    if (parsed.get("Srvr") and parsed.get("Ref")
            and parsed["Srvr"].lower() in cmdline_low and parsed["Ref"].lower() in cmdline_low):
        return True
    if _ws_url(parsed) and _ws_url(parsed) in cmdline_low:
        return True

    # #49: запущено через "Список информационных баз" по /IBName — сырого
    # File=/Srvr= в командной строке может не быть, резолвим имя через
    # ibases.v8i (ibase_registry, см. _load_ibase_registry) и сверяем УЖЕ
    # РАЗОБРАННОЕ подключение, а не подстроку.
    if ibase_registry:
        m = _IBNAME_RE.search(cmdline or "")
        if m:
            ib_name = (m.group(1) or m.group(2) or "").strip().lower()
            candidates = ibase_registry.get(ib_name) or []
            if any(_connection_matches(c, parsed) for c in candidates):
                return True
    return False


def find_matching_processes(ib_connection: str) -> list:
    """Процессы 1cv8*.exe, командная строка которых указывает на ЭТУ базу (ib_connection)."""
    parsed = parse_connection_string(ib_connection)
    registry = _load_ibase_registry()
    return [p for p in list_1c_processes() if _matches(p.get("CommandLine", ""), parsed, registry)]


def _is_automation_process(cmdline: str) -> bool:
    """
    True только для процессов, которые ЗАПУСКАЕТ САМ 1cAgent: форма-раннер
    (ENTERPRISE .../Execute ...epf_runner...), headless-прогон тестов
    (ENTERPRISE .../C"RunUnitTests=...") или ЛЮБОЙ из batch-режимов DESIGNER,
    которые используют module_deploy.py/extension_deploy.py/metadata_deploy.py
    (/DumpConfigToFiles, /LoadConfigFromFiles, /UpdateDBCfg). Голый интерактивный
    DESIGNER/ENTERPRISE (человек открыл Конфигуратор/клиент вручную — например,
    чтобы снять "Безопасный режим"/"Защиту от опасных действий" у только что
    подключённого расширения) ни одного из этих маркеров не содержит —
    protect_interactive защищает такую сессию от случайного force-kill.

    ГРАБЛИ (пойманы вживую): изначально распознавался только "/execute", из-за
    чего kill_sessions НЕ считал зависший RunUnitTests "своим" и пропускал его
    (skipped_interactive) — пользователю приходилось закрывать зависшую сессию
    тестов вручную. RunUnitTests — это тоже НАША автоматизация (yaxunit_runner.py),
    а не сессия человека, поэтому его маркер тоже нужно распознавать.

    ГРАБЛЯ №2 (пойманы вживую, #44): та же история повторилась с /LoadConfigFromFiles —
    когда DESIGNER-вызов deploy_*-инструмента завис на неожиданном модальном
    диалоге (например "Ни один из документов не является регистратором для
    регистра"), kill_sessions отказался его убивать (skipped_interactive),
    хотя это ТОЖЕ наша автоматизация, не сессия человека. Пользователю пришлось
    убивать процесс вручную через taskkill. Добавлены маркеры для всех
    batch-флагов DESIGNER, которые используют deploy_*-инструменты.
    """
    low = (cmdline or "").lower()
    return ("/execute" in low or 'rununittests=' in low or "/dumpconfigtofiles" in low
            or "/loadconfigfromfiles" in low or "/updatedbcfg" in low)


def kill_matching_processes(ib_connection: str, protect_interactive: bool = True) -> dict:
    """
    Точечно завершает процессы 1cv8*.exe, подключённые к ib_connection (сверка по
    командной строке). Возвращает {"killed": [...], "failed": [...], "skipped_interactive": [...]}.
    ВНИМАНИЕ: это force-kill (taskkill /F) — как обычное закрытие крестиком,
    не штатное грациозное завершение работы пользователя.

    protect_interactive=True (по умолчанию): НЕ трогает голые интерактивные сессии
    (человек вручную открыл Конфигуратор/клиент — например, чтобы снять галки
    безопасности у расширения) — убивает только собственные автоматизированные
    сессии 1cAgent (форма-раннер ENTERPRISE .../Execute). Такие интерактивные
    сессии попадают в "skipped_interactive", а не "killed"/"failed".
    """
    procs = find_matching_processes(ib_connection)
    killed, failed, skipped = [], [], []
    for p in procs:
        pid = p.get("ProcessId")
        entry = {"pid": pid, "name": p.get("Name")}
        if protect_interactive and not _is_automation_process(p.get("CommandLine", "")):
            skipped.append(entry)
            continue
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
        (killed if r.returncode == 0 else failed).append(entry)
    return {"killed": killed, "failed": failed, "skipped_interactive": skipped}
