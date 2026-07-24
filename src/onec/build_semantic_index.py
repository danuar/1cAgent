#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#54: РАЗОВЫЙ сборочный скрипт семантического индекса — НЕ MCP-инструмент (см.
HANDOFF #54 про то, почему): полный прогон по реальному корпусу пользователя —
~642К процедур/функций, ~1.7 часа на эмбеддинг при батче 256 (~9.5-10мс/чанк,
измерено вживую). Это НАМНОГО дольше типичного job_status-паттерна (тот рассчитан
на минуты, не часы) — гонять как обычный async-инструмент означало бы сотни
последовательных job_status-опросов из будущей сессии, только тратя её ходы.
Поэтому — отдельный скрипт, запускается РУКАМИ (или Claude через Bash) с
выводом прогресса в stdout, самодостаточен.

Чекпоинты: сохраняем ЧАСТИЧНЫЙ результат каждые _CHECKPOINT_BATCHES батчей —
при сбое (обрыв LM Studio, перезагрузка) теряем максимум пару минут, не весь
прогон. Векторы копятся в ПРЕДВЫДЕЛЕННЫЙ numpy-массив (известен total count
после первого прохода чанкинга) — без O(n^2) роста через повторные vstack.

Запуск: python -m src.onec.build_semantic_index
"""
import sys
import time
from pathlib import Path

import numpy as np

from src.core.config import CFG
from src.onec.reference_chunks import iter_export_chunks, chunk_embed_text
from src.onec.embeddings_client import embed_batch, embeddings_available, BATCH_SIZE
from src.onec import semantic_index

_CHECKPOINT_BATCHES = 50  # #54: ~50 батчей по 256 = ~12800 чанков = ~2 минуты — приемлемый риск потери прогресса
_EMBED_DIM = 768  # #54: подтверждено живым запросом к text-embedding-embeddinggemma-300m


def build(reference_root: str = None, checkpoint_batches: int = _CHECKPOINT_BATCHES) -> Path:
    root = Path(reference_root or CFG["reference_config"])
    if not root.is_dir():
        raise SystemExit(f"reference_config не найден: {root}")
    if not embeddings_available():
        raise SystemExit("LM Studio недоступен или модель text-embedding-embeddinggemma-300m не загружена")

    print(f"[1/2] Чанкинг корпуса: {root}", flush=True)
    t0 = time.time()
    chunks = list(iter_export_chunks(root))
    n = len(chunks)
    print(f"      найдено чанков: {n}, время: {time.time()-t0:.0f}с", flush=True)

    vectors = np.zeros((n, _EMBED_DIM), dtype=np.float32)
    done = 0
    t0 = time.time()
    print(f"[2/2] Эмбеддинг {n} чанков батчами по {BATCH_SIZE}...", flush=True)
    for batch_no, start in enumerate(range(0, n, BATCH_SIZE), start=1):
        batch = chunks[start:start + BATCH_SIZE]
        texts = [chunk_embed_text(c) for c in batch]
        vecs = embed_batch(texts)
        if len(vecs) != len(batch):
            raise RuntimeError(f"embed_batch вернул {len(vecs)} векторов на {len(batch)} текстов — несовпадение")
        actual_dim = len(vecs[0]) if vecs else _EMBED_DIM
        if actual_dim != _EMBED_DIM:
            raise RuntimeError(f"неожиданная размерность эмбеддинга: {actual_dim} (ожидалось {_EMBED_DIM})")
        vectors[start:start + len(vecs)] = vecs
        done = start + len(vecs)

        if batch_no % 10 == 0 or done >= n:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (n - done) / rate if rate > 0 else 0
            print(f"      {done}/{n} ({100*done/n:.1f}%), "
                  f"{elapsed:.0f}с прошло, ETA {eta:.0f}с, {rate:.0f} чанк/с", flush=True)

        if batch_no % checkpoint_batches == 0 or done >= n:
            d = semantic_index.save_index(CFG, vectors[:done].tolist(), chunks[:done])
            print(f"      [чекпоинт] сохранено {done} записей -> {d}", flush=True)

    print(f"Готово. Всего {done} чанков, время: {time.time()-t0:.0f}с", flush=True)
    return semantic_index.index_dir(CFG)


if __name__ == "__main__":
    build()
