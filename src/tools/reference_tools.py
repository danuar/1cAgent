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
    """Чтение. Regex по локальному дампу типовой конфигурации (CFG reference_config). glob — подпуть, напр. 'Documents/**/Ext/Form.xml'. → matches[{path,line,match,context}] — фрагменты ~240 симв.; кусок файла — read_reference_snippet."""
    return _search_reference(CFG, pattern, glob=glob, max_matches=max_matches)


@mcp.tool()
def read_reference_snippet(path: str, start_line: int = 1, end_line: int = 200) -> dict:
    """Чтение. Строки start_line..end_line (≤400) файла reference_config по относительному path из search_reference."""
    return _read_reference_snippet(CFG, path, start_line=start_line, end_line=end_line)


@mcp.tool()
def search_reference_semantic(query: str, top_k: int = 10) -> dict:
    """Чтение. Поиск по СМЫСЛУ среди процедур/функций эталонного корпуса (нужен индекс + embeddinggemma в LM Studio). → results[{module,name,kind,line,export,comment,score}]; тело — read_module(path, procedure). Найденное — «как в эталоне», в текущей базе проверять describe_metadata/describe_common_module."""
    return _semantic_search(CFG, query, top_k=top_k)
