#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#54: хранилище + поиск векторного индекса — обычный numpy-массив в памяти,
БЕЗ векторной СУБД. Посчитано на реальном корпусе пользователя: ~209К Экспорт-
процедур (768-мерные векторы embeddinggemma-300M) — это ~640МБ float32,
полный перебор косинуса матричным умножением — доли секунды даже на CPU.
Специализированный движок (Milvus/Qdrant и т.п.) оправдан от десятков
МИЛЛИОНОВ векторов или для конкурентной серверной выдачи — ни то, ни другое
не применимо к одному локальному Python-процессу с редкими запросами.
"""
import json
from pathlib import Path

import numpy as np

_INDEX_DIRNAME = "semantic_index"


def index_dir(cfg: dict) -> Path:
    return Path(cfg["runtime_dir"]) / _INDEX_DIRNAME


def save_index(cfg: dict, vectors: list, metadata: list) -> Path:
    """vectors — [[float,...], ...], metadata — параллельный список dict (см.
    reference_chunks.iter_export_chunks) — ДОЛЖНЫ быть в ОДНОМ порядке."""
    if len(vectors) != len(metadata):
        raise ValueError(f"vectors ({len(vectors)}) и metadata ({len(metadata)}) разной длины")
    d = index_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(vectors, dtype=np.float32)
    np.save(d / "vectors.npy", arr)
    with open(d / "metadata.jsonl", "w", encoding="utf-8") as f:
        for m in metadata:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return d


def load_index(cfg: dict):
    """(vectors: np.ndarray, metadata: list) или (None, None), если индекс ещё не построен."""
    d = index_dir(cfg)
    vectors_path, meta_path = d / "vectors.npy", d / "metadata.jsonl"
    if not vectors_path.exists() or not meta_path.exists():
        return None, None
    vectors = np.load(vectors_path)
    metadata = [json.loads(line) for line in meta_path.read_text(encoding="utf-8").splitlines() if line]
    return vectors, metadata


def search(vectors: np.ndarray, metadata: list, query_vector: list, top_k: int = 10) -> list:
    """Косинусное сходство полным перебором — топ-K метаданных + score (по убыванию)."""
    q = np.asarray(query_vector, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
    sims = (vectors / norms) @ q
    top_k = max(1, min(top_k, len(metadata)))
    top_idx = np.argpartition(-sims, top_k - 1)[:top_k]
    top_idx = top_idx[np.argsort(-sims[top_idx])]
    return [{**metadata[i], "score": float(sims[i])} for i in top_idx]
