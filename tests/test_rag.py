"""RAG layer testleri — chunker + ingest dry-run.

ChromaDB / network testleri integration olarak işaretlenir; default skip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from price_action.rag.chunker import chunk_markdown
from price_action.rag.ingest import (
    IngestItem,
    _parse_since,
    quality_filter,
    tag_topics_keyword,
)


# ----------------------------------------------------------------------
# Chunker
# ----------------------------------------------------------------------

def test_chunker_short_doc_single_chunk() -> None:
    md = (
        "# Title\n\nKısa bir paragraf. Bu chunk'a girer.\n\n"
        "## Subsection\n\nBaşka kısa cümle.\n"
    )
    chunks = chunk_markdown(md, chunk_tokens=128, overlap_tokens=16)
    assert len(chunks) == 2
    assert chunks[0].heading_path.startswith("Title")
    assert "Subsection" in chunks[1].heading_path
    for ch in chunks:
        assert ch.token_count > 0
        assert ch.text.strip()


def test_chunker_long_section_splits_with_overlap() -> None:
    body = " ".join(["word"] * 1500)
    md = f"# Big\n\n{body}\n"
    chunks = chunk_markdown(md, chunk_tokens=400, overlap_tokens=50)
    assert len(chunks) >= 3
    assert all(c.heading_path.startswith("Big") for c in chunks)
    # Her chunk text içermeli
    assert all(c.text for c in chunks)


def test_chunker_metadata_propagation() -> None:
    md = "# Sec\n\nContent.\n"
    chunks = chunk_markdown(md, base_metadata={"source_id": "s1", "url": "x"})
    assert chunks
    md0 = chunks[0].metadata
    assert md0["source_id"] == "s1"
    assert md0["heading"].startswith("Sec")


def test_chunker_skips_empty_sections() -> None:
    md = "# A\n\n\n\n## B\n\nbody\n"
    chunks = chunk_markdown(md)
    assert len(chunks) == 1
    assert chunks[0].heading_path.endswith("B")


# ----------------------------------------------------------------------
# Ingest helpers (no network)
# ----------------------------------------------------------------------

def test_topic_tagger_keyword() -> None:
    text = "We use Kelly position sizing and analyze pin bar patterns."
    tags = tag_topics_keyword(text)
    assert "risk_management" in tags
    assert "pattern" in tags


def test_topic_tagger_empty_for_unrelated() -> None:
    tags = tag_topics_keyword("Cooking pasta with garlic.")
    assert tags == []


def test_quality_filter_min_words() -> None:
    item = IngestItem(
        source_id="x", source_type="rss", url="https://x.com/a", title="t",
        text="kısa metin", quality=5,
    )
    ok, reason = quality_filter(item, blacklist=[])
    assert not ok
    assert "min_words" in reason


def test_quality_filter_blacklist() -> None:
    body = " ".join(["word"] * 800)
    item = IngestItem(
        source_id="x", source_type="rss",
        url="https://signal-service.example.com/promo", title="ad",
        text=body, quality=5,
    )
    ok, reason = quality_filter(item, blacklist=["*signal-service*"])
    assert not ok
    assert reason == "blacklisted"


def test_quality_filter_quality_threshold() -> None:
    body = " ".join(["word"] * 800)
    item = IngestItem(
        source_id="x", source_type="rss", url="https://ok.example/a", title="t",
        text=body, quality=2,
    )
    ok, reason = quality_filter(item, blacklist=[])
    assert not ok
    assert "quality" in reason


def test_quality_filter_passes_clean_item() -> None:
    body = " ".join(["word"] * 800)
    item = IngestItem(
        source_id="x", source_type="rss", url="https://ok.example/a", title="t",
        text=body, quality=4,
    )
    ok, reason = quality_filter(item, blacklist=[])
    assert ok and reason == "ok"


def test_parse_since() -> None:
    assert _parse_since("7d") is not None
    assert _parse_since("24h") is not None
    assert _parse_since("2w") is not None
    assert _parse_since(None) is None
    assert _parse_since("garbage") is None


# ----------------------------------------------------------------------
# Ingest dry run — ağ yok
# ----------------------------------------------------------------------

def test_ingest_dry_run_no_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`gather_items(network=False)` boş döner; ingest_items akışı patlamaz."""
    from price_action.rag import ingest as ingest_mod

    seeds = {
        "academic_feeds": [{"id": "x", "type": "rss", "url": "http://x", "quality": 5}],
        "blacklist": [],
    }
    items = ingest_mod.gather_items(seeds, network=False)
    assert items == []


