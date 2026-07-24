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
    """
    Список запущенных процессов 1cv8*.exe (PID/имя/командная строка). Если задан
    ib_connection — только те, чья командная строка указывает на эту базу
    (сверка по /F или /S+база, см. sessions.py). Пустой ib_connection — все,
    для просмотра глазами (например, если авто-сверка не сработала: клиент
    запущен по /IBName из списка баз, а не сырым путём).
    """
    if ib_connection:
        return {"processes": _find_processes(ib_connection)}
    return {"processes": _list_processes()}


@mcp.tool()
def kill_sessions(ib_connection: str) -> dict:
    """
    РЕЖИМ B (подготовка). Точечно завершает (taskkill /F) процессы 1cv8*.exe,
    подключённые к базе ib_connection — сверка по командной строке, НЕ трогает
    процессы других баз. Это force-kill, не штатное завершение работы
    пользователя (штатный механизм ЗавершитьРаботуПользователей требует
    подсистему БСП в самой конфигурации). Нужно перед UpdateDBCfg на файловой
    базе, если к ней уже подключена живая сессия (см. attach_extension).

    ЗАЩИЩАЕТ интерактивные сессии: если человек вручную открыл Конфигуратор/клиент
    на этой же базе (например, чтобы сразу снять "Безопасный режим"/"Защиту от
    опасных действий" у только что подключённого расширения) — эта сессия НЕ
    убивается, попадает в ответе в "skipped_interactive". Завершаются только
    собственные автоматизированные сессии 1cAgent (форма-раннер .../Execute).
    """
    return _kill_processes(ib_connection)


@mcp.tool()
def attach_extension(ib_connection: str, cfe_path: str = "", ext_name: str = "",
                      kill_sessions: bool = True) -> dict:
    """
    РЕЖИМ B: подключает/обновляет расширение из .cfe в УКАЗАННУЮ базу (LoadCfg
    -Extension + UpdateDBCfg -Extension). Меняет реальную конфигурацию.
    ib_connection — строка подключения 1С, ОБЯЗАТЕЛЬНО указывать явно (не путать
    с базой-компилятором для сборки epf!), например:
      File="C:\\Users\\danua\\Documents\\gosNas";
      Srvr="server";Ref="base";Usr="Admin";Pwd="secret";
    cfe_path/ext_name по умолчанию — YAxUnit (CFG["yaxunit_cfe"]/CFG["yaxunit_ext"]).
    kill_sessions=True (по умолчанию) — сначала точечно завершает процессы,
    подключённые к этой базе (файловой базе для UpdateDBCfg нужен монопольный
    доступ). После подключения нужно вручную снять "Безопасный режим" и "Защиту
    от опасных действий" у расширения (см. доки YAxUnit). Живая сессия формы-
    раннера на этой базе (если она была) тоже будет завершена — её нужно поднять
    заново, чтобы продолжить run_module/heal_module.
    """
    return _attach_extension(CFG, ib_connection, cfe_path or CFG["yaxunit_cfe"],
                              ext_name or CFG["yaxunit_ext"], kill_sessions=kill_sessions)


@mcp.tool()
def start_runner(ib_connection: str) -> dict:
    """
    Открывает форму-раннер (CFG["epf_runner"]) в базе ib_connection полностью
    автоматически (ENTERPRISE /Execute) — форма сама взводит цикличный
    перезапуск в ПриОткрытии(), ручных кликов не нужно. АСИНХРОННО: не ждёт
    закрытия сессии, она должна остаться открытой (в этом и цель). Нужен
    после kill_sessions/attach_extension/deploy_module (они гасят сессию для
    монопольного доступа) — без него run_module/warmup/describe_metadata не
    будут работать. Подождите 5-15с и проверьте list_sessions()/warmup().
    """
    return _launch_runner(CFG, ib_connection)


