"""Yüksek seviye RAG sorgu API'si.

Researcher / Lab / CEO tarafından çağrılır. Doğrudan ChromaDB'yi açmaz;
``RAGStore`` üzerinden çalışır.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from price_action.logging_config import logger

from .store import Hit, RAGStore

_default_store: RAGStore | None = None


def get_default_store() -> RAGStore:
    global _default_store
    if _default_store is None:
        _default_store = RAGStore()
    return _default_store


def reset_default_store() -> None:
    """Test fixture'larında kullanılır."""
    global _default_store
    _default_store = None


def retrieve(
    query: str,
    *,
    k: int = 8,
    topic_tags: list[str] | None = None,
    store: RAGStore | None = None,
) -> list[Hit]:
    """Genel amaçlı RAG sorgusu.

    ``topic_tags`` verilirse Chroma `where` ile sadece ilgili etiketli
    chunk'lar döndürülür (tek tag için exact match, çoklu için $in).
    """
    store = store or get_default_store()
    where: dict[str, Any] | None = None
    if topic_tags:
        if len(topic_tags) == 1:
            where = {"topic_tag": topic_tags[0]}
        else:
            where = {"topic_tag": {"$in": list(topic_tags)}}
    hits = store.query(query, k=k, where=where)
    logger.debug(
        "rag.retrieve",
        extra={"q": query[:80], "k": k, "topic_tags": topic_tags, "hits": len(hits)},
    )
    return hits


def retrieve_for_hypothesis(
    hypothesis_text: str,
    *,
    k: int = 10,
    store: RAGStore | None = None,
) -> list[Hit]:
    """Researcher hipotez metninin alıntı/destek için kullanılır.

    Daha geniş k (default 10) ve `pattern` / `risk_management` /
    `quant_finance` gibi araştırma odaklı topic'leri öncelendirir.
    """
    # Topic filter intentionally broad — book summaries may bucket into
    # behavioral_finance / regimes via the keyword tagger; semantic
    # similarity already prioritizes relevance, so a narrow filter only
    # excludes valid PA literature without improving precision.
    research_topics = [
        "pattern",
        "structure",
        "risk_management",
        "quant_finance",
        "ml_for_trading",
        "market_microstructure",
        "regimes",
        "behavioral_finance",
    ]
    return retrieve(hypothesis_text, k=k, topic_tags=research_topics, store=store)


def summarize_recent_additions(
    since_date: datetime,
    *,
    store: RAGStore | None = None,
    limit: int = 200,
) -> list[Hit]:
    """``since_date`` sonrası eklenmiş chunk'ları döndürür.

    `ingested_date` metadata alanına göre filtreler. Lab haftalık RAG refresh
    raporunda kullanır.
    """
    store = store or get_default_store()
    iso = since_date.date().isoformat()
    col = store._ensure_collection()  # noqa: SLF001  - dahili helper
    try:
        n = col.count()
    except Exception:
        n = 0
    if n == 0:
        return []
    try:
        result = col.get(where={"ingested_date": {"$gte": iso}}, limit=limit)
    except Exception as exc:
        logger.warning("rag.summary_filter_failed", extra={"err": str(exc)})
        return []
    ids = result.get("ids") or []
    docs = result.get("documents") or []
    metas = result.get("metadatas") or []
    out: list[Hit] = []
    for _id, doc, meta in zip(ids, docs, metas):
        out.append(Hit(id=_id, text=doc or "", score=1.0, metadata=dict(meta or {})))
    return out
