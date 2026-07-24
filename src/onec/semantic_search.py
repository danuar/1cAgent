#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#54: запрос к семантическому индексу — тонкая склейка embeddings_client (эмбеддинг
запроса) + semantic_index (загрузка индекса + косинусный поиск). Индекс строится
ОТДЕЛЬНО, разово, см. build_semantic_index.py — эта функция только ЧИТАЕТ
готовый индекс, ничего не пересчитывает.

ВАЖНО (см. HANDOFF #54 про генерализацию): результат — ПУТИ/ИМЕНА кандидатов
из ЭТАЛОННОГО корпуса (как это ТИПИЧНО делается в 1С), НЕ гарантия, что то же
самое есть в базе, с которой вы сейчас работаете. Дальше — read_module(path,
procedure=Имя) на найденный путь, а для проверки существования В ТЕКУЩЕЙ живой
базе — describe_metadata/describe_common_module/dump_main_config (см. HANDOFF),
НЕ этот индекс.
"""
from src.onec.embeddings_client import embed_batch, embeddings_available
from src.onec import semantic_index


def semantic_search(cfg: dict, query: str, top_k: int = 10) -> dict:
    if not embeddings_available():
        return {"ok": False, "reason": "LM Studio недоступен или text-embedding-embeddinggemma-300m не загружена"}
    vectors, metadata = semantic_index.load_index(cfg)
    if vectors is None:
        return {"ok": False, "reason": "индекс ещё не построен — см. build_semantic_index.py"}
    qvec = embed_batch([query])[0]
    results = semantic_index.search(vectors, metadata, qvec, top_k=top_k)
    return {"ok": True, "query": query, "total_indexed": len(metadata), "results": results}
