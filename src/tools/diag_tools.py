#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#85 (A3): разведка одним вызовом. Механика — src/onec/preflight.py."""
from src.tools.core import mcp, CFG
from src.onec.preflight import preflight as _preflight


@mcp.tool()
def preflight(probe: bool = False) -> dict:
    """Вызывать первым в сессии. Сводка: платформы, компилятор-база, HTTP-эндпоинт, транспорт/режим раннера, verdict. probe=True — плюс пробное задание через раннер."""
    return _preflight(CFG, probe=probe)
