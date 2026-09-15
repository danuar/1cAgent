#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#70, РЕЖИМ A: HTTP-транспорт заданий — чтобы раннер мог жить на ЧУЖОЙ машине,
куда не протянуть ни файловую шару, ни VPN. Механика — src/onec/http_transport.py.
"""
from src.tools.core import mcp, CFG
from src.onec import http_transport as _ht


@mcp.tool()
def http_transport_start(host: str = "127.0.0.1", port: int = 1533) -> dict:
    """Поднять HTTP-эндпоинт раннера в процессе MCP → url+token для поля «Папка обмена» раннера ('http://host:port#token'). host='0.0.0.0' — только за TLS-прокси; SMB наружу — никогда."""
    return _ht.start(CFG, host=host, port=port)


@mcp.tool()
def http_transport_status() -> dict:
    """Чтение. Эндпоинт поднят? mode owner/client, заданий обслужено, runner_alive/last_seen_ago. При runner_alive run_module идёт по HTTP сам."""
    return _ht.status(CFG)


@mcp.tool()
def http_transport_stop() -> dict:
    """Остановить эндпоинт (раннер будет ждать — штатно)."""
    return _ht.stop()
