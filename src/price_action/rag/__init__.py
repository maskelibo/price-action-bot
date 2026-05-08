"""RAG layer — chunker, ChromaDB vector store, retrieval ve ingest CLI.

Yüksek seviye akış:

1. ``ingest.py`` — feed crawl'ı + temizlik + chunk + embed + store.
2. ``chunker.py`` — markdown'a duyarlı chunking (512 token, 64 overlap).
3. ``store.RAGStore`` — ChromaDB persistent client wrapper.
4. ``retrieve.py`` — Researcher / Lab tarafından çağrılan sorgu API'si.

Tüm operasyonlar dosya/disk tabanlıdır; ChromaDB persistent client ile
``settings.chroma_path`` altında durur.
"""
from __future__ import annotations

from .chunker import Chunk, chunk_markdown
from .retrieve import Hit, retrieve, retrieve_for_hypothesis, summarize_recent_additions
from .store import RAGStore

__all__ = [
    "Chunk",
    "Hit",
    "RAGStore",
    "chunk_markdown",
    "retrieve",
    "retrieve_for_hypothesis",
    "summarize_recent_additions",
]
