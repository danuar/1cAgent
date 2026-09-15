#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Общее ядро для всех tools_*.py: единственный экземпляр mcp/FastMCP, job-инфра
(_spawn/_JOBS/job_status), телеметрия вызовов и мелкие хелперы. Разбито из
mcp_server.py (было 590 строк одним файлом — правка ОДНОГО инструмента
требовала читать/грепать весь файл целиком). Каждый tools_*.py делает
`from src.tools.core import mcp, ...` и регистрирует свои @mcp.tool() —
mcp_server.py лишь импортирует модули ради побочного эффекта регистрации и
запускает mcp.run().
"""
import functools
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from src.core.config import CFG

# Уходит клиенту в handshake (Claude Code кладёт в системный промпт). Коротко:
# конвенции, общие для всех инструментов, чтобы не повторять их в каждом docstring.
INSTRUCTIONS = """\
1c-agent: BSL в живой 1С через раннер + DESIGNER/ENTERPRISE CLI. Полный бриф — HANDOFF.md в корне проекта.
Старт: preflight(). Раннер не на связи → попросить человека открыть ВнешняяОбработка.epf в базе.
ib_connection — строка подключения ТОЛЬКО из чата, явно в каждом вызове; Usr= — точный логин ИБ (list_ib_users), иначе зависание на диалоге.
Конвенции: «Async» = вернёт job_id, результат job_status(job_id, wait_seconds=55). «Группа A» = нужен живой раннер.
Деплой-инструменты (deploy_*/sync_*/attach_extension/adopt_*) гасят сессии базы, включая раннер → потом restart_runner; после деплоя базу оставлять свободной, если человек не просил раннер.
Задание run_module: Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт … Сообщить("ГОТОВО"); без вложенных Процедура/Функция и Возврат.
Файлы править Write/Edit, не bash-heredoc (слэши схлопываются). .epf разбирать только в родной базе. Боевые базы удалённые — файлы туда через upload_file_to_runner.
Не хватило инструмента / упёрся в ограничение → запись в TASKS.md «Чего не хватило». Новый ручной паттерн → guides.py + инструмент.
"""
mcp = FastMCP("1c-agent", instructions=INSTRUCTIONS)
MAX_CODE_INLINE = 4000
MAX_OUTPUT = 6000
_JOBS = {}
_JOB_EVENTS = {}
_JOB_DONE_AT = {}
# Потолок блокирующего ожидания в job_status — строго МЕНЬШЕ типичного клиентского
# MCP-таймаута (см. HANDOFF.md #25 п.5), чтобы сам job_status не завис так же,
# как раньше зависали deploy_module/run_tests до перехода на job_id/job_status.
_MAX_WAIT_SECONDS = 55
# Сколько хранить результат ЗАВЕРШЁННОЙ задачи, прежде чем можно вытеснить её из
# _JOBS/_JOB_EVENTS. Без этого оба словаря растут без ограничения на весь срок
# жизни процесса сервера (мелкая, но реальная утечка памяти при долгой сессии) —
# найдено при код-ревью, не по факту жалобы на память.
_JOB_TTL_SECONDS = 3600


def _clip(s, n):
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n...(+{len(s) - n} симв.)"


# ---------- Телеметрия вызовов (ретроотчёт по билету №15, п.1 TL;DR) ----------
# Раньше "ретроспектива по сессии" собиралась по памяти диалога — сам отчёт
# честно фиксировал, что это реконструкция, не факт (у сервера не было
# собственного журнала вызовов). Теперь каждый @mcp.tool()-вызов (см. _timed_tool
# ниже) и каждое реальное завершение фоновой job (см. _spawn) пишут по строке
# в JSONL. Телеметрия НИКОГДА не должна ронять реальный вызов инструмента —
# любая ошибка записи на диск молча проглатывается.
_TELEMETRY_PATH = Path(CFG["runtime_dir"]) / "telemetry.jsonl"
_PWD_RE = re.compile(r'(Pwd\s*=\s*")[^"]*(")', re.IGNORECASE)


def _mask_secrets(s: str) -> str:
    """ib_connection может содержать Pwd="..." в открытом виде — не писать пароли на диск."""
    return _PWD_RE.sub(r"\1***\2", s)


def _summarize_args(args: tuple, kwargs: dict, limit: int = 200) -> str:
    """Компактная, замаскированная, обрезанная строка аргументов — не весь bsl_code целиком."""
    try:
        parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        return _clip(_mask_secrets(", ".join(parts)), limit)
    except Exception:
        return ""


def _log_telemetry(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        _TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TELEMETRY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


_real_tool_decorator = mcp.tool  # оригинальный FastMCP.tool — ДО переопределения ниже


def _timed_tool(*targs, **tkwargs):
    """
    Обёртка над FastMCP.tool(): КАЖДЫЙ @mcp.tool(), зарегистрированный где угодно
    в tools_*.py, автоматически пишет телеметрию — правка отдельных файлов не
    нужна, единственная точка регистрации здесь. Для АСИНХРОННЫХ инструментов
    (возвращают job_id сразу, см. _spawn) это событие — только время "диспетчинга"
    (обычно быстро, kind="call"); реальную длительность фоновой работы см. в
    отдельном событии kind="async_job" из _spawn ниже (там же — статус, с
    которым job реально завершилась).
    """
    real_decorator = _real_tool_decorator(*targs, **tkwargs)

    def wrapper(fn):
        @functools.wraps(fn)
        def timed(*a, **k):
            t0 = time.time()
            status = "error"
            try:
                result = fn(*a, **k)
                status = "ok"
                return result
            finally:
                _log_telemetry({
                    "kind": "call",
                    "tool": fn.__name__,
                    "duration_ms": round((time.time() - t0) * 1000),
                    "status": status,
                    "args": _summarize_args(a, k),
                })
        return real_decorator(timed)
    return wrapper


mcp.tool = _timed_tool


def _evict_stale_jobs():
    now = time.time()
    for jid, done_at in list(_JOB_DONE_AT.items()):
        if now - done_at >= _JOB_TTL_SECONDS:
            _JOBS.pop(jid, None)
            _JOB_EVENTS.pop(jid, None)
            _JOB_DONE_AT.pop(jid, None)


def _spawn(fn, *a, **k):
    _evict_stale_jobs()  # дешёвая ленивая уборка при каждом новом job, без отдельного потока
    jid = uuid.uuid4().hex[:8]
    _JOBS[jid] = {"status": "running", "result": None}
    ev = threading.Event()
    _JOB_EVENTS[jid] = ev

    def work():
        t0 = time.time()
        status = "error"
        try:
            _JOBS[jid] = {"status": "done", "result": fn(*a, **k)}
            status = "ok"
        except Exception as e:
            _JOBS[jid] = {"status": "error", "result": {"error": repr(e)}}
        finally:
            _JOB_DONE_AT[jid] = time.time()
            # NB: fn — ВНУТРЕННЯЯ реализация (например deploy_common_module), не
            # имя MCP-инструмента (deploy_module) — имена могут не совпадать один
            # в один с "call"-событием выше; оба стабильны и грепаются по смыслу.
            _log_telemetry({
                "kind": "async_job",
                "tool": fn.__name__,
                "job_id": jid,
                "duration_ms": round((time.time() - t0) * 1000),
                "status": status,
                "args": _summarize_args(a, k),
            })
            ev.set()

    threading.Thread(target=work, daemon=True).start()
    return jid


@mcp.tool()
def job_status(job_id: str, wait_seconds: int = 0) -> dict:
    """Результат async-задачи. wait_seconds>0 — событийно ждать до min(wait_seconds,55); всё ещё running — вызвать снова."""
    ev = _JOB_EVENTS.get(job_id)
    if ev is not None and wait_seconds > 0:
        ev.wait(timeout=min(wait_seconds, _MAX_WAIT_SECONDS))
    return _JOBS.get(job_id, {"status": "unknown"})
