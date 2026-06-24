"""RAG corpus ingest CLI.

Akış:

1. ``seeds.yaml`` oku.
2. RSS / web feed'lerini çek (feedparser).
3. Web içeriğini ``trafilatura`` ile temizle.
4. YouTube transkriptlerini ``youtube-transcript-api`` ile çek.
5. Kalite filtresi: min 500 kelime, blacklist kontrolü, kaynak otoritesi
   (``quality`` skoru >= 3).
6. Topic tagging: basit keyword matcher; Lab haftalık LLM ile rafine eder
   (``tag_topics_with_llm`` placeholder).
7. Chunk + embed + ``RAGStore.add``.
8. Cache: ``knowledge/cache/<hash>.json`` (URL bazında dedup).

CLI:
    pa-rag ingest --since 7d
    pa-rag ingest --source-id arxiv_qfin
    pa-rag stats
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

import typer
import yaml

from price_action.logging_config import logger
from price_action.settings import get_settings

from .chunker import chunk_markdown
from .store import RAGStore, hash_text

app = typer.Typer(add_completion=False, help="RAG corpus ingest aracı.")

MIN_WORDS = 500
QUALITY_MIN = 3

_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "pattern": [
        "pin bar", "engulfing", "inside bar", "outside bar", "fakeout",
        "candlestick", "doji", "hammer", "harami", "pattern",
    ],
    "structure": [
        "support", "resistance", "swing", "break of structure", "bos",
        "choch", "wyckoff", "smart money", "order block", "liquidity",
        "structure",
    ],
    "risk_management": [
        "kelly", "position size", "stop loss", "drawdown", "risk per trade",
        "leverage", "anti-fragile", "expectancy", "risk management",
    ],
    "quant_finance": [
        "sharpe", "sortino", "alpha", "beta", "regression", "factor",
        "garch", "stochastic", "calibration", "p-value", "monte carlo",
    ],
    "ml_for_trading": [
        "machine learning", "neural network", "reinforcement", "lstm",
        "xgboost", "random forest", "deep learning", "feature",
    ],
    "market_microstructure": [
        "order book", "spread", "market maker", "liquidity", "kyle",
        "vpin", "tick", "microstructure", "execution",
    ],
    "behavioral_finance": [
        "fomo", "loss aversion", "behavioral", "psychology", "bias",
        "overconfidence", "anchoring", "herding",
    ],
    "regimes": [
        "regime", "bull", "bear", "range", "volatility", "rolling",
        "trend following",
    ],
}


# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------

@dataclass
class IngestItem:
    """Tek bir kaynak tarafından üretilen ingest item'ı."""

    source_id: str
    source_type: str
    url: str
    title: str
    text: str
    author: str = ""
    published_date: str | None = None
    quality: int = 3
    extra_tags: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        if self.extra_tags is None:
            self.extra_tags = []


