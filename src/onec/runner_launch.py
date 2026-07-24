#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автозапуск сессии 1С:Предприятия с открытой формой-раннером — без ручного
поиска базы/обработки в списке 1С:Стартера.

Платформенный механизм (подтверждён по докам, см. mifodiy.com/...): ключ
/Execute <файл.epf> при запуске ENTERPRISE открывает указанную внешнюю
обработку автоматически — платформа сама вызывает её ПриОткрытии(), как
если бы человек открыл файл через меню Файл->Открыть. Цикличный перезапуск
форма взводит сама (ПриОткрытии -> ВключитьЦикличныйПерезапуск), ручных
кликов не нужно.

#21: чтобы форма НЕ хардкодила пути к error.txt/logs.txt/AgentCode.epf,
дополнительно передаём рабочую папку через /C — платформа кладёт это
значение в глобальную переменную ПараметрЗапуска, форма читает её в
ЗапуститьАгента() и строит все пути от неё (см. Module.bsl внутри
CFG["epf_runner_src"]). Так путь всегда свежий и не зависит от того, где
физически лежит проект — Python и так каждый раз знает свою рабочую папку.

    "<1cv8.exe>" ENTERPRISE <connection> /Execute "<epf_runner>" /C"<work_dir>"

ВАЖНО: запуск АСИНХРОННЫЙ (Popen, не subprocess.run) — форма-раннер держит
сессию открытой неопределённо долго (это и есть цель), ждать завершения
процесса нельзя, иначе зависнем на весь срок жизни сессии.
"""
import subprocess
import threading
import time

from src.core.ib_connection import cli_connection_str
from src.onec.sessions import kill_matching_processes, find_matching_processes
from src.onec.glue import Real1CRunner
from src.core.screenshot_1c import find_1c_window, capture_window, ocr_text as _ocr_text

# #42 (найдено вживую): слова, типичные для КНОПОК модального диалога 1С
# (Продолжить?/Да/Нет/Отмена/OK), которых НЕ бывает на обычном экране загрузки
# формы-раннера. Эвристика ДЕШЁВАЯ и неидеальная (может дать ложные срабатывания/
# пропуски) — окончательное решение всё равно за Claude, читающим hint/картинку
# через screenshot_1c_window, это только сигнал "стоит присмотреться, не ждать
# вслепую весь таймаут".
_DIALOG_MARKERS = ("продолжить", "отмена", " да ", " нет ", "cancel", " ok", "ошибка")
# Надписи САМОЙ формы-раннера — если они есть, это НЕ диалог, а обычная загрузка.
_RUNNER_FORM_MARKERS = ("перезапуск", "внешняя обработка")


def launch_runner(cfg: dict, ib_connection: str) -> dict:
    """
    Открывает форму-раннер (CFG["epf_runner"] — файл С ФОРМОЙ, НЕ пересобираемый
    кодом, не путать с CFG["epf_build"] из glue.py) в базе ib_connection через
    ENTERPRISE /Execute. Возвращает {"ok": bool, "pid"?, "reason"?}.
    Не ждёт закрытия сессии — она должна остаться открытой (это и есть цель).
    """
    try:
        conn = cli_connection_str(ib_connection)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}

    cmd = f'"{cfg["path_1c"]}" ENTERPRISE {conn} /Execute "{cfg["epf_runner"]}" /C"{cfg["work_dir"]}"'
    try:
        proc = subprocess.Popen(cmd, shell=True)
    except Exception as e:
        return {"ok": False, "reason": repr(e)}

    return {"ok": True, "pid": proc.pid,
            "hint": "сессия поднимается в фоне (~5-15с) — проверьте через паузу list_sessions()/warmup()"}


def _looks_like_dialog(text: str) -> bool:
    low = (text or "").lower()
    if any(m in low for m in _RUNNER_FORM_MARKERS):
        return False
    return any(m in low for m in _DIALOG_MARKERS)


def _wait_for_ready_or_dialog(cfg: dict, ib_connection: str, timeout: int = 50, poll_interval: int = 2) -> dict:
    """
    #42 (найдено вживую — restart_runner дважды подряд вслепую ждал полный
    таймаут warmup(), затем повторял попытку, оставив 2 зависших процесса,
    хотя 1С уже 1-2с спустя после старта показала модальный диалог
    "Конфигурация базы данных не соответствует сохранённой. Продолжить?").

    Запускает Real1CRunner.warmup() В ФОНОВОМ ПОТОКЕ и, ПОКА он не завершился,
    каждые poll_interval секунд (НЕ каждую секунду — снимок+OCR имеют свою
    цену по времени/CPU, 2с достаточно, чтобы поймать проблему намного
    быстрее полного 50-секундного таймаута) делает screenshot_1c_window-
    эквивалент (find_1c_window+capture_window+ocr_text) и проверяет
    эвристику _looks_like_dialog. Что раньше — то и возвращает:
        {"outcome": "ready", "warmup": {...}}
        {"outcome": "dialog", "hint": <распознанный текст>, "window_title": ...}
        {"outcome": "timeout", "warmup": None}
    НИКОГДА не отправляет клавиши/клики — только читает экран. Если поймали
    "dialog", вызывающий код (restart_runner) НЕ должен вслепую повторять
    попытку — решение (kill_sessions/разбор через screenshot_1c_window с
    force_image) остаётся за Claude.
    """
    box = {}

    def _run_warmup():
        status, _errors, output = Real1CRunner(cfg).warmup()
        box["warmup"] = {"status": status, "output": (output or "")[:400]}

    t = threading.Thread(target=_run_warmup, daemon=True)
    t.start()

    t0 = time.time()
    while time.time() - t0 < timeout:
        if "warmup" in box:
            return {"outcome": "ready", "warmup": box["warmup"]}
        procs = find_matching_processes(ib_connection)
        pids = {p["ProcessId"] for p in procs if p.get("ProcessId")}
        win = find_1c_window(pids) if pids else None
        if win is not None:
            png = capture_window(win["hwnd"])
            if png is not None:
                text = _ocr_text(cfg, png) or ""
                if _looks_like_dialog(text):
                    return {"outcome": "dialog", "hint": text[:300], "window_title": win["title"]}
        time.sleep(poll_interval)

    return {"outcome": "timeout", "warmup": box.get("warmup")}


def restart_runner(cfg: dict, ib_connection: str, retries: int = 2) -> dict:
    """
    kill_sessions + launch_runner + СОБЫТИЙНОЕ ожидание готовности — вместо
    ручного kill->start->sleep(12)->warmup, повторявшегося ~18 раз за сессию
    билета №15 (см. ретроотчёт/HANDOFF.md). Ожидание — через
    _wait_for_ready_or_dialog (#42): не только ждёт warmup(), но и АКТИВНО
    проверяет экран каждые ~2с, чтобы поймать неожиданный модальный диалог
    (например рассинхрон конфигурации/базы) за секунды, а не после полного
    таймаута — и, что важно, НЕ повторяет попытку вслепую поверх диалога
    (см. живую находку: раньше это оставляло по 2 зависших процесса).

    retries — сколько раз повторить launch_runner+ожидание, если попытка
    закончилась ПРОСТЫМ таймаутом (не диалогом) — ENTERPRISE стартовал
    медленнее обычного или была занята лицензия/слот. Если поймали диалог —
    НЕ повторяем, возвращаем результат сразу (см. step="unexpected_dialog").
    """
    kill_report = kill_matching_processes(ib_connection)
    last_warmup = None
    for attempt in range(1, retries + 1):
        launch = launch_runner(cfg, ib_connection)
        if not launch.get("ok"):
            return {"ok": False, "step": "start_runner", "attempt": attempt,
                    "kill_report": kill_report, "launch": launch}
        outcome = _wait_for_ready_or_dialog(cfg, ib_connection)
        if outcome["outcome"] == "ready":
            return {"ok": True, "attempts": attempt, "kill_report": kill_report, "warmup": outcome["warmup"]}
        if outcome["outcome"] == "dialog":
            return {"ok": False, "step": "unexpected_dialog", "attempt": attempt,
                    "hint": outcome["hint"], "window_title": outcome["window_title"],
                    "kill_report": kill_report,
                    "advice": "похоже на модальный диалог (не обычная загрузка) — НЕ повторяем "
                              "попытку вслепую. Вызовите screenshot_1c_window(ib_connection, "
                              "force_image=True) за точной картинкой, прежде чем решать "
                              "kill_sessions+повтор или что-то другое."}
        last_warmup = outcome.get("warmup")
    return {"ok": False, "step": "warmup", "attempts": retries,
            "kill_report": kill_report, "warmup": last_warmup}
