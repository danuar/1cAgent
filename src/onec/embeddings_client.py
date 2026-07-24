#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#54: клиент к OpenAI-совместимому /v1/embeddings. БЕЗ зависимости от роли
фиксера (НЕ импортирует fixer.py — тот сам импортирует config.py, импорт в
обратную сторону создал бы цикл config->bootstrap->...; оба берут LM_KEY/URL
из config.py независимо): embeddinggemma-300M — ОТДЕЛЬНАЯ модель.

#60: URL теперь EMBED_MODEL_BASE_URL из config.py, НЕ обязательно тот же порт,
что у фиксера — при backend="lmstudio" оба на одном порту (проверено вживую:
обе модели разом умещаются в 8ГБ VRAM при контексте фиксера 32К — см. HANDOFF
#54), при backend="llama_server" — у эмбеддингов СВОЙ порт (один llama-server
процесс = одна модель, см. ensure_models_running).

Модель подтверждена реальным запросом: POST /v1/embeddings,
model="text-embedding-embeddinggemma-300m" -> 768-мерный вектор, ~9.5-10мс на
чанк при батче 256-512 (дальше не ускоряется — плато).
"""
import json
import urllib.request

from src.core.config import EMBED_MODEL_BASE_URL as LM_BASE, LM_KEY, EMBED_MODEL_LMS_KEY as EMBED_MODEL

BATCH_SIZE = 256  # #54: эмпирически — 256-512 уже плато (~9.5-10мс/чанк), больше не ускоряет


def embed_batch(texts: list, model: str = EMBED_MODEL, timeout: int = 120) -> list:
    """texts -> [[float, ...], ...] В ТОМ ЖЕ ПОРЯДКЕ. ОДИН HTTP-запрос на ВЕСЬ
    список — резать на батчи по BATCH_SIZE должен вызывающий код (см.
    build_semantic_index.py), эта функция сама не режет."""
    if not texts:
        return []
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        LM_BASE + "/embeddings", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + LM_KEY},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return [item["embedding"] for item in data["data"]]


def embeddings_available(model: str = EMBED_MODEL, timeout: float = 2.0) -> bool:
    """Быстрая проверка, что LM Studio поднят И модель эмбеддингов реально загружена
    (не только Qwen) — тот же паттерн, что fixer.qwen_available()."""
    try:
        req = urllib.request.Request(LM_BASE + "/models",
            headers={"Authorization": "Bearer " + LM_KEY})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return any(m.get("id") == model for m in data.get("data", []))
    except Exception:
        return False
