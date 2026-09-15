#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#45: общая безопасная замена `subprocess.run(cmd, shell=True, timeout=N)` для
ЛЮБОГО batch-вызова DESIGNER (LoadConfigFromFiles/UpdateDBCfg/
DumpConfigToFiles) — раньше эта функция (`_run`) была ПОЧТИ ДОСЛОВНО
продублирована в metadata_deploy.py/module_deploy.py/extension_deploy.py.

Два реальных пробела, найденных ЖИВЫМ тестированием (#42-44), которые эта
замена закрывает разом:

1. **`subprocess.run(shell=True, timeout=N)` НЕ гарантированно убивает
   дочерний процесс на Windows при таймауте** — с `shell=True` реальный
   `1cv8.exe` является ВНУКОМ Python-процесса (через обёртку `cmd.exe`),
   и штатное поведение таймаута убивает только обёртку, оставляя `1cv8.exe`
   осиротевшим и зависшим (пойман вживую — пришлось убивать вручную через
   `taskkill /PID.../F` из PowerShell, Bash кейс не смог). `run_watched`
   всегда явно убивает ДЕРЕВО процессов (`taskkill /T /F`), не полагаясь на
   Python.
2. **Слепое ожидание всего timeout (до 600с), даже если 1С уже через 1-2с
   встала на неожиданный модальный диалог** (например "Конфигурация базы
   данных не соответствует сохранённой. Продолжить?", или "Ни один из
   документов не является регистратором для регистра") — тот же паттерн,
   что уже применили к `restart_runner`/`_wait_for_ready_or_dialog` (#42),
   перенесён сюда: пока процесс не завершился, каждые ~3с проверяем экран
   (screenshot+OCR) на признаки диалога, и если он похож на диалог — сразу
   убиваем и возвращаем диагностику, вместо ожидания вслепую.

ВАЖНО: НИКОГДА не отправляет клавиши/клики — только смотрит и, если нужно,
завершает процесс. Это то же самое "read-only + kill, не dismiss", что и у
`screenshot_1c_window`/`restart_runner`.
"""
import subprocess
import time

from src.onec.sessions import find_matching_processes
from src.core.screenshot_1c import (find_1c_window, _enum_1c_windows, capture_window,
                                    ocr_text as _ocr_text)

# Тот же список маркеров, что в runner_launch._looks_like_dialog (#42) — держим
# отдельной копией здесь, т.к. designer_run обслуживает DESIGNER-вызовы
# (нет своей "формы-раннера", поэтому не нужен _RUNNER_FORM_MARKERS-фильтр).
_DIALOG_MARKERS = ("продолжить", "отмена", " да ", " нет ", "cancel", " ok", "ошибка")

# ОКНО АВТОРИЗАЦИИ — отдельный случай, и самый частый (поймано вживую 14.09.2026
# на unf14143_demo: замеры выгрузки шли 928с и 353с вместо ~15с, потому что
# конфигуратор молча ждал логин, а пользователь жал Enter руками). Причина
# всегда одна: в команде нет /N и /P, то есть в ib_connection не передали
# Usr/Pwd. Лечится не убийством процесса, а строкой подключения, поэтому и
# подсказка должна быть другая.
_AUTH_MARKERS = ("доступ к информационной базе", "аутентификация", "пароль")


def _classify(text: str) -> str:
    """'' | 'auth' | 'dialog' — что именно показано на экране."""
    low = (text or "").lower()
    if any(m in low for m in _AUTH_MARKERS):
        return "auth"
    if any(m in low for m in _DIALOG_MARKERS):
        return "dialog"
    return ""


def _looks_like_dialog(text: str) -> bool:
    return bool(_classify(text))


def _kill_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
    except Exception:
        pass


def run_watched(cmd: str, timeout: int, cfg: dict, ib_connection: str, poll_interval: int = 3) -> dict:
    """
    Popen(cmd) вместо subprocess.run(timeout=) — не блокирует, поэтому можно
    параллельно проверять экран. Возвращает:
        {"returncode": int, "dialog": False, "hint": None, "timed_out": False}  — обычное завершение
        {"returncode": None, "dialog": True, "hint": "<распознанный текст>", "timed_out": False}  — диалог, процесс убит
        {"returncode": None, "dialog": False, "hint": None, "timed_out": True}  — таймаут, процесс убит
    Никогда не бросает исключение (в отличие от subprocess.run(timeout=),
    которое кидает TimeoutExpired) — вызывающий код всегда получает словарь.
    """
    proc = subprocess.Popen(cmd, shell=True)
    t0 = time.time()
    while True:
        rc = proc.poll()
        if rc is not None:
            return {"returncode": rc, "dialog": False, "hint": None, "timed_out": False}

        elapsed = time.time() - t0
        if elapsed >= timeout:
            _kill_tree(proc.pid)
            return {"returncode": None, "dialog": False, "hint": None, "timed_out": True}

        try:
            procs = find_matching_processes(ib_connection)
            pids = {p["ProcessId"] for p in procs if p.get("ProcessId")}
            # ВСЕ окна процесса, а не первое: модальное окно (в т.ч.
            # авторизации) — ОТДЕЛЬНОЕ top-level окно, и find_1c_window
            # возвращал вместо него пустое главное окно конфигуратора. Именно
            # поэтому детектор молчал, пока 1С ждала логин.
            for win in (_enum_1c_windows(pids) if pids else []):
                # заголовок дешевле OCR и у окна авторизации говорящий
                kind = _classify(win.get("title") or "")
                text = ""
                if not kind:
                    png = capture_window(win["hwnd"])
                    if png is not None:
                        text = _ocr_text(cfg, png) or ""
                        kind = _classify(text)
                if kind:
                    _kill_tree(proc.pid)
                    hint = ((win.get("title") or "") + " | " + text).strip(" |")
                    return {"returncode": None, "dialog": True, "kind": kind,
                            "hint": hint[:300], "timed_out": False}
        except Exception:
            pass  # проверка экрана — best-effort, не должна ронять основной вызов

        time.sleep(min(poll_interval, max(0.1, timeout - elapsed)))


def watched_error(step: str, watched: dict, timeout: int, **extra) -> dict:
    """
    Собирает единообразный error-dict, ЕСЛИ watched — это диалог или таймаут.
    Возвращает None, если это НЕ ошибка такого рода (тогда вызывающий код
    сам проверяет watched["returncode"] как раньше — обычный путь ошибки/успеха
    DESIGNER-вызова не меняется).
    """
    if watched["dialog"]:
        if watched.get("kind") == "auth":
            return {"ok": False, "step": "auth_dialog", "at_step": step,
                    "hint": watched["hint"],
                    "advice": "1С показала окно АВТОРИЗАЦИИ и ждала логин — процесс убит. "
                              "В строке подключения нет пользователя: добавьте "
                              'Usr="Имя";Pwd="пароль"; в ib_connection. Без этого любой '
                              "пакетный вызов конфигуратора будет висеть до таймаута.", **extra}
        return {"ok": False, "step": "unexpected_dialog", "at_step": step,
                "hint": watched["hint"],
                "advice": "похоже на модальный диалог (не обычное выполнение) — процесс уже "
                          "убит. Разберитесь через screenshot_1c_window/check_event_log, прежде "
                          "чем повторять попытку.", **extra}
    if watched["timed_out"]:
        return {"ok": False, "step": step, "reason": f"таймаут {timeout}с — процесс убит (taskkill /T /F)",
                **extra}
    return None
