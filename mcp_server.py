#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP-сервер 1С-агента. Точка входа для клиента (Claude Desktop/Code): импортирует
src/tools/*.py (регистрация @mcp.tool() побочным эффектом импорта) и запускает mcp.run().

Для ИИ: бриф — HANDOFF.md (и он же коротко в src/tools/core.py INSTRUCTIONS, уходит
клиенту при подключении). Задачи/хотелки — TASKS.md. История — HANDOFF_ARCHIVE.md.
Для человека: README.md.
"""
from src.tools.core import mcp, CFG
import src.tools.module_tools    # noqa: F401 — регистрация @mcp.tool()
import src.tools.session_tools   # noqa: F401
import src.tools.deploy_tools    # noqa: F401
import src.tools.test_tools      # noqa: F401
import src.tools.eventlog_tools  # noqa: F401
import src.tools.verify_tools    # noqa: F401
import src.tools.metadata_tools  # noqa: F401
import src.tools.reference_tools # noqa: F401
import src.tools.epf_tools     # noqa: F401
import src.tools.http_tools    # noqa: F401
import src.tools.diag_tools    # noqa: F401
import src.tools.container_tools # noqa: F401
import src.tools.file_tools     # noqa: F401

def _trim_schemas():
    """Убрать из схем параметров автогенерируемые title («Ib Connection», «deploy_reportArguments»):
    они дублируют имя и только едят токены клиента на каждой сессии."""
    for tool in mcp._tool_manager._tools.values():
        params = tool.parameters
        params.pop("title", None)
        for prop in params.get("properties", {}).values():
            prop.pop("title", None)


_trim_schemas()

if __name__ == "__main__":
    # Модели НЕ грузим при старте (ленивая загрузка в fixer/embeddings_client, #62).
    # HTTP-эндпоинт раннера поднимаем вместе с сервером, best-effort (#81).
    if CFG.get("http_autostart"):
        try:
            from src.onec.http_transport import start as _http_start
            _http_start(CFG, host=CFG.get("http_host", "127.0.0.1"),
                        port=CFG.get("http_port", 1533))
        except Exception:
            pass

    mcp.run()   # stdio