def _cache_dir() -> Path:
    s = get_settings()
    p = s.knowledge_dir / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_get(url: str) -> dict[str, Any] | None:
    fn = _cache_dir() / f"{hash_text(url)[:32]}.json"
    if not fn.exists():
        return None
    try:
        return json.loads(fn.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(url: str, payload: dict[str, Any]) -> None:
    fn = _cache_dir() / f"{hash_text(url)[:32]}.json"
    fn.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _is_blacklisted(text: str, blacklist: Iterable[str]) -> bool:
    low = text.lower()
    for pat in blacklist:
        if fnmatch(low, pat.lower()):
            return True
    return False


def tag_topics_keyword(text: str) -> list[str]:
    """Hızlı keyword bazlı topic tagger."""
    low = text.lower()
    out: set[str] = set()
    for tag, kws in _TOPIC_KEYWORDS.items():
        for kw in kws:
            if kw in low:
                out.add(tag)
                break
    return sorted(out)


def tag_topics_with_llm(text: str) -> list[str]:  # pragma: no cover - placeholder
    """Lab haftalık LLM rafine etiketleyici — şimdilik no-op (placeholder).

    Lab Scientist bu fonksiyonu LLM agent ile override eder.
    """
    return tag_topics_keyword(text)


def quality_filter(item: IngestItem, blacklist: list[str]) -> tuple[bool, str]:
    """(passes, reason) — item kalite filtresinden geçiyor mu?"""
    if not item.text or not item.text.strip():
        return False, "empty"
    wc = _word_count(item.text)
    if wc < MIN_WORDS:
        return False, f"min_words<{MIN_WORDS}({wc})"
    if item.quality < QUALITY_MIN:
        return False, f"quality<{QUALITY_MIN}"
    if _is_blacklisted(item.url, blacklist) or _is_blacklisted(item.title, blacklist):
        return False, "blacklisted"
    return True, "ok"


# ----------------------------------------------------------------------
# Feed crawler'lar (defensive: paket yoksa boş döner + log)
# ----------------------------------------------------------------------

def fetch_rss(url: str, category_quality: int = 3) -> list[IngestItem]:
    """RSS feed'inden item listesi üretir."""
    cached = _cache_get(url)
    entries: list[dict[str, Any]] = []
    try:
        import feedparser  # type: ignore[import-not-found]

        d = feedparser.parse(url)
        for e in d.entries:
            entries.append(
                {
                    "title": getattr(e, "title", ""),
                    "link": getattr(e, "link", ""),
                    "summary": getattr(e, "summary", ""),
                    "author": getattr(e, "author", "")
                    if hasattr(e, "author")
                    else "",
                    "published": getattr(e, "published", None),
                }
            )
    except Exception as exc:
        logger.warning("rag.rss_fail", extra={"url": url, "err": str(exc)})
        if cached:
            entries = cached.get("entries", [])

    _cache_put(url, {"entries": entries, "fetched_at": datetime.now(timezone.utc).isoformat()})

    items: list[IngestItem] = []
    for e in entries:
        link = e.get("link", "")
        text = (e.get("summary") or "").strip()
        text = _strip_html(text)
        if link and len(text) < MIN_WORDS * 4:
            # Tam içeriği çekmeyi dene
            full = fetch_web_text(link)
            if full and _word_count(full) > _word_count(text):
                text = full
        items.append(
            IngestItem(
                source_id=hash_text(link)[:12],
                source_type="rss",
                url=link,
                title=e.get("title", ""),
                text=text,
                author=e.get("author", "") or "",
                published_date=str(e.get("published") or "")[:10] or None,
                quality=category_quality,
            )
        )
    return items


def fetch_web_text(url: str) -> str:
    """Bir URL'den temiz markdown/text çek (trafilatura)."""
    try:
        import trafilatura  # type: ignore[import-not-found]

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            output_format="markdown",
        )
        return text or ""
    except Exception as exc:
        logger.warning("rag.web_fail", extra={"url": url, "err": str(exc)})
        return ""


def fetch_youtube_transcript(video_url_or_id: str) -> str:
    """YouTube videosunun transkriptini markdown'a yakın metne çevirir."""
    try:
        from youtube_transcript_api import (  # type: ignore[import-not-found]
            YouTubeTranscriptApi,
        )
    except ImportError:  # pragma: no cover
        logger.warning("rag.yt_module_missing")
        return ""
    video_id = _extract_youtube_id(video_url_or_id)
    if not video_id:
        return ""
    try:
        # v1.2.4+: get_transcript() removed; use instance method fetch()
        api_instance = YouTubeTranscriptApi()
        transcript = api_instance.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return "\n".join(s.text for s in transcript)
    except Exception as exc:
        logger.warning("rag.yt_fail", extra={"video": video_id, "err": str(exc)})
        return ""


def _extract_youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    return None


def _strip_html(text: str) -> str:
    if "<" not in text:
        return text
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]

        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", text)


# ----------------------------------------------------------------------
# Ana ingest pipeline
# ----------------------------------------------------------------------

