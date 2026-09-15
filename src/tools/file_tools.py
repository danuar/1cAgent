#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Передача файлов на машину раннера. Нужно потому, что пользователь работает с
базами УДАЛЁННО: агент собирает .epf/.cfe локально, а сервер 1С этих путей не
видит и отвечает ОшибкаДоступаКЛокальномуФайлу. Механика — в
src/onec/file_transfer.py.
"""
from pathlib import Path

from src.tools.core import mcp, CFG
from src.onec.glue import Real1CRunner
from src.onec.file_transfer import upload as _upload


@mcp.tool()
def upload_file_to_runner(local_path: str, remote_dir: str = "",
                          remote_name: str = "") -> dict:
    """Перелить локальный файл на машину раннера (кусками base64 через задания). remote_dir пустой → CFG remote_upload_dir → временный каталог сервера. → {ok, remote_path, parts, size, sha1}. Для удалённых баз (сервер не видит локальных путей)."""
    src = Path(local_path)
    if not src.exists():
        return {"ok": False, "reason": f"нет файла: {src}"}
    target_dir = remote_dir or CFG.get("remote_upload_dir") or ""
    return _upload(Real1CRunner(CFG), str(src),
                   file_name=remote_name, remote_dir=target_dir)


@mcp.tool()
def remote_upload_dir() -> dict:
    """Куда upload_file_to_runner кладёт файлы по умолчанию."""
    configured = CFG.get("remote_upload_dir") or ""
    return {"remote_upload_dir": configured,
            "effective": configured or "временный каталог сервера (КаталогВременныхФайлов())",
            "note": "меняется в src/core/config.py или параметром remote_dir на один вызов"}
