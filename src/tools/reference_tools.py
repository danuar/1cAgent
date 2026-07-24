#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РЕЖИМ B, справочный (#38): search_reference/read_reference_snippet — поиск
по локальному дампу полной типовой конфигурации, см. src/onec/reference_search.py.
search_reference_semantic (#54) — семантический поиск по процедурам/функциям,
см. src/onec/semantic_search.py."""
from src.tools.core import mcp, CFG
from src.onec.reference_search import (search_reference as _search_reference,
                                        read_reference_snippet as _read_reference_snippet)
from src.onec.semantic_search import semantic_search as _semantic_search


@mcp.tool()
def search_reference(pattern: str, glob: str = "**/*.xml", max_matches: int = 40) -> dict:
    """
    ТОЛЬКО ЧТЕНИЕ. Regex-поиск по локальному дампу ПОЛНОЙ типовой конфигурации
    (например 1С:ERP), настроенному в CFG["reference_config"] (личный путь под
    конкретную машину, см. src/core/config.py). Grep, НЕ векторный/семантический
    поиск — для точных XML-паттернов (тег/атрибут) надёжнее и не требует
    инфраструктуры эмбеддингов.

    Пример: pattern='Event name="\\\\w+"', glob="Documents/**/Ext/Form.xml" —
    найти реально используемые платформенные имена событий в формах (закрывает
    класс риска "угадал русское имя вместо платформенного" — см. HANDOFF.md #34,
    HANDOFF_ARCHIVE.md #34/#38).

    Возвращает {"matches": [{"path","line","match","context"}], ...} — маленькие
    фрагменты (~240 симв. вокруг совпадения), НЕ целые файлы (там могут быть
    десятки/сотни тысяч файлов — см. read_reference_snippet для более широкого
    куска ОДНОГО конкретного файла по пути из "path").
    """
    return _search_reference(CFG, pattern, glob=glob, max_matches=max_matches)


@mcp.tool()
def read_reference_snippet(path: str, start_line: int = 1, end_line: int = 200) -> dict:
    """
    ТОЛЬКО ЧТЕНИЕ. Ограниченный (максимум 400 строк за раз) диапазон строк
    файла внутри CFG["reference_config"] — path ОТНОСИТЕЛЬНЫЙ (см. поле "path"
    в результате search_reference). Специально ограничен по размеру и не
    позволяет выйти путём за пределы reference_config — чтобы физически нельзя
    было случайно вытащить огромный типовой файл целиком или прочитать что-то
    за пределами справочной папки.
    """
    return _read_reference_snippet(CFG, path, start_line=start_line, end_line=end_line)


@mcp.tool()
def search_reference_semantic(query: str, top_k: int = 10) -> dict:
    """
    ТОЛЬКО ЧТЕНИЕ (#54). Семантический поиск по ВСЕМ процедурам/функциям
    (Экспорт и закрытым — намеренно, см. build_semantic_index.py про то, почему
    закрытые тоже важны: тонкая Экспорт-обёртка часто просто вызывает закрытую
    процедуру с реальной логикой) эталонного корпуса (CFG["reference_config"]).
    В ОТЛИЧИЕ от search_reference (точный regex по тексту) — ищет по СМЫСЛУ:
    "тут нужен такой-то функционал" -> кандидаты, даже если вы не знаете точное
    название процедуры в 1С.

    Требует ПОСТРОЕННЫЙ индекс (см. build_semantic_index.py — разовый скрипт,
    НЕ MCP-инструмент, гоняется вручную/через Bash, ~1.7 часа на полный корпус)
    и ЗАГРУЖЕННУЮ модель text-embedding-embeddinggemma-300m в LM Studio (может
    работать ОДНОВРЕМЕННО с Qwen2.5-Coder-7B — проверено вживую, обе укладываются
    в 8ГБ VRAM при контексте фиксера 32К).

    Возвращает {"results": [{"module","name","kind","line","export","comment","score"}, ...]}
    — путь+имя+doc-комментарий кандидата, БЕЗ полного тела процедуры (для этого —
    read_module(path=<полный путь reference_config/path>, procedure=name)).

    ВАЖНО (генерализация, см. HANDOFF #54): результат — это "как ТИПИЧНО
    делается в ЭТАЛОННОЙ конфигурации", НЕ гарантия, что то же самое есть в
    базе, с которой вы сейчас работаете (другая конфигурация/редакция/масштаб).
    Прежде чем полагаться на найденное как на РЕАЛЬНО переиспользуемое —
    ПРОВЕРЬТЕ существование в ТЕКУЩЕЙ живой базе (describe_metadata/
    describe_common_module/dump_main_config, НЕ этот индекс) — это дешёвая
    детерминированная проверка, model для неё не нужна.
    """
    return _semantic_search(CFG, query, top_k=top_k)