def load_seeds(path: Path | None = None) -> dict[str, Any]:
    s = get_settings()
    p = Path(path) if path else (s.knowledge_dir / "seeds.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def gather_items(
    seeds: dict[str, Any],
    *,
    only_source_id: str | None = None,
    network: bool = True,
) -> list[IngestItem]:
    """Seed config'inden ingest item'ları topla."""
    items: list[IngestItem] = []
    if not network:
        return items

    sources: list[tuple[str, dict[str, Any]]] = []
    for key in (
        "academic_feeds",
        "firm_blogs",
        "practitioner_blogs",
        "crypto_research",
        "extended_academic",
        "extended_practitioner",
    ):
        for entry in seeds.get(key, []) or []:
            sources.append((key, entry))

    for _section, entry in sources:
        sid = entry.get("id", "")
        if only_source_id and sid != only_source_id:
            continue
        stype = entry.get("type", "rss")
        url = entry.get("url", "")
        quality = int(entry.get("quality", 3))
        if not url:
            continue
        if stype == "rss":
            items.extend(fetch_rss(url, category_quality=quality))
        elif stype == "web":
            text = fetch_web_text(url)
            if text:
                items.append(
                    IngestItem(
                        source_id=sid,
                        source_type="web",
                        url=url,
                        title=entry.get("name", sid),
                        text=text,
                        quality=quality,
                    )
                )

    # YouTube
    for entry in seeds.get("youtube", []) or []:
        sid = entry.get("id", "")
        if only_source_id and sid != only_source_id:
            continue
        if entry.get("type") != "channel":
            continue
        # Channel listesini biz çekemiyoruz (yt-dlp gerekir); 'search' tipi
        # CLI çağrısı yt-dlp ile zenginleştirilebilir — şimdilik boş geç.

    return items


def ingest_items(
    items: list[IngestItem],
    seeds: dict[str, Any],
    *,
    store: RAGStore | None = None,
) -> dict[str, int]:
    """Bir item listesini chunk + embed + store akışından geçirir."""
    store = store or RAGStore()
    blacklist = list(seeds.get("blacklist", []) or [])

    stats = {"received": len(items), "passed": 0, "rejected": 0, "added_chunks": 0}
    for item in items:
        ok, reason = quality_filter(item, blacklist)
        if not ok:
            stats["rejected"] += 1
            logger.debug(
                "rag.ingest_reject",
                extra={"source_id": item.source_id, "reason": reason, "url": item.url},
            )
            continue

        topics = tag_topics_keyword(item.text)
        chunks = chunk_markdown(
            item.text,
            base_metadata={
                "source_id": item.source_id,
                "source_type": item.source_type,
                "url": item.url or "",
                "title": item.title or "",
                "author": item.author or "",
                "published_date": item.published_date or "",
                "ingested_date": datetime.now(timezone.utc).date().isoformat(),
                "quality_score": str(item.quality),
                # Chroma where filters need scalar values; ana topic + virgül
                "topic_tag": topics[0] if topics else "",
                "topic_tags_csv": ",".join(topics),
            },
        )
        if not chunks:
            continue

        documents = [c.text for c in chunks]
        metadatas = [c.metadata for c in chunks]
        ids = [hash_text(c.text + (c.metadata.get("url") or "")) for c in chunks]
        added = store.add(documents=documents, metadatas=metadatas, ids=ids)
        stats["added_chunks"] += len(added)
        stats["passed"] += 1

    return stats


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    m = re.fullmatch(r"(\d+)([dhwmy])", value.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
        "w": timedelta(weeks=n),
        "m": timedelta(days=30 * n),
        "y": timedelta(days=365 * n),
    }[unit]
    return datetime.now(timezone.utc) - delta


