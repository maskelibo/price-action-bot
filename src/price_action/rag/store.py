"""ChromaDB persistent vector store wrapper.

Embedding modeli: ``sentence-transformers/all-MiniLM-L6-v2`` (default).
Sabit collection adı: ``price_action_corpus``.

Hash dedup: aynı ``content_hash`` için ekleme idempotent (mevcut ID'ler
atlanır). Filtreler ChromaDB ``where`` parametresine eşlenir.

Not: Test ortamında `chroma_path` parametresi izole bir tmp_path olabilir;
init sırasında client her zaman ``persist_directory`` kullanır.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from price_action.logging_config import logger
from price_action.settings import get_settings

DEFAULT_COLLECTION = "price_action_corpus"
DEFAULT_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Hit:
    """Bir retrieval isabeti."""

    id: str
    text: str
    score: float  # 1 - distance (yüksek = iyi); chroma cosine için
    metadata: dict[str, Any]


class RAGStore:
    """ChromaDB persistent client wrapper.

    Kullanım:
        store = RAGStore()
        store.add(documents=["..."], metadatas=[{"source_id": ...}], ids=[...])
        hits = store.query("hipotez metni", k=8, filter={"topic_tag": "pattern"})
    """

    def __init__(
        self,
        *,
        persist_dir: Path | None = None,
        collection_name: str = DEFAULT_COLLECTION,
        embed_model: str = DEFAULT_EMBED_MODEL,
    ) -> None:
        self.persist_dir: Path = (persist_dir or get_settings().chroma_path).resolve()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embed_model = embed_model
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------
    # Lazy client init
    # ------------------------------------------------------------------

    def _ensure_collection(self):  # type: ignore[no-untyped-def]
        if self._collection is not None:
            return self._collection
        try:
            import chromadb  # type: ignore[import-not-found]
            from chromadb.config import Settings as ChromaSettings  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "chromadb yüklü değil — `pip install chromadb` gerekir"
            ) from exc

        try:
            from chromadb.utils.embedding_functions import (  # type: ignore[import-not-found]
                SentenceTransformerEmbeddingFunction,
            )

            embed_fn = SentenceTransformerEmbeddingFunction(model_name=self.embed_model)
        except Exception as exc:  # pragma: no cover - test/CI'da ağ yok
            logger.warning(
                "rag.embed_fn_unavailable_using_default", extra={"err": str(exc)}
            )
            embed_fn = None

        client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self._client = client
        if embed_fn is not None:
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embed_fn,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def add(
        self,
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
        ids: Sequence[str] | None = None,
    ) -> list[str]:
        """Belgeleri ekler. Aynı ID/hash daha önce eklendiyse atlanır.

        Returns: gerçekten eklenen id'ler.
        """
        if len(documents) != len(metadatas):
            raise ValueError("documents/metadatas uzunluğu eşit olmalı")
        col = self._ensure_collection()

        if ids is None:
            ids_resolved = [hash_text(d) for d in documents]
        else:
            ids_resolved = list(ids)

        # Hash dedup — mevcut ID'leri çek
        try:
            existing = col.get(ids=ids_resolved).get("ids", [])
        except Exception:
            existing = []
        existing_set = set(existing)

        new_docs: list[str] = []
        new_meta: list[dict[str, Any]] = []
        new_ids: list[str] = []
        for doc, meta, _id in zip(documents, metadatas, ids_resolved):
            if _id in existing_set:
                continue
            # content_hash metadata'ya yaz
            meta = {**meta, "content_hash": _id}
            new_docs.append(doc)
            new_meta.append(meta)
            new_ids.append(_id)

        if not new_docs:
            logger.debug(
                "rag.add_dedup_skip", extra={"requested": len(documents), "added": 0}
            )
            return []

        col.add(documents=new_docs, metadatas=new_meta, ids=new_ids)
        logger.info(
            "rag.add",
            extra={
                "added": len(new_ids),
                "skipped": len(documents) - len(new_ids),
                "collection": self.collection_name,
            },
        )
        return new_ids

    # ------------------------------------------------------------------
    # Sorgu
    # ------------------------------------------------------------------

    def query(
        self,
        text: str,
        *,
        k: int = 8,
        where: dict[str, Any] | None = None,
    ) -> list[Hit]:
        """En yakın ``k`` chunk'u döndürür."""
        col = self._ensure_collection()
        # Empty collection check
        try:
            n = col.count()
        except Exception:
            n = 0
        if n == 0:
            return []
        k_eff = max(1, min(k, n))
        result = col.query(query_texts=[text], n_results=k_eff, where=where or None)
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]

        hits: list[Hit] = []
        for _id, doc, meta, dist in zip(ids, docs, metas, dists):
            score = 1.0 - float(dist)
            hits.append(Hit(id=_id, text=doc, score=score, metadata=dict(meta or {})))
        return hits

    def count(self) -> int:
        col = self._ensure_collection()
        try:
            return int(col.count())
        except Exception:
            return 0

    def reset(self) -> None:
        """Collection'ı temizle (test fixture'ları için)."""
        col = self._ensure_collection()
        try:
            col.delete(where={})  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("rag.reset_fail", extra={"err": str(exc)})