@mcp.tool()
def restart_runner(ib_connection: str, retries: int = 2) -> dict:
    """
    АСИНХРОННО (job_id/job_status) — kill_sessions + start_runner + СОБЫТИЙНОЕ
    ожидание готовности (Real1CRunner.warmup(), встроенный поллинг до 50с)
    ОДНИМ вызовом, вместо ручного kill_sessions->start_runner->sleep(12)->
    warmup, повторявшегося ~18 раз за сессию билета №15. Нужен после
    kill_sessions/deploy_module/attach_extension или просто чтобы получить
    гарантированно свежую живую сессию для run_module/warmup/describe_metadata.

    retries=2 (по умолчанию) — если первая попытка не поймала окно готовности
    (ENTERPRISE стартовал медленнее обычного), пробует поднять раннер ещё раз.
    job_status(job_id) -> {"ok": bool, "attempts": N, "kill_report": {...},
    "warmup": {"status": "ok"|"timeout"|..., "output": "..."}}.
    """
    jid = _spawn(_restart_runner, CFG, ib_connection, retries=retries)
    return {"job_id": jid, "status": "running", "hint": "job_status(job_id, wait_seconds=30) — обычно ~10-30с, до ~100с при повторной попытке"}


@mcp.tool()
def screenshot_1c_window(ib_connection: str = "", force_image: bool = False):
    """
    ТОЛЬКО ЧТЕНИЕ. Снимок ВИДИМОГО окна 1cv8.exe (DESIGNER/ENTERPRISE) —
    закрывает слепую зону "невидимых" модальных диалогов, которые НЕ попадают
    ни в /Out-лог, ни в Журнал регистрации (check_event_log): ошибка формата
    документа, диалог логина, конфликт имён общего модуля и т.п. (см.
    HANDOFF.md #25 п.2, #32 п.2, #34, ретроотчёт по билету №15).

    ТАКЖЕ полезен, чтобы ОТЛИЧИТЬ "просто медленно" от "реально стоит на
    диалоге": если на картинке виден прогресс/окно ещё не готово, а не
    диалог — значит, процесс жив, ждите дальше (job_status(job_id,
    wait_seconds=...)) вместо повторного вызова deploy_*/dump_*.

    ib_connection — если задан, ищет окно СРЕДИ процессов, подключённых
    именно к этой базе (см. list_sessions); пустой — среди ВСЕХ реальных
    процессов 1cv8.exe (не угадывает по заголовку/классу окна — ловилось
    вживую ложное совпадение с окном редактора кода, у которого в заголовке
    было "1cAgent"). НИКОГДА не отправляет клавиши/клики в найденное окно
    (только смотрит) — закрытие зависшей сессии, если нужно, через kill_sessions.

    Возвращает {"found": bool, "pid", "title", "ocr_text"?, ...} — БЕЗ
    картинки, ЕСЛИ OCR (#39, Tesseract rus+eng) что-то распознал (экономит
    vision-токены — не тратить их, когда текст уже есть дёшево). Картинка
    (Image, отдельным элементом списка) прикладывается ТОЛЬКО если OCR не
    настроен/ничего не распознал (нестандартная вёрстка, мелкий шрифт), ИЛИ
    если force_image=True (когда распознанному тексту не доверяете —
    например, подозреваете, что важная деталь могла исказиться на смешанном
    рус/англ тексте, см. HANDOFF_ARCHIVE.md #39). found=false — окно не
    видно (процесс либо ещё не отрисовался, либо уже закрылся, либо это НЕ
    падение — просто пока ничего не всплыло, всё в порядке).
    """
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
    """Только чтение. Список подключённых к базе расширений (имя/активно/безопасный режим)."""
    status, errors, output = Real1CRunner(CFG)(LIST_EXTENSIONS_BSL)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", "output": output}


@mcp.tool()
def list_ib_users() -> dict:
    """
    Группа A (нужна живая форма-раннер, см. start_runner). Только чтение. Список
    ПЛАТФОРМЕННЫХ логинов информационной базы (ПользователиИнформационнойБазы —
    Имя/ПолноеИмя), НЕ бизнес-справочник Пользователи. НЕ обходит аутентификацию:
    раннер должен быть уже поднят под каким-то валидным логином (start_runner) —
    полезно свериться с точным написанием логина/регистром для follow-up-вызовов.
    """
    status, errors, output = Real1CRunner(CFG)(LIST_IB_USERS_BSL)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", "output": output}
