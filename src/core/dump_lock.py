#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lock-файл против гонки параллельных DumpConfigToFiles/LoadConfigFromFiles в ОДНУ
И ТУ ЖЕ папку runtime/ext_src/<ext>. Пойман вживую: клиентский таймаут MCP короче
реальной DESIGNER-операции на тяжёлой конфигурации — агент (или пользователь),
не дождавшись ответа, повторяет вызов, а предыдущий ещё пишет файлы в ту же
папку → повреждённый XML (см. HANDOFF.md #25, п.6).

dump_lock(dump_dir) — просто: пишет `<dump_dir>/.lock` = "<pid>|<unix-время>" на
время операции, удаляет в конце. Если лок уже занят ДРУГИМ живым процессом моложе
stale_seconds — кидает RuntimeError вместо того, чтобы тихо портить файлы.
"""
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                              capture_output=True, text=True, timeout=5)
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


def _try_acquire(lock_path: Path) -> bool:
    """
    Атомарный захват: os.open(O_CREAT|O_EXCL) падает FileExistsError, если файл
    уже существует — ОС гарантирует, что "проверить-и-создать" делает единым
    системным вызовом. Раньше было check-then-write (lock_path.exists() затем
    отдельный write_text) — теоретическая гонка: два процесса одновременно видят
    "лока нет" и оба продолжают. Малове­роятно на практике (нужны два вызова
    вплотную), но раз докстринг обещает защиту от гонки — она должна быть настоящей.
    """
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, f"{os.getpid()}|{time.time()}".encode("utf-8"))
    finally:
        os.close(fd)
    return True


@contextmanager
def dump_lock(dump_dir: Path, stale_seconds: int = 600):
    """
    Использование: with dump_lock(dump_dir): <Dump -> правки -> Load -> Update>.
    stale_seconds — сколько ждать до того, как лок считается протухшим (процесс
    мог быть убит без удаления .lock) — по умолчанию 10 минут, с запасом даже для
    тяжёлых ERP-конфигураций.
    """
    dump_dir = Path(dump_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)
    lock_path = dump_dir / ".lock"

    if not _try_acquire(lock_path):
        try:
            pid_str, ts_str = lock_path.read_text(encoding="utf-8").split("|", 1)
            pid, ts = int(pid_str), float(ts_str)
            age = time.time() - ts
            stale = age >= stale_seconds or not _pid_alive(pid)
        except Exception:
            stale, pid, age = True, None, None  # повреждённый lock-файл — считаем протухшим

        if not stale:
            raise RuntimeError(
                f"{dump_dir} уже занята другим деплоем (pid={pid}, начат {age:.0f}с назад) — "
                f"дождитесь его завершения (проверьте list_sessions на DESIGNER-процесс) "
                f"перед повтором. Если это точно зависший процесс старше {stale_seconds}с, "
                f"lock снимется сам при следующей попытке."
            )

        # протух — снимаем и пробуем захватить ещё раз атомарно (не просто write_text)
        lock_path.unlink(missing_ok=True)
        if not _try_acquire(lock_path):
            raise RuntimeError(
                f"{dump_dir}: лок протух, но кто-то перехватил его в момент перезахвата — "
                f"повторите вызов."
            )

    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