@app.command()
def ingest(
    since: str = typer.Option(None, help="Pencere: 7d, 24h, 2w, 1m"),
    source_id: str = typer.Option(None, help="Tek bir source_id ile sınırla"),
    seeds_path: Path = typer.Option(None, help="seeds.yaml yolu"),
    dry_run: bool = typer.Option(False, help="Network çağrısı yapma"),
) -> None:
    """Yeni içerikleri çek ve RAG'e ekle."""
    seeds = load_seeds(seeds_path)
    items = gather_items(seeds, only_source_id=source_id, network=not dry_run)
    cutoff = _parse_since(since)
    if cutoff and items:
        filtered = []
        for it in items:
            try:
                pd = datetime.fromisoformat((it.published_date or "")[:10])
                if pd >= cutoff:
                    filtered.append(it)
            except (ValueError, TypeError):
                filtered.append(it)
        items = filtered
    stats = ingest_items(items, seeds)
    typer.echo(json.dumps(stats, ensure_ascii=False))


@app.command()
def stats() -> None:
    """Mevcut corpus istatistikleri."""
    store = RAGStore()
    typer.echo(json.dumps({"count": store.count()}, ensure_ascii=False))


# ----------------------------------------------------------------------
# Query
# ----------------------------------------------------------------------

PREVIEW_CHARS = 240


def _build_where(source_type: str | None, topic: str | None) -> dict | None:
    """Build a ChromaDB ``where`` dict from optional CLI filters.

    If both filters are present we need the ``$and`` operator.
    """
    clauses: list[dict] = []
    if source_type:
        clauses.append({"source_type": source_type})
    if topic:
        clauses.append({"topic_tag": topic})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def run_query(
    text: str,
    *,
    k: int = 8,
    source_type: str | None = None,
    topic: str | None = None,
    full: bool = False,
    store: "RAGStore | None" = None,
) -> list:
    """Execute a RAG query and return hits.

    Separated from the CLI command so it can be called directly in tests.
    """
    store = store or RAGStore()
    where = _build_where(source_type, topic)
    return store.query(text, k=k, where=where)


def format_query_output(
    text: str,
    hits: list,
    *,
    k: int,
    source_type: str | None,
    topic: str | None,
    full: bool,
) -> str:
    """Format query results as a human-readable string."""
    filters: dict = {}
    if source_type:
        filters["source_type"] = source_type
    if topic:
        filters["topic"] = topic

    lines: list[str] = [
        f'k={k} query="{text}" filters={json.dumps(filters, ensure_ascii=False)}',
    ]
    if not hits:
        lines.append("(no results)")
    for i, hit in enumerate(hits, 1):
        m = hit.metadata
        src = m.get("source_id", "")
        author = m.get("author", "")
        stype = m.get("source_type", "")
        ttag = m.get("topic_tag", "")
        header = (
            f"#{i} score={hit.score:.3f} type={stype} src={src}"
            + (f" author={author}" if author else "")
            + (f" topic={ttag}" if ttag else "")
        )
        lines.append(header)
        body = hit.text if full else hit.text[:PREVIEW_CHARS].replace("\n", " ").strip()
        if not full and len(hit.text) > PREVIEW_CHARS:
            body += "..."
        lines.append(f"    {body}")
    return "\n".join(lines)


@app.command()
def query(
    text: str = typer.Argument(..., help="Sorgu metni"),
    k: int = typer.Option(8, "--k", help="Döndürülecek hit sayısı"),
    source_type: str = typer.Option(None, "--source-type", help="Filtre: book | rss | web | youtube"),
    topic: str = typer.Option(None, "--topic", help="topic_tag filtresi"),
    full: bool = typer.Option(False, "--full/--no-full", help="Tam chunk metnini bas"),
) -> None:
    """RAG corpus'unu interaktif olarak sorgula."""
    hits = run_query(text, k=k, source_type=source_type, topic=topic, store=None)
    output = format_query_output(
        text, hits, k=k, source_type=source_type, topic=topic, full=full
    )
    # Use errors='replace' to handle terminals with narrow code pages (e.g. cp1254 on Windows)
    import sys
    sys.stdout.buffer.write((output + "\n").encode(sys.stdout.encoding or "utf-8", errors="replace"))


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