# ----------------------------------------------------------------------
# query command — mocked store
# ----------------------------------------------------------------------

class _MockStore:
    """Minimal RAGStore stand-in that returns canned Hit objects."""

    def __init__(self, hits):
        self._hits = hits

    def query(self, text, *, k=8, where=None):  # noqa: ARG002
        return self._hits[:k]


def _make_hit(
    idx: int,
    text: str = "Some chunk text about price action.",
    source_type: str = "book",
    source_id: str = "brooks_summary",
    author: str = "Al Brooks",
    topic_tag: str = "pattern",
    score: float = 0.75,
):
    from price_action.rag.store import Hit
    return Hit(
        id=f"id{idx}",
        text=text,
        score=score,
        metadata={
            "source_type": source_type,
            "source_id": source_id,
            "author": author,
            "topic_tag": topic_tag,
        },
    )


def test_run_query_returns_hits() -> None:
    """run_query passes text+where through to the store and returns hits."""
    from price_action.rag.ingest import run_query

    hits_in = [_make_hit(i) for i in range(3)]
    mock = _MockStore(hits_in)
    result = run_query("pin bar", k=2, store=mock)
    assert len(result) == 2
    assert result[0] is hits_in[0]


def test_run_query_source_type_filter() -> None:
    """source_type filter is wired into where dict."""
    from price_action.rag.ingest import _build_where, run_query

    where = _build_where(source_type="book", topic=None)
    assert where == {"source_type": "book"}

    where2 = _build_where(source_type="rss", topic="pattern")
    assert where2 == {"$and": [{"source_type": "rss"}, {"topic_tag": "pattern"}]}

    where3 = _build_where(source_type=None, topic=None)
    assert where3 is None


def test_format_query_output_no_results() -> None:
    from price_action.rag.ingest import format_query_output

    out = format_query_output("pin bar", [], k=8, source_type=None, topic=None, full=False)
    assert "no results" in out
    assert 'query="pin bar"' in out


def test_format_query_output_preview() -> None:
    from price_action.rag.ingest import PREVIEW_CHARS, format_query_output

    long_text = "x" * 500
    hits = [_make_hit(1, text=long_text)]
    out = format_query_output("pin bar", hits, k=8, source_type=None, topic=None, full=False)
    assert "..." in out
    # Preview portion should not exceed PREVIEW_CHARS + ellipsis overhead
    lines = out.splitlines()
    body_line = lines[-1].strip()
    assert len(body_line) <= PREVIEW_CHARS + 10


def test_format_query_output_full_text() -> None:
    from price_action.rag.ingest import format_query_output

    long_text = "y" * 500
    hits = [_make_hit(1, text=long_text)]
    out = format_query_output("pin bar", hits, k=8, source_type=None, topic=None, full=True)
    # Full text — no ellipsis, all chars present
    assert "..." not in out
    assert "y" * 500 in out


def test_format_query_output_header_fields() -> None:
    from price_action.rag.ingest import format_query_output

    hits = [_make_hit(1, score=0.446, source_type="book", source_id="brooks_summary",
                      author="Al Brooks", topic_tag="pattern")]
    out = format_query_output("pin bar", hits, k=8, source_type=None, topic=None, full=False)
    assert "score=0.446" in out
    assert "type=book" in out
    assert "src=brooks_summary" in out
    assert "author=Al Brooks" in out
    assert "topic=pattern" in out


def test_run_query_empty_store() -> None:
    """Empty store returns empty list without errors."""
    from price_action.rag.ingest import run_query

    mock = _MockStore([])
    result = run_query("anything", k=5, store=mock)
    assert result == []


# ----------------------------------------------------------------------
# RAGStore — chromadb varsa
# ----------------------------------------------------------------------

@pytest.mark.integration
def test_rag_store_add_and_query(tmp_path: Path) -> None:
    """Gerçek ChromaDB ile add+query (integration; CI'da skip)."""
    from price_action.rag.store import RAGStore

    store = RAGStore(persist_dir=tmp_path / "chroma")
    docs = [
        "Pin bar formation tested across BTC daily charts.",
        "Risk management with Kelly criterion and ATR-based sizing.",
    ]
    metas = [
        {"source_id": "test1", "topic_tag": "pattern"},
        {"source_id": "test2", "topic_tag": "risk_management"},
    ]
    ids = store.add(documents=docs, metadatas=metas)
    assert len(ids) == 2
    hits = store.query("pin bar", k=2)
    assert hits, "no hits"
