#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP-сервер: инструменты для 1С-петли (для Клода в чате). НАЧНИ С HANDOFF.md —
там порядок действий для новой сессии в двух шагах, без гадания.

Установка: pip install mcp ; регистрация: claude_desktop_config.example.json

ДВЕ НЕЗАВИСИМЫЕ ГРУППЫ ИНСТРУМЕНТОВ, не путать предпосылки:
  A) run_module/heal_module/warmup/describe_metadata/query_data/list_extensions —
     нужна ЖИВАЯ форма-раннер (см. start_runner) в базе. heal_module/fix_snippet
     ДОПОЛНИТЕЛЬНО нужен LM Studio на :1235 (Qwen-фиксер) — остальные из этой
     группы БЕЗ него работают нормально.
  B) attach_extension/deploy_module/run_tests/kill_sessions/list_sessions/
     start_runner/lint_module/check_setup — работают НАПРЯМУЮ через DESIGNER/
     ENTERPRISE CLI по явно переданному ib_connection, форма-раннер и LM Studio
     не нужны вообще.

АСИНХРОННОСТЬ: heal_module и fix_snippet зовут Qwen (иногда подвисает дольше
таймаута MCP) — возвращают job_id мгновенно, результат через job_status(job_id).
Всё остальное — синхронное (кроме deploy_module/sync_extension_files/
deploy_extension_from_files/run_tests/verify_extension — тоже job_id, см. #25-27).

ПЕСОЧНИЦА ИСПОЛНЕНИЯ (для run_module/heal_module/fix_snippet):
  - точка входа СТРОГО:  Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт ... КонецПроцедуры
  - логируй в строку ЛогВыполнения, в конце допиши "ГОТОВО"
  - к конфигурации — полными путями (Документы.X, Справочники.Y, Запрос); выборка .Выбрать()
  - ПЕРВЫМ вызовом в сессии из группы A сделай warmup().

СТРУКТУРА ФАЙЛОВ (#28 разбил mcp_server.py на тонкие tools_*.py; #29 разложил
всё дерево по src/, чтобы и здесь не расползаться по десяткам файлов в корне):
  src/core/   — config.py, errors1c.py, ib_connection.py, dump_lock.py (низкоуровневая инфра).
  src/onec/   — вся бизнес-логика общения с 1С: glue.py (Real1CRunner/heal),
                runner_launch.py, sessions.py, extensions.py, bootstrap.py,
                metadata_tool.py, bsl_ls.py, module_deploy.py, extension_deploy.py,
                metadata_deploy.py (Справочники/Документы/РегистрыНакопления/
                РегистрыСведений ОСНОВНОЙ конфигурации, #билет15),
                event_log.py, yaxunit_runner.py, verify.py, module_reader.py,
                extractor.py, fixer.py, guides.py.
  src/tools/  — тонкие @mcp.tool()-обёртки поверх src/onec: core.py (mcp/FastMCP,
                job_status, _spawn/_JOBS), module_tools.py, session_tools.py,
                deploy_tools.py, test_tools.py, eventlog_tools.py, verify_tools.py,
                metadata_tools.py.
Этот файл (корень, вне src/ — единственная точка входа, которую видит MCP-клиент)
только импортирует src/tools/*.py (регистрирует @mcp.tool() по побочному эффекту
импорта) и запускает mcp.run().
"""
from src.tools.core import mcp
import src.tools.module_tools    # noqa: F401 — регистрация @mcp.tool()
import src.tools.session_tools   # noqa: F401
import src.tools.deploy_tools    # noqa: F401
import src.tools.test_tools      # noqa: F401
import src.tools.eventlog_tools  # noqa: F401
import src.tools.verify_tools    # noqa: F401
import src.tools.metadata_tools  # noqa: F401
import src.tools.reference_tools # noqa: F401

if __name__ == "__main__":
    mcp.run()   # stdio
